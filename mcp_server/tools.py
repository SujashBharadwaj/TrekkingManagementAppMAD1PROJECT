"""The five MCP tools: everything an AI agent can do on Mountains & Maggi.

The list is fixed here in code, so nothing a client sends can add a tool or reach
an admin or staff function. Every tool acts as the visit's own throwaway trekker
(visits.py), and results carry only the fields in the output schemas below: no
descriptions, phone numbers, emails, medical notes or ids from other tables.
"""
import json

from models import db, Booking, Trek
from services import bookings, catalogue
from services.bookings import BookingError
from services.catalogue import (DIFFICULTIES, LIST_LIMIT, MAX_ID, MONTH_HINT, MONTH_NAMES,  # noqa: F401
                                MONTH_PATTERN, NAME_LIMIT, REGIONS, SearchError, clean_name)
from . import schema
from .visits import DemoBusy, record_call

MAX_SEATS = bookings.WALKER_MAX_SEATS  # the same limits as a walker booking on the website
MAX_ACTIVE_BOOKINGS = bookings.WALKER_MAX_ACTIVE
MAX_PRICE = 10_000_000  # rupees

NEEDS_VISIT = 'This tool needs the MM-Visit-Id header (a UUID v4) to know whose bookings to use.'
NOT_YOURS = 'You have no booking with that number.'


class ToolError(Exception):
    """A tool call failed in a way the agent can read out: str(error) is one plain sentence."""


class Tool:
    def __init__(self, name, title, description, input_schema, output_schema, annotations,
                 run, hints=None):
        self.name = name
        self.title = title
        self.description = description
        self.input_schema = input_schema
        self.output_schema = output_schema
        self.annotations = dict(annotations, title=title)
        self.run = run
        self.hints = hints or {}

    def definition(self):
        """The Tool object that tools/list returns."""
        return {
            'name': self.name,
            'title': self.title,
            'description': self.description,
            'inputSchema': self.input_schema,
            'outputSchema': self.output_schema,
            'annotations': self.annotations,
        }


# --- Running a tool ---------------------------------------------------------

def call(tool, arguments, visit):
    """Run `tool` for `visit` and return the CallToolResult fields.

    A refusal is a result with isError and one plain sentence, so the agent can read
    it out or try again; protocol problems (an unknown tool) are the caller's job.
    """
    if visit.malformed:
        return _failure('The MM-Visit-Id header must be a UUID v4.')
    refusal = record_call(visit.id, tool.name)
    if refusal:
        return _failure(refusal)
    try:
        args = schema.validate(tool.input_schema, {} if arguments is None else arguments, tool.hints)
        data = tool.run(args, visit)
    except (schema.SchemaError, ToolError) as problem:
        db.session.rollback()
        return _failure(str(problem))
    return {
        'content': [{'type': 'text', 'text': json.dumps(data, ensure_ascii=False)}],
        'structuredContent': data,
        'isError': False,
    }


def _failure(sentence):
    return {'content': [{'type': 'text', 'text': sentence}], 'isError': True}


# --- The tools --------------------------------------------------------------

def _list_treks(args, visit):
    # The same search as GET /api/treks (services/catalogue.py), so the two can't drift.
    try:
        return catalogue.search(month=args.get('month'), region=args.get('region'),
                                difficulty=args.get('difficulty'),
                                max_price_inr=args.get('max_price_inr'), min_seats=args.get('min_seats'))
    except SearchError as problem:
        raise ToolError(str(problem))


def _check_availability(args, visit):
    trek = _trek(args['trek_id'])
    walker = visit.walker()
    reason = None
    try:
        bookings.check(trek, walker.user_id if walker else None, args['seats'],
                       max_active=MAX_ACTIVE_BOOKINGS, max_seats=MAX_SEATS)
    except BookingError as refusal:
        reason = refusal.reason
    base, cover, total = bookings.quote(trek.price, args['seats'], args['insurance'])
    return {
        'trek_id': trek.id,
        'name': clean_name(trek.name),
        'start_date': trek.start_date.isoformat(),
        'seats_left': max(0, trek.available_slots),
        'can_book': reason is None,
        'reason': reason,
        'quote': {'base_inr': _rupees(base), 'insurance_inr': _rupees(cover), 'total_inr': _rupees(total)},
    }


def _book_trek(args, visit):
    if visit.id is None:
        raise ToolError(NEEDS_VISIT)
    _trek(args['trek_id'])  # before making a walker for a trek that doesn't exist
    try:
        walker = visit.walker_or_create()
    except DemoBusy as busy:
        raise ToolError(str(busy))
    if walker is None:
        raise ToolError("This visit's demo trekker couldn't be set up. Please try again.")
    try:
        booking = bookings.book(walker.user_id, args['trek_id'], args['seats'],
                                insurance=args['insurance'], max_active=MAX_ACTIVE_BOOKINGS,
                                max_seats=MAX_SEATS)
    except BookingError as refusal:
        if refusal.code == 'no_user':  # housekeeping removed the walker a moment ago
            raise ToolError("This visit's bookings have expired. Please start a new run.")
        raise ToolError(refusal.reason)
    trek = booking.trek
    return {
        'booking_id': booking.id,
        'trek_id': trek.id,
        'name': clean_name(trek.name),
        'start_date': trek.start_date.isoformat(),
        'seats': booking.slots_booked,
        'insurance': bool(booking.has_insurance),
        'total_inr': _rupees(booking.total_price),
        'status': 'Booked',
        'seats_left_after': max(0, trek.available_slots),
    }


