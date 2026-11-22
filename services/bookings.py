"""Booking rules for Mountains & Maggi, shared by the website and the MCP tools.

Each rule lives here once, so the trekker pages (routes/trekker_routes.py) and the
AI agent's tools (mcp_server/tools.py) can't drift apart. A refusal raises
BookingError with one plain sentence that either side can show as it is.

Seats are taken with a conditional UPDATE (`... WHERE available_slots >= n`), so
two requests for the last seats can't both succeed: SQLite runs each statement
atomically, and only one of them still finds enough seats.
"""
from datetime import date

from sqlalchemy import func, update

from models import db, Booking, McpWalker, Trek, User

INSURANCE_PER_SEAT = 500  # rupees per seat, as the trek page says

# The demo's limits for throwaway walkers (mcp_server/visits.py), whether the AI
# agent books through the MCP tools or signs in and books on the website. Real
# accounts have neither limit.
WALKER_MAX_SEATS = 4
WALKER_MAX_ACTIVE = 3

_treks = Trek.__table__
_bookings = Booking.__table__


class BookingError(Exception):
    """A booking or a cancellation was refused.

    reason:   one plain sentence for a person or an agent.
    code:     a short, stable name for the rule that refused it.
    category: the flash category the website shows the reason with.
    """

    def __init__(self, reason, code, category='danger'):
        super().__init__(reason)
        self.reason = reason
        self.code = code
        self.category = category


def quote(price, seats, insurance):
    """Return (base, insurance, total) in rupees for `seats` seats at `price` each."""
    base = price * seats
    cover = INSURANCE_PER_SEAT * seats if insurance else 0
    return base, cover, base + cover


def seats_left_reason(seats_left):
    if seats_left <= 0:
        return 'That date is sold out.'
    if seats_left == 1:
        return 'Only 1 seat is left on that date.'
    return f'Only {seats_left} seats are left on that date.'


def too_many_reason(limit):
    return f'You already have {limit} active bookings, which is the limit. Cancel one before booking another.'


def too_many_seats_reason(limit):
    return f'You can book at most {limit} seats at a time.'


def limits_for(user_id):
    """(max_seats, max_active) for `user_id`: the demo's limits for a walker, or
    (None, None), no limits, for a real account."""
    is_walker = db.session.query(McpWalker.id).filter(McpWalker.user_id == user_id).first() is not None
    return (WALKER_MAX_SEATS, WALKER_MAX_ACTIVE) if is_walker else (None, None)


def check(trek, user_id, seats, today=None, max_active=None, max_seats=None):
    """Raise BookingError if `user_id` can't book `seats` seats on `trek`.

    Read-only. user_id may be None (an agent visit that hasn't booked yet), which
    skips the rules about the user's own bookings. max_seats caps one booking and
    max_active how many Booked bookings one user may hold: limits_for() gives a
    walker's, and both are None (no cap) for a real account.
    """
    today = today or date.today()
    if seats < 1:
        raise BookingError('Book at least 1 seat.', 'bad_seats')
    if max_seats is not None and seats > max_seats:
        raise BookingError(too_many_seats_reason(max_seats), 'too_many_seats')
    if trek.status != 'Open':
        raise BookingError('This trek is not open for bookings.', 'not_open')
    if trek.start_date <= today:
        raise BookingError("This trek has already started, so it can't be booked.", 'started')
    if trek.available_slots < seats:
        raise BookingError(seats_left_reason(trek.available_slots), 'sold_out')
    if user_id is not None:
        if _has_active_booking(user_id, trek.id):
            raise BookingError('You already have a booking on this trek.', 'already_booked', 'warning')
        if max_active is not None and _active_count(user_id) >= max_active:
            raise BookingError(too_many_reason(max_active), 'too_many')


