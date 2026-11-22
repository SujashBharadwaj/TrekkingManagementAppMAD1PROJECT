"""Throwaway trekkers ("walkers"), housekeeping and limits for the portfolio's agents.

Each portfolio visit has a random UUID v4: the MCP agent sends it in the
MM-Visit-Id header, and the browser agent in the body of POST /demo/walker. The
visit's first booking over MCP, or its first /demo/walker call, makes a trekker
called walker-<first 8 hex digits>. Nobody can sign in as a walker until
/demo/walker gives it a random password, and each call replaces the last one. Every
MCP call and every /demo/walker call first deletes walkers older than an hour, with
their bookings, giving back their seats. So two visitors never see each other's
bookings, and the demo tidies up after itself without a scheduled job (Render's
free tier has none).
"""
import re
import secrets
from datetime import timedelta

from sqlalchemy import DateTime, String, and_, delete, func, insert, literal, or_, select, update
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from models import (db, Booking, McpToolCall, McpWalker, Review, StaffApplication, StaffReview,
                    TrekPhoto, User, utc_now)
from services.bookings import release

WALKER_LIFETIME = timedelta(minutes=60)
CALLS_PER_VISIT_PER_HOUR = 12
CALLS_PER_MINUTE = 60  # across every visit, and calls without one
NEW_WALKERS_PER_MINUTE = 30  # across every visit, over MCP and /demo/walker alike
PASSWORD_BYTES = 16  # 128 random bits: a 22-character password from secrets.token_urlsafe
BUSY = 'The demo is busy right now. Please try again in a minute.'

# Werkzeug's pbkdf2:sha256, as for every password in the app, so /login checks a
# walker's like anyone's. Key stretching only protects guessable passwords, and a
# walker's is 128 random bits (or 256 that nobody keeps), so 1,000 rounds instead
# of the default million keeps making and checking one cheap on Render's small CPU.
_HASH_METHOD = 'pbkdf2:sha256:1000'

_UUID4 = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}')
_calls = McpToolCall.__table__
_users = User.__table__

# What a signed-in walker could leave on the website besides bookings, deleted with
# it so nothing is left pointing at a missing user (an admin page would trip on it).
_LEFT_BEHIND = (
    (StaffApplication.__table__, 'user_id'),
    (Review.__table__, 'user_id'),
    (StaffReview.__table__, 'user_id'),
    (TrekPhoto.__table__, 'uploaded_by'),
)


class DemoBusy(Exception):
    """Too many new walkers this minute. str(error) is the plain sentence to show."""


class Visit:
    """One portfolio visit, picked by its id (the MM-Visit-Id header), which may be absent."""

    def __init__(self, header_value):
        value = (header_value or '').strip().lower()
        self.sent = header_value is not None
        self.id = value if _UUID4.fullmatch(value) else None

    @property
    def malformed(self):
        """True when the header was sent but isn't a UUID v4."""
        return self.sent and self.id is None

    def walker(self):
        """This visit's McpWalker, or None if it hasn't booked anything yet."""
        if self.id is None:
            return None
        return McpWalker.query.filter_by(visit_id=self.id).first()

    def walker_or_create(self):
        """This visit's McpWalker, made now if this is its first write. None if that failed.

        Raises DemoBusy when making one would pass NEW_WALKERS_PER_MINUTE.
        """
        return self.walker() or _create_walker(self.id)


def _create_walker(visit_id, now=None):
    now = now or utc_now()
    digits = visit_id.replace('-', '')
    for suffix in (digits[:8], digits):  # the long name only if a real account took the short one
        username, email = f'walker-{suffix}', f'walker-{suffix}@demo.invalid'
        if User.query.filter(or_(User.username == username, User.email == email)).first() is None:
            break
    # 256 random bits that nobody keeps, so nobody can sign in as a new walker until
    # /demo/walker gives it a password of its own.
    secret_hash = generate_password_hash(secrets.token_hex(32), method=_HASH_METHOD)
    user = User(username=username, email=email, password_hash=secret_hash,
                role='trekker', status='active')
    db.session.add(user)
    try:
        # From this INSERT until the commit, this request holds SQLite's write lock,
        # so two requests can't both take the last place under the cap.
        db.session.flush()
        made_lately = db.session.query(func.count(McpWalker.id)).filter(
            McpWalker.created_at > now - timedelta(minutes=1)).scalar()
        if made_lately >= NEW_WALKERS_PER_MINUTE:
            db.session.rollback()
            raise DemoBusy(BUSY)
        walker = McpWalker(visit_id=visit_id, user_id=user.id, created_at=now)
        db.session.add(walker)
        db.session.commit()
        return walker
    except IntegrityError:
        # Another request from the same visit made its walker first: use that one.
        db.session.rollback()
        return McpWalker.query.filter_by(visit_id=visit_id).first()