def _cancel_booking(args, visit):
    if visit.id is None:
        raise ToolError(NEEDS_VISIT)
    walker = visit.walker()
    if walker is None:
        raise ToolError(NOT_YOURS)
    try:
        booking, returned = bookings.cancel(walker.user_id, args['booking_id'])
    except BookingError as refusal:
        booking = db.session.get(Booking, args['booking_id'])
        if refusal.code != 'not_active' or booking is None or booking.status != 'Cancelled':
            raise ToolError(refusal.reason)
        returned = 0  # already cancelled: the same answer again, and nothing changes
    trek = booking.trek
    return {
        'booking_id': booking.id,
        'trek_id': trek.id,
        'name': clean_name(trek.name),
        'status': 'Cancelled',
        'seats_returned': returned,
        'seats_left_after': max(0, trek.available_slots),
    }


def _my_bookings(args, visit):
    walker = visit.walker()
    if walker is None:
        return {'bookings': []}
    rows = Booking.query.filter_by(user_id=walker.user_id).order_by(Booking.id).all()
    return {'bookings': [{
        'booking_id': b.id,
        'trek_id': b.trek_id,
        'name': clean_name(b.trek.name),
        'start_date': b.trek.start_date.isoformat(),
        'seats': b.slots_booked,
        'total_inr': _rupees(b.total_price),
        'status': b.status,
    } for b in rows if b.trek is not None]}


# --- Helpers ----------------------------------------------------------------
# clean_name() and the list's fields live in services/catalogue.py, shared with
# GET /api/treks.

def _trek(trek_id):
    trek = db.session.get(Trek, trek_id)
    if trek is None:
        raise ToolError(f"There's no trek with id {trek_id}.")
    return trek


_rupees = catalogue.rupees


# --- Schemas ----------------------------------------------------------------

def _object(properties, required=()):
    shape = {'type': 'object', 'properties': properties}
    if required:
        shape['required'] = list(required)
    shape['additionalProperties'] = False
    return shape


_TREK_ID = {'type': 'integer', 'minimum': 1, 'maximum': MAX_ID,
            'description': 'The id of one departure, as list_treks returns it.'}
_SEATS = {'type': 'integer', 'minimum': 1, 'maximum': MAX_SEATS,
          'description': f'How many seats, from 1 to {MAX_SEATS}.'}
_INSURANCE = {'type': 'boolean', 'default': False,
              'description': 'Add trek insurance, 500 rupees per seat. Defaults to false.'}
_NAME = {'type': 'string', 'maxLength': NAME_LIMIT, 'description': 'Trek name, as plain text.'}
_DATE = {'type': 'string', 'format': 'date', 'description': 'YYYY-MM-DD'}
_COUNT = {'type': 'integer', 'minimum': 0}
_RUPEES = {'type': 'integer', 'minimum': 0, 'description': 'Whole rupees.'}

_TREK_SUMMARY = _object({
    'id': {'type': 'integer', 'description': 'Departure id, for check_availability and book_trek.'},
    'name': _NAME,
    'region': {'type': ['string', 'null']},
    'difficulty': {'type': 'string'},
    'start_date': _DATE,
    'end_date': _DATE,
    'days': {'type': 'integer', 'description': 'Length of the trek in days.'},
    'price_inr': dict(_RUPEES, description='Price per seat, in whole rupees.'),
    'seats_left': _COUNT,
}, required=['id', 'name', 'region', 'difficulty', 'start_date', 'end_date', 'days', 'price_inr',
             'seats_left'])

_BOOKING_ROW = _object({
    'booking_id': {'type': 'integer'},
    'trek_id': {'type': 'integer'},
    'name': _NAME,
    'start_date': _DATE,
    'seats': {'type': 'integer', 'minimum': 1},
    'total_inr': _RUPEES,
    'status': {'type': 'string', 'enum': ['Booked', 'Cancelled', 'Completed']},
}, required=['booking_id', 'trek_id', 'name', 'start_date', 'seats', 'total_inr', 'status'])