def book(user_id, trek_id, seats, insurance=False, medical_info=None, dietary_needs=None,
         max_active=None, max_seats=None, today=None):
    """Book `seats` seats on trek `trek_id` for `user_id`, commit, and return the Booking."""
    today = today or date.today()
    trek = db.session.get(Trek, trek_id)
    if trek is None:
        raise BookingError(f"There's no trek with id {trek_id}.", 'no_trek')
    check(trek, user_id, seats, today, max_active, max_seats)  # the usual refusals, before any write
    base, cover, total = quote(trek.price, seats, insurance)

    # Take the seats only if they are still there. The WHERE clause repeats the
    # checks above, so a request that lost a race changes nothing.
    taken = db.session.execute(
        update(_treks)
        .where(_treks.c.id == trek.id,
               _treks.c.status == 'Open',
               _treks.c.start_date > today,
               _treks.c.available_slots >= seats)
        .values(available_slots=_treks.c.available_slots - seats)
    ).rowcount
    if taken != 1:
        db.session.rollback()
        check(trek, user_id, seats, today, max_active, max_seats)  # names what changed meanwhile
        raise BookingError('Those seats were just taken. Please try again.', 'sold_out')

    # From that UPDATE until the commit, this request holds SQLite's write lock, so
    # the checks below see every booking made before it and none can slip in between.
    if db.session.query(User.id).filter(User.id == user_id).first() is None:
        db.session.rollback()
        raise BookingError('This account no longer exists.', 'no_user')
    if _has_active_booking(user_id, trek.id):
        db.session.rollback()
        raise BookingError('You already have a booking on this trek.', 'already_booked', 'warning')
    if max_active is not None and _active_count(user_id) >= max_active:
        db.session.rollback()
        raise BookingError(too_many_reason(max_active), 'too_many')

    booking = Booking(user_id=user_id, trek_id=trek.id, slots_booked=seats, status='Booked',
                      has_insurance=bool(insurance), total_price=total,
                      medical_info=medical_info, dietary_needs=dietary_needs)
    db.session.add(booking)
    db.session.commit()
    return booking


def cancel(user_id, booking_id):
    """Cancel `user_id`'s booking `booking_id`, give its seats back and commit.

    Returns (booking, seats_returned).
    """
    booking = db.session.get(Booking, booking_id)
    if booking is None or booking.user_id != user_id:
        # The same sentence for "no such booking" and "someone else's", so it
        # doesn't reveal which booking numbers exist.
        raise BookingError('You have no booking with that number.', 'not_found')
    if booking.status != 'Booked':
        raise BookingError('Only active bookings can be cancelled.', 'not_active')
    seats = booking.slots_booked
    if not release(booking.id, booking.trek_id, seats):
        db.session.rollback()
        raise BookingError('Only active bookings can be cancelled.', 'not_active')
    db.session.commit()
    return booking, seats


def toggle_insurance(user_id, booking_id, today=None):
    """Add insurance to `user_id`'s active booking or take it off, recompute the total
    the same way as a booking does, and commit. Returns the booking.

    Refused once the trek has started: insurance bought or dropped mid-trek would
    defeat its purpose.
    """
    today = today or date.today()
    booking = _changeable(user_id, booking_id)
    trek = booking.trek
    if trek.start_date <= today:
        raise BookingError("This trek has already started, so the booking can't be changed.", 'started')
    was_insured = bool(booking.has_insurance)
    _, _, total = quote(trek.price, booking.slots_booked, not was_insured)
    # Only if nothing changed since it was read: a cancel, or a second toggle from a
    # double click, can't be undone or doubled by this one.
    changed = db.session.execute(
        update(_bookings)
        .where(_bookings.c.id == booking.id,
               _bookings.c.user_id == user_id,
               _bookings.c.status == 'Booked',
               func.coalesce(_bookings.c.has_insurance, False) == was_insured)
        .values(has_insurance=not was_insured, total_price=total)
    ).rowcount
    if changed != 1:
        db.session.rollback()
        raise BookingError('This booking just changed. Please try again.', 'changed')
    db.session.commit()
    return booking


