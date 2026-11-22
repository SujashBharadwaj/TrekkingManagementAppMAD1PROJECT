"""Tests for the website side of the MCP work: the seed's extra departures, the home
page's one card per trek, /healthz, and the trekker pages that book, cancel, move a
booking to another date or toggle its insurance, which all use services/bookings.py.

From the repo root:  venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""
import html
import re
import unittest
from datetime import date, timedelta
from unittest import mock

import support  # first: it points the app at a throwaway database
from support import flask_app

from models import db, Booking, Trek, User
from services import bookings
from services.bookings import BookingError

SEEDED_NAMES = [
    'Hampta Pass Trek', 'Kedarkantha Trek', 'Kedarkantha Trek', 'Valley of Flowers', 'Roopkund Trek',
    'Chadar Trek', 'Triund Trek', 'Brahmatal Trek', 'Kuari Pass Trek', 'Sandakphu Trek', 'Goechala Trek',
    'Dzukou Valley Trek', 'Harishchandragad Trek', 'Kalsubai Peak Trek', 'Kumara Parvatha Trek',
    'Meesapulimala Trek',
]
CARD = re.compile(r'href="/trek/(\d+)" class="text-decoration-none text-dark">.*?'
                  r'<h5 class="card-title">(.*?)</h5>', re.S)
FLASH = re.compile(r'alert-(\w+) alert-dismissible fade show" role="alert">\s*(.*?)\s*<button', re.S)


def flashes(page):
    """The (category, message) pairs flashed on a rendered page."""
    return [(category, html.unescape(message)) for category, message in FLASH.findall(page)]


class WebsiteTestCase(unittest.TestCase):
    def setUp(self):
        support.fresh_db()
        self.client = flask_app.test_client()

    def login(self, username, password):
        response = self.client.post('/login', data={'username': username, 'password': password})
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True))

    def page(self, response):
        return response.get_data(as_text=True)


class HealthTests(WebsiteTestCase):
    def test_healthz(self):
        response = self.client.get('/healthz')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {'ok': True})
        self.assertNotIn('Set-Cookie', response.headers)
        self.assertNotIn('Cookie', response.headers.get('Vary', ''))


class SeedTests(WebsiteTestCase):
    def test_the_first_sixteen_treks_and_their_bookings_are_unchanged(self):
        with flask_app.app_context():
            treks = Trek.query.order_by(Trek.id).all()
            self.assertEqual([trek.name for trek in treks[:16]], SEEDED_NAMES)
            self.assertEqual([trek.id for trek in treks[:16]], list(range(1, 17)))
            self.assertEqual((treks[5].status, treks[6].status), ('Pending', 'Completed'))
            self.assertEqual(db.session.get(Trek, 1).available_slots, 18)
            self.assertEqual(Booking.query.count(), 7)
            self.assertEqual([b.trek_id for b in Booking.query.order_by(Booking.id)], [1, 2, 4, 7, 1, 2, 5])

    def test_extra_departures_copy_their_route(self):
        today = date.today()
        with flask_app.app_context():
            treks = Trek.query.order_by(Trek.id).all()
            first = {}
            for trek in treks[:16]:
                first.setdefault(trek.name, trek)
            extras = treks[16:]
            self.assertGreaterEqual(len(extras), 24)
            for trek in extras:
                route = first[trek.name]
                self.assertEqual(trek.status, 'Open')
                self.assertGreater(trek.start_date, today)
                self.assertEqual(trek.available_slots, trek.total_slots)
                self.assertEqual(trek.end_date, trek.start_date + timedelta(days=trek.duration))
                for field in ('location', 'region', 'difficulty', 'duration', 'total_slots', 'price',
                              'best_season', 'description', 'assigned_staff_id'):
                    self.assertEqual(getattr(trek, field), getattr(route, field), (trek.id, field))

    def test_every_month_of_the_next_year_has_two_open_departures(self):
        today = date.today()
        with flask_app.app_context():
            starts = [trek.start_date for trek in
                      Trek.query.filter(Trek.status == 'Open', Trek.start_date > today)]
        for ahead in range(1, 13):
            months = today.month - 1 + ahead
            year, month = today.year + months // 12, months % 12 + 1
            count = sum(1 for start in starts if (start.year, start.month) == (year, month))
            self.assertGreaterEqual(count, 2, f'{year}-{month:02d}')


class HomePageTests(WebsiteTestCase):
    def test_lists_each_trek_once_at_its_soonest_departure(self):
        cards = CARD.findall(self.page(self.client.get('/')))
        names = [name for _, name in cards]
        self.assertEqual(len(names), len(set(names)), names)
        today = date.today()
        with flask_app.app_context():
            self.assertEqual(set(names), {trek.name for trek in Trek.query.filter_by(status='Open')})
            for trek_id, name in cards:
                soonest = (Trek.query.filter(Trek.name == name, Trek.status == 'Open', Trek.start_date > today)
                           .order_by(Trek.start_date, Trek.id).first())
                self.assertEqual(int(trek_id), soonest.id, name)

    def test_filters_apply_before_picking_a_departure(self):
        html = self.page(self.client.get('/?region=West&difficulty=Easy'))
        self.assertEqual([name for _, name in CARD.findall(html)], ['Kalsubai Peak Trek'])
        later = (date.today() + timedelta(days=60)).isoformat()
        cards = CARD.findall(self.page(self.client.get(f'/?start_date={later}')))
        with flask_app.app_context():
            for trek_id, name in cards:
                self.assertGreaterEqual(db.session.get(Trek, int(trek_id)).start_date.isoformat(), later, name)

    def test_trek_page_lists_the_other_dates(self):
        html = self.page(self.client.get('/trek/2'))
        self.assertIn('Other Available Dates', html)
        with flask_app.app_context():
            others = Trek.query.filter(Trek.name == 'Kedarkantha Trek', Trek.id != 2,
                                       Trek.status == 'Open').count()
        self.assertGreaterEqual(others, 3)
        self.assertEqual(html.count('slots left'), others)


class BookingPageTests(WebsiteTestCase):
    def test_user1_can_still_book_on_the_website(self):
        self.login('user1', 'user123')
        response = self.client.post('/book/2', data={'slots': '2', 'insurance': 'on'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers['Location'].endswith('/user/dashboard'))
        with flask_app.app_context():
            user = User.query.filter_by(username='user1').one()
            booking = Booking.query.filter_by(user_id=user.id, trek_id=2).one()
            self.assertEqual((booking.slots_booked, booking.has_insurance, booking.total_price, booking.status),
                             (2, True, 12000.0, 'Booked'))
            self.assertEqual(db.session.get(Trek, 2).available_slots, 27)
        dashboard = self.page(self.client.get('/user/dashboard'))
        self.assertIn('booked for 2 slot(s). Total: ₹12000.00', dashboard)

    def test_the_website_refuses_what_it_always_refused_and_started_treks(self):
        self.login('user1', 'user123')

        def refusal(trek_id, slots):
            return self.page(self.client.post(f'/book/{trek_id}', data={'slots': str(slots)},
                                              follow_redirects=True))

        self.assertIn('You already have a booking on this trek.', refusal(1, 1))  # user1 has Hampta Pass
        self.assertIn('This trek is not open for bookings.', refusal(6, 1))  # Chadar is Pending
        self.assertIn('Book at least 1 seat.', refusal(3, 0))
        with flask_app.app_context():
            db.session.get(Trek, 3).available_slots = 1
            base = db.session.get(Trek, 3)
            started = Trek(name='Started Today', location=base.location, region=base.region,
                           difficulty=base.difficulty, duration=4, total_slots=10, available_slots=10,
                           start_date=date.today(), end_date=date.today() + timedelta(days=4),
                           price=base.price, status='Open')
            db.session.add(started)
            db.session.commit()
            started_id = started.id
        self.assertIn('Only 1 seat is left on that date.', refusal(3, 2))
        self.assertIn('This trek has already started', refusal(started_id, 1))
        with flask_app.app_context():
            self.assertEqual(Booking.query.count(), 7)
            self.assertEqual(db.session.get(Trek, started_id).available_slots, 10)

    def test_cancelling_on_the_website_gives_seats_back(self):
        self.login('user1', 'user123')
        page = self.page(self.client.post('/booking/cancel/1', follow_redirects=True))
        self.assertIn('cancelled. Refund will be processed.', page)
        with flask_app.app_context():
            self.assertEqual(db.session.get(Booking, 1).status, 'Cancelled')
            self.assertEqual(db.session.get(Trek, 1).available_slots, 20)
        again = self.page(self.client.post('/booking/cancel/1', follow_redirects=True))
        self.assertIn('Only active bookings can be cancelled.', again)
        someone_elses = self.page(self.client.post('/booking/cancel/2', follow_redirects=True))
        self.assertIn('You have no booking with that number.', someone_elses)
        with flask_app.app_context():
            self.assertEqual(db.session.get(Booking, 2).status, 'Booked')
            self.assertEqual(db.session.get(Trek, 1).available_slots, 20)


class ChangeBookingTests(WebsiteTestCase):
    """Moving a booking to another date and toggling its insurance, through the service."""

    def setUp(self):
        super().setUp()
        self.login('user1', 'user123')  # user1 holds booking 1: 2 seats on Hampta Pass (trek 1)
        self.client.get('/user/dashboard')  # shows, and so clears, the "Welcome back" flash
        with flask_app.app_context():
            self.user1 = User.query.filter_by(username='user1').one().id
            self.target = (Trek.query.filter(Trek.name == 'Hampta Pass Trek', Trek.id != 1,
                                             Trek.status == 'Open')
                           .order_by(Trek.start_date, Trek.id).first().id)

    def post(self, path, data=None):
        return flashes(self.page(self.client.post(path, data=data or {}, follow_redirects=True)))

    def move(self, new_trek_id, booking_id=1):
        return self.post(f'/booking/{booking_id}/change-date', {'new_trek_id': str(new_trek_id)})

    def booking(self, booking_id=1):
        with flask_app.app_context():
            booking = db.session.get(Booking, booking_id)
            return booking.trek_id, bool(booking.has_insurance), booking.total_price, booking.status

    def seats(self, *trek_ids):
        with flask_app.app_context():
            return [db.session.get(Trek, trek_id).available_slots for trek_id in trek_ids]

    def update_trek(self, trek_id, **fields):
        with flask_app.app_context():
            trek = db.session.get(Trek, trek_id)
            for name, value in fields.items():
                setattr(trek, name, value)
            db.session.commit()

    def test_toggle_insurance_adds_it_and_takes_it_off(self):
        self.assertEqual(self.post('/booking/1/toggle-insurance'),
                         [('success', 'Insurance added. New total: ₹18000.00')])
        self.assertEqual(self.booking(), (1, True, 18000.0, 'Booked'))
        self.assertEqual(self.post('/booking/1/toggle-insurance'),
                         [('success', 'Insurance removed. New total: ₹17000.00')])
        self.assertEqual(self.booking(), (1, False, 17000.0, 'Booked'))
        self.assertEqual(self.seats(1), [18])

    def test_toggle_insurance_refusals(self):
        self.assertEqual(self.post('/booking/2/toggle-insurance'),  # user2's booking
                         [('danger', 'Cannot modify this booking.')])
        self.assertEqual(self.booking(2), (2, True, 5500.0, 'Booked'))
        self.update_trek(1, start_date=date.today())
        self.assertEqual(self.post('/booking/1/toggle-insurance'),
                         [('danger', "This trek has already started, so the booking can't be changed.")])
        self.assertEqual(self.booking(), (1, False, 17000.0, 'Booked'))
        self.update_trek(1, start_date=date.today() + timedelta(days=10))
        self.post('/booking/cancel/1')
        self.assertEqual(self.post('/booking/1/toggle-insurance'), [('danger', 'Cannot modify this booking.')])
        self.assertEqual(self.client.post('/booking/9999/toggle-insurance').status_code, 404)

    def test_toggle_insurance_only_changes_what_it_read(self):
        # A toggle working from a stale read (a double click, say) changes nothing.
        with flask_app.app_context():
            db.session.get(Booking, 1).has_insurance = True
            db.session.commit()
            stale = mock.Mock(id=1, has_insurance=False, slots_booked=2, trek=db.session.get(Trek, 1))
            with mock.patch.object(bookings, '_changeable', return_value=stale):
                with self.assertRaises(BookingError) as caught:
                    bookings.toggle_insurance(self.user1, 1)
            self.assertEqual(caught.exception.code, 'changed')
        self.assertEqual(self.booking(), (1, True, 17000.0, 'Booked'))

    def test_change_date_moves_the_seats(self):
        with flask_app.app_context():
            start = db.session.get(Trek, self.target).start_date
        self.assertEqual(self.move(self.target), [('success', f'Booking moved to {start:%d-%m-%Y} batch.')])
        self.assertEqual(self.booking(), (self.target, False, 17000.0, 'Booked'))
        self.assertEqual(self.seats(1, self.target), [20, 18])
        self.move(1)  # and back again
        self.assertEqual(self.booking(), (1, False, 17000.0, 'Booked'))
        self.assertEqual(self.seats(1, self.target), [18, 20])

    def test_change_date_recomputes_the_total_at_the_new_price(self):
        self.post('/booking/1/toggle-insurance')
        self.update_trek(self.target, price=9000.0)
        self.move(self.target)
        self.assertEqual(self.booking(), (self.target, True, 19000.0, 'Booked'))  # 2 x 9000 + 2 x 500

    def test_change_date_refusals(self):
        self.assertEqual(self.move(2), [('danger', 'Can only switch to another batch of the same trek.')])
        self.assertEqual(self.move(1), [('danger', 'Your booking is already on that date.')])
        for fields, reason in (({'status': 'Pending'}, 'The selected batch is not available.'),
                               ({'start_date': date.today()}, 'The selected batch has already started.'),
                               ({'available_slots': 1}, 'Only 1 seat is left on that date.')):
            with flask_app.app_context():
                trek = db.session.get(Trek, self.target)
                saved = {name: getattr(trek, name) for name in fields}
            self.update_trek(self.target, **fields)
            self.assertEqual(self.move(self.target), [('danger', reason)], fields)
            self.update_trek(self.target, **saved)
        self.assertEqual(self.move(3, booking_id=2), [('danger', 'Cannot modify this booking.')])  # user2's
        self.assertEqual(self.client.post('/booking/1/change-date', data={'new_trek_id': '9999'}).status_code,
                         404)
        self.assertEqual(self.client.post('/booking/1/change-date').status_code, 404)
        self.assertEqual(self.booking(), (1, False, 17000.0, 'Booked'))
        self.assertEqual(self.seats(1, self.target), [18, 20])

    def test_change_date_onto_a_date_already_booked(self):
        self.post(f'/book/{self.target}', {'slots': '1'})
        self.assertEqual(self.move(self.target), [('danger', 'You already have a booking on that date.')])
        self.assertEqual(self.booking(), (1, False, 17000.0, 'Booked'))
        self.assertEqual(self.seats(1, self.target), [18, 19])

    def test_change_date_from_a_trek_that_has_started(self):
        self.update_trek(1, start_date=date.today())
        self.assertEqual(self.move(self.target),
                         [('danger', "This trek has already started, so the booking can't be moved.")])
        self.assertEqual(self.booking(), (1, False, 17000.0, 'Booked'))
        self.assertEqual(self.seats(1, self.target), [18, 20])

    def test_change_date_takes_seats_atomically(self):
        # Even when the friendly checks pass on stale numbers, the conditional UPDATE refuses.
        self.update_trek(self.target, available_slots=1)
        with flask_app.app_context():
            with mock.patch.object(bookings, 'check_move'):
                with self.assertRaises(BookingError) as caught:
                    bookings.change_date(self.user1, 1, self.target)
            self.assertEqual(caught.exception.code, 'sold_out')
        self.assertEqual(self.booking(), (1, False, 17000.0, 'Booked'))
        self.assertEqual(self.seats(1, self.target), [18, 1])


if __name__ == '__main__':
    unittest.main()