TOOLS = [
    Tool(
        name='list_treks',
        title='List treks',
        description=(
            'Find upcoming departures that are open for booking, soonest first, at most 10 '
            '(total says how many match). A trek such as Hampta Pass runs on several dates, and '
            'each date is a departure with its own id. Filter by month (YYYY-MM), region, '
            'difficulty, highest price per seat in rupees, or the number of free seats needed.'),
        input_schema=_object({
            'month': {'type': 'string', 'pattern': MONTH_PATTERN,
                      'description': 'Only departures that start in this month, written YYYY-MM.'},
            'region': {'type': 'string', 'enum': REGIONS, 'description': 'Part of India.'},
            'difficulty': {'type': 'string', 'enum': DIFFICULTIES},
            'max_price_inr': dict(_RUPEES, maximum=MAX_PRICE,
                                  description='Highest price per seat, in whole rupees.'),
            'min_seats': {'type': 'integer', 'minimum': 1, 'maximum': MAX_SEATS,
                          'description': 'Only departures with at least this many free seats.'},
        }),
        output_schema=_object({
            'treks': {'type': 'array', 'items': _TREK_SUMMARY, 'maxItems': LIST_LIMIT},
            'total': dict(_COUNT, description='How many departures match. treks holds the first 10.'),
        }, required=['treks', 'total']),
        annotations={'readOnlyHint': True, 'openWorldHint': False},
        run=_list_treks,
        hints={'month': MONTH_HINT},
    ),
    Tool(
        name='check_availability',
        title='Check availability',
        description=(
            'Check one departure before booking it: how many seats are left, whether this '
            'visit can book it (and if not, why), and a price quote in whole rupees. '
            'Trek insurance costs 500 rupees per seat.'),
        input_schema=_object({
            'trek_id': _TREK_ID,
            'seats': dict(_SEATS, default=1, description=f'How many seats, from 1 to {MAX_SEATS}. Defaults to 1.'),
            'insurance': _INSURANCE,
        }, required=['trek_id']),
        output_schema=_object({
            'trek_id': {'type': 'integer'},
            'name': _NAME,
            'start_date': _DATE,
            'seats_left': _COUNT,
            'can_book': {'type': 'boolean'},
            'reason': {'type': ['string', 'null'],
                       'description': 'Why this visit can\'t book it, or null when can_book is true.'},
            'quote': _object({'base_inr': _RUPEES, 'insurance_inr': _RUPEES, 'total_inr': _RUPEES},
                             required=['base_inr', 'insurance_inr', 'total_inr']),
        }, required=['trek_id', 'name', 'start_date', 'seats_left', 'can_book', 'reason', 'quote']),
        annotations={'readOnlyHint': True, 'openWorldHint': False},
        run=_check_availability,
    ),
    Tool(
        name='book_trek',
        title='Book a trek',
        description=(
            'Book seats on one departure for this visit, with the same rules as the website: '
            'the trek must be open, not yet started, have enough seats left, and not already be '
            'booked by this visit. Up to 4 seats per booking and 3 active bookings per visit. '
            'Returns the booking, its total in whole rupees and the seats left afterwards.'),
        input_schema=_object({
            'trek_id': _TREK_ID,
            'seats': _SEATS,
            'insurance': _INSURANCE,
        }, required=['trek_id', 'seats']),
        output_schema=_object({
            'booking_id': {'type': 'integer'},
            'trek_id': {'type': 'integer'},
            'name': _NAME,
            'start_date': _DATE,
            'seats': {'type': 'integer', 'minimum': 1, 'maximum': MAX_SEATS},
            'insurance': {'type': 'boolean'},
            'total_inr': _RUPEES,
            'status': {'type': 'string', 'enum': ['Booked']},
            'seats_left_after': _COUNT,
        }, required=['booking_id', 'trek_id', 'name', 'start_date', 'seats', 'insurance', 'total_inr',
                     'status', 'seats_left_after']),
        annotations={'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': False,
                     'openWorldHint': False},
        run=_book_trek,
    ),
    Tool(
        name='cancel_booking',
        title='Cancel a booking',
        description=(
            "Cancel one of this visit's bookings by its booking_id and give its seats back. "
            'Cancelling a booking that is already cancelled changes nothing.'),
        input_schema=_object({
            'booking_id': {'type': 'integer', 'minimum': 1, 'maximum': MAX_ID,
                           'description': 'The booking to cancel, from book_trek or my_bookings.'},
        }, required=['booking_id']),
        output_schema=_object({
            'booking_id': {'type': 'integer'},
            'trek_id': {'type': 'integer'},
            'name': _NAME,
            'status': {'type': 'string', 'enum': ['Cancelled']},
            'seats_returned': _COUNT,
            'seats_left_after': _COUNT,
        }, required=['booking_id', 'trek_id', 'name', 'status', 'seats_returned', 'seats_left_after']),
        annotations={'readOnlyHint': False, 'destructiveHint': True, 'idempotentHint': True,
                     'openWorldHint': False},
        run=_cancel_booking,
    ),
    Tool(
        name='my_bookings',
        title='My bookings',
        description="List this visit's bookings, active and cancelled, oldest first.",
        input_schema=_object({}),
        output_schema=_object({
            'bookings': {'type': 'array', 'items': _BOOKING_ROW},
        }, required=['bookings']),
        annotations={'readOnlyHint': True, 'openWorldHint': False},
        run=_my_bookings,
    ),
]

TOOLS_BY_NAME = {tool.name: tool for tool in TOOLS}