def change_date(user_id, booking_id, new_trek_id, today=None):
    """Move `user_id`'s active booking to another departure of the same trek and commit.

    The seats move with it: they're taken on the new date with the same conditional
    UPDATE as a booking, then given back on the old one, and the total is recomputed
    at the new date's price. Neither date may have started. Returns the booking.
    """
    today = today or date.today()
    booking = _changeable(user_id, booking_id)
    new_trek = db.session.get(Trek, new_trek_id) if new_trek_id is not None else None
    if new_trek is None:
        raise BookingError(f"There's no trek with id {new_trek_id}.", 'no_trek')
    old_trek = booking.trek
    seats = booking.slots_booked
    check_move(booking, old_trek, new_trek, today)
    _, _, total = quote(new_trek.price, seats, booking.has_insurance)

    taken = db.session.execute(
        update(_treks)
        .where(_treks.c.id == new_trek.id,
               _treks.c.status == 'Open',
               _treks.c.start_date > today,
               _treks.c.available_slots >= seats)
        .values(available_slots=_treks.c.available_slots - seats)
    ).rowcount
    if taken != 1:
        db.session.rollback()
        check_move(booking, old_trek, new_trek, today)  # names what changed meanwhile
        raise BookingError('Those seats were just taken. Please try again.', 'sold_out')

    # As in book(), this request now holds SQLite's write lock until the commit.
    if _has_active_booking(user_id, new_trek.id):
        db.session.rollback()
        raise BookingError('You already have a booking on that date.', 'already_booked')
    moved = db.session.execute(
        update(_bookings)
        .where(_bookings.c.id == booking.id,
               _bookings.c.user_id == user_id,
               _bookings.c.status == 'Booked',
               _bookings.c.trek_id == old_trek.id)
        .values(trek_id=new_trek.id, total_price=total)
    ).rowcount
    if moved != 1:
        db.session.rollback()
        raise BookingError('Cannot modify this booking.', 'not_active')
    db.session.execute(
        update(_treks)
        .where(_treks.c.id == old_trek.id)
        .values(available_slots=_treks.c.available_slots + seats)
    )
    db.session.commit()
    return booking


def check_move(booking, old_trek, new_trek, today):
    """Raise BookingError if `booking` can't move from `old_trek` to `new_trek`. Read-only."""
    if new_trek.name != old_trek.name:
        raise BookingError('Can only switch to another batch of the same trek.', 'other_trek')
    if new_trek.id == old_trek.id:
        raise BookingError('Your booking is already on that date.', 'same_date')
    if old_trek.start_date <= today:
        raise BookingError("This trek has already started, so the booking can't be moved.", 'started')
    if new_trek.status != 'Open':
        raise BookingError('The selected batch is not available.', 'not_open')
    if new_trek.start_date <= today:
        raise BookingError('The selected batch has already started.', 'started')
    if new_trek.available_slots < booking.slots_booked:
        raise BookingError(seats_left_reason(new_trek.available_slots), 'sold_out')
    if _has_active_booking(booking.user_id, new_trek.id):
        raise BookingError('You already have a booking on that date.', 'already_booked')


def _changeable(user_id, booking_id):
    """`user_id`'s Booked booking `booking_id`, or BookingError with the website's old wording."""
    booking = db.session.get(Booking, booking_id)
    if booking is None or booking.user_id != user_id:
        raise BookingError('Cannot modify this booking.', 'not_found')
    if booking.status != 'Booked':
        raise BookingError('Cannot modify this booking.', 'not_active')
    return booking


def release(booking_id, trek_id, seats):
    """Mark a Booked booking Cancelled and give its seats back to the trek, once.

    Returns False, and changes nothing, if the booking was no longer Booked, so two
    requests can't both give back the same seats. Doesn't commit.
    """
    flipped = db.session.execute(
        update(_bookings)
        .where(_bookings.c.id == booking_id, _bookings.c.status == 'Booked')
        .values(status='Cancelled')
    ).rowcount
    if flipped != 1:
        return False
    db.session.execute(
        update(_treks)
        .where(_treks.c.id == trek_id)
        .values(available_slots=_treks.c.available_slots + seats)
    )
    return True


def _has_active_booking(user_id, trek_id):
    return db.session.query(Booking.id).filter(
        Booking.user_id == user_id, Booking.trek_id == trek_id, Booking.status == 'Booked'
    ).first() is not None


def _active_count(user_id):
    return db.session.query(func.count(Booking.id)).filter(
        Booking.user_id == user_id, Booking.status == 'Booked'
    ).scalar()