def sign_in_details(walker):
    """Give `walker` a new random password and return (username, password), or None
    if housekeeping removed the walker meanwhile. Its last password stops working.
    Commits.
    """
    password = secrets.token_urlsafe(PASSWORD_BYTES)
    changed = db.session.execute(
        update(_users).where(_users.c.id == walker.user_id)
        .values(password_hash=generate_password_hash(password, method=_HASH_METHOD))
    ).rowcount
    if changed != 1:
        db.session.rollback()
        return None
    username = db.session.execute(select(_users.c.username).where(_users.c.id == walker.user_id)).scalar()
    db.session.commit()
    return username, password


def housekeeping(now=None):
    """Delete walkers older than an hour with their bookings, giving back the seats of
    any still Booked, and forget tool calls older than an hour.

    Writes only when there's something to delete, so most calls cost two quick reads.
    """
    now = now or utc_now()
    cutoff = now - WALKER_LIFETIME
    expired = McpWalker.query.filter(McpWalker.created_at < cutoff).all()
    old_calls = db.session.query(McpToolCall.id).filter(McpToolCall.called_at < cutoff).first()
    if not expired and old_calls is None:
        return
    for walker in expired:
        active = db.session.query(Booking.id, Booking.trek_id, Booking.slots_booked).filter(
            Booking.user_id == walker.user_id, Booking.status == 'Booked').all()
        for booking_id, trek_id, seats in active:
            release(booking_id, trek_id, seats)  # conditional, so seats come back once
        db.session.execute(delete(Booking.__table__).where(Booking.__table__.c.user_id == walker.user_id))
        for table, column in _LEFT_BEHIND:
            db.session.execute(delete(table).where(table.c[column] == walker.user_id))
        db.session.execute(delete(McpWalker.__table__).where(McpWalker.__table__.c.id == walker.id))
        db.session.execute(delete(_users).where(_users.c.id == walker.user_id))
    db.session.execute(delete(_calls).where(_calls.c.called_at < cutoff))
    db.session.commit()


def record_call(visit_id, tool, now=None):
    """Count one tool call, or return the plain sentence that refuses it.

    The count and the insert are one INSERT ... SELECT ... WHERE statement, so two
    calls at the same moment can't both take the last place under a limit.
    """
    now = now or utc_now()
    in_last_minute = (select(func.count()).select_from(_calls)
                      .where(_calls.c.called_at > now - timedelta(minutes=1)).scalar_subquery())
    allowed = in_last_minute < CALLS_PER_MINUTE
    if visit_id is not None:
        allowed = and_(allowed, _visit_calls(visit_id, now).scalar_subquery() < CALLS_PER_VISIT_PER_HOUR)
    row = select(literal(visit_id, String()), literal(tool, String()), literal(now, DateTime())).where(allowed)
    inserted = db.session.execute(
        insert(_calls).from_select(['visit_id', 'tool', 'called_at'], row)).rowcount
    db.session.commit()
    if inserted == 1:
        return None
    if visit_id is not None and db.session.execute(_visit_calls(visit_id, now)).scalar() >= CALLS_PER_VISIT_PER_HOUR:
        return (f'This visit has used its {CALLS_PER_VISIT_PER_HOUR} tool calls for the hour. '
                'Please try again later.')
    return BUSY


def _visit_calls(visit_id, now):
    return (select(func.count()).select_from(_calls)
            .where(_calls.c.visit_id == visit_id, _calls.c.called_at > now - timedelta(hours=1)))
