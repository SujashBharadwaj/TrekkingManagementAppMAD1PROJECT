"""The treks as the public sees them: one search and one set of fields, shared.

GET /api/treks (routes/api_routes.py) and the MCP list_treks tool
(mcp_server/tools.py) both call search(), so a person reading the JSON API and an
AI agent using the tool get the same departures, in the same order, with the same
fields. summary() is that whitelist, and nothing private (contacts, emails,
bookings, medical notes) is in it. detail() and itinerary() add what the public
trek page already shows, for the API's single-trek endpoints.

The filters that arrive as text (month, region, difficulty) are checked here, and
a bad one raises SearchError with one plain sentence that the API and the tool
both pass on as it is.
"""
import calendar
import math
import re
import unicodedata
from datetime import date

from models import db, Itinerary, Trek

LIST_LIMIT = 10
NAME_LIMIT = 80
MAX_ID = 2 ** 31 - 1  # bounds every id, so a huge number is refused instead of overflowing SQLite
REGIONS = ['North', 'East', 'West', 'South']
DIFFICULTIES = ['Easy', 'Moderate', 'Hard']
MONTH_NAMES = ('', 'January', 'February', 'March', 'April', 'May', 'June', 'July',
               'August', 'September', 'October', 'November', 'December')
HIDDEN_STATUSES = ('Pending',)  # waiting for an admin's approval, so not public yet

_MONTH = re.compile(r'[0-9]{4}-(0[1-9]|1[0-2])')
MONTH_PATTERN = f'^{_MONTH.pattern}$'  # the same rule as a JSON Schema pattern, for the MCP tool
MONTH_HINT = '"month" must be a year and month written YYYY-MM, with a two-digit month.'


class SearchError(ValueError):
    """A filter can't be used. str(error) is one plain sentence."""


def search(month=None, region=None, difficulty=None, max_price_inr=None, min_seats=None, today=None):
    """Open departures that haven't started, soonest first, as {'treks': [...], 'total': n}.

    `treks` holds at most LIST_LIMIT summaries, and `total` says how many match.
    max_price_inr and min_seats are whole numbers the caller has already checked
    (the MCP tool's schema does; the API doesn't offer them).
    """
    today = today or date.today()
    query = Trek.query.filter(Trek.status == 'Open', Trek.start_date > today)
    if month is not None:
        first, last = month_bounds(month, today)
        query = query.filter(Trek.start_date >= first, Trek.start_date <= last)
    if region is not None:
        query = query.filter(Trek.region == _one_of('region', region, REGIONS))
    if difficulty is not None:
        query = query.filter(Trek.difficulty == _one_of('difficulty', difficulty, DIFFICULTIES))
    if max_price_inr is not None:
        query = query.filter(Trek.price <= max_price_inr)
    if min_seats is not None:
        query = query.filter(Trek.available_slots >= min_seats)
    total = query.count()
    rows = query.order_by(Trek.start_date, Trek.id).limit(LIST_LIMIT).all()
    return {'treks': [summary(trek) for trek in rows], 'total': total}


def month_bounds(month, today):
    """The first and last day of `month` (YYYY-MM), or SearchError if it's malformed or over."""
    if not isinstance(month, str) or not _MONTH.fullmatch(month):
        raise SearchError(MONTH_HINT)
    year, number = int(month[:4]), int(month[5:7])
    if (year, number) < (today.year, today.month):
        # Someone asking for "a June trek" may pick a June that's over (a model
        # often does): say which one they probably meant, so they can correct it.
        next_year = today.year if number >= today.month else today.year + 1
        raise SearchError(f'{MONTH_NAMES[number]} {year} has already passed. Try {next_year}-{number:02d}.')
    return date(year, number, 1), date(year, number, calendar.monthrange(year, number)[1])


def summary(trek):
    """One departure in a list: the fields both the API and the MCP tool may show."""
    return {
        'id': trek.id,
        'name': clean_name(trek.name),
        'region': trek.region,
        'difficulty': trek.difficulty,
        'start_date': trek.start_date.isoformat(),
        'end_date': trek.end_date.isoformat(),
        'days': trek.duration,
        'price_inr': rupees(trek.price),
        'seats_left': max(0, trek.available_slots),
    }


def public_trek(trek_id):
    """The departure with this id if the public website shows it, else None (no such
    id, or still Pending)."""
    if not isinstance(trek_id, int) or not 1 <= trek_id <= MAX_ID:
        return None
    trek = db.session.get(Trek, trek_id)
    if trek is None or trek.status in HIDDEN_STATUSES:
        return None
    return trek


def detail(trek):
    """One departure as its public trek page shows it: the summary's fields and a few more."""
    base = summary(trek)
    return {
        'id': base['id'],
        'name': base['name'],
        'location': plain_text(trek.location),
        'region': base['region'],
        'difficulty': base['difficulty'],
        'start_date': base['start_date'],
        'end_date': base['end_date'],
        'days': base['days'],
        'price_inr': base['price_inr'],
        'seats_left': base['seats_left'],
        'total_seats': trek.total_slots,
        'status': trek.status,
        'best_season': plain_text(trek.best_season) or None,
        'route_kms': trek.route_kms if _finite(trek.route_kms) else None,
        'description': plain_text(trek.description) or None,
    }


def itinerary(trek):
    """The approved days of `trek`'s plan, in order, as the trek page lists them."""
    items = (Itinerary.query.filter_by(trek_id=trek.id, is_approved=True)
             .order_by(Itinerary.day_number, Itinerary.id).all())
    return {
        'trek_id': trek.id,
        'days': [{'day': item.day_number,
                  'title': plain_text(item.title),
                  'details': plain_text(item.description) or None} for item in items],
    }


def clean_name(name):
    """A trek name as one line of plain text, cut at 80 characters.

    Names are the only text in the MCP tool's results that other people can write
    (the admin login is published), so control and format characters, such as
    right-to-left overrides, are dropped before an agent reads them.
    """
    return plain_text(name, NAME_LIMIT)


def plain_text(value, limit=None):
    """`value` as one line of plain text: control and format characters dropped and
    each run of white space made one space, as a web page shows it. Cut at `limit`
    characters when one is given. None becomes ''."""
    kept = ''.join(' ' if ch.isspace() else ch for ch in (value or '')
                   if ch.isspace() or not unicodedata.category(ch).startswith('C'))
    text = ' '.join(kept.split())
    return text if limit is None else text[:limit].rstrip()


def rupees(value):
    return int(round(value or 0))


def join_words(words, last):
    """'a, b and c' (or 'a, b or c'), the way the refusals list choices."""
    words = list(words)
    if len(words) <= 1:
        return ''.join(words)
    return f'{", ".join(words[:-1])} {last} {words[-1]}'


def _one_of(name, value, allowed):
    if value not in allowed:
        raise SearchError(f'"{name}" must be {join_words(allowed, "or")}.')
    return value


def _finite(value):
    return isinstance(value, (int, float)) and math.isfinite(value)
