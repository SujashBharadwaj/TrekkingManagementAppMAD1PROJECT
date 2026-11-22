"""Tests for POST /demo/walker and for walkers using the website like a person:
the door, the per-visit password, the cap on new walkers, housekeeping, and the
demo's limits on the website's booking form (real accounts keep today's rules).

From the repo root:  venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""
import json
import re
import threading
import unittest
from datetime import timedelta

import support  # first: it points the app at a throwaway database
from support import TOKEN, McpClient, flask_app, new_visit
from test_website import flashes

from mcp_server import visits
from models import db, Booking, McpWalker, StaffApplication, Trek, User, utc_now
from services import bookings

BUSY = 'The demo is busy right now. Please try again in a minute.'
BAD_BODY = 'Bad request: send a JSON object with one field, "visit_id", a UUID v4.'


class DemoWalkerTestCase(unittest.TestCase):
    def setUp(self):
        support.fresh_db()
        flask_app.config['MCP_TOKEN'] = TOKEN
        flask_app.config['MCP_ALLOWED_ORIGINS'] = []
        self.client = flask_app.test_client()

    def tearDown(self):
        flask_app.config['MCP_TOKEN'] = ''

    # --- helpers ---

    def post(self, body, headers=None, token=TOKEN, client=None):
        sent = {'Content-Type': 'application/json'}
        if token:
            sent['Authorization'] = f'Bearer {token}'
        sent.update(headers or {})
        data = body if isinstance(body, (bytes, str)) else json.dumps(body)
        return (client or self.client).post('/demo/walker', data=data, headers=sent)

    def details(self, visit):
        """The {username, password} for `visit`, checking the reply on the way."""
        response = self.post({'visit_id': visit})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(response.mimetype, 'application/json')
        self.assertNotIn('Set-Cookie', response.headers)
        body = response.get_json()
        self.assertEqual(set(body), {'username', 'password'})
        return body

    def refusal(self, response, status):
        self.assertEqual(response.status_code, status, response.get_data(as_text=True))
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        body = response.get_json()
        self.assertEqual(set(body), {'error'})
        return body['error']

    def sign_in(self, details, client=None):
        """Sign in through the /login form, as the browser does, and return the response."""
        return (client or self.client).post('/login', data={
            'next': '', 'username': details['username'], 'password': details['password']})

    def browser(self, visit):
        """A fresh test client signed in as `visit`'s walker, with its details."""
        details = self.details(visit)
        client = flask_app.test_client()
        response = self.sign_in(details, client)
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True))
        return client, details

    def book(self, client, trek_id, slots, insurance=False):
        """Submit the trek page's booking modal, as its form does."""
        form = {'slots': str(slots), 'medical_info': '', 'dietary_needs': ''}
        if insurance:
            form['insurance'] = 'on'
        return client.post(f'/book/{trek_id}', data=form)

    def seats(self, trek_id):
        with flask_app.app_context():
            return db.session.get(Trek, trek_id).available_slots

    def user_id(self, username):
        with flask_app.app_context():
            user = User.query.filter_by(username=username).first()
            return user.id if user else None

    def page(self, response):
        return response.get_data(as_text=True)


class DoorTests(DemoWalkerTestCase):
    """The same door as /mcp, with plain-sentence refusals."""

    def test_off_without_token(self):
        flask_app.config['MCP_TOKEN'] = ''
        for method in ('get', 'post', 'put', 'delete', 'options'):
            self.assertEqual(getattr(self.client, method)('/demo/walker').status_code, 404, method)
        self.assertEqual(self.post({'visit_id': new_visit()}).status_code, 404)
        with flask_app.app_context():
            self.assertEqual(McpWalker.query.count(), 0)

    def test_post_only(self):
        for method in ('get', 'delete', 'put', 'patch'):
            response = getattr(self.client, method)('/demo/walker', headers={'Authorization': f'Bearer {TOKEN}'})
            self.assertEqual(self.refusal(response, 405), 'Method not allowed: this endpoint takes POST only.')
            self.assertEqual(response.headers['Allow'], 'POST')

    def test_missing_or_wrong_token(self):
        response = self.post({'visit_id': new_visit()}, token=None)
        self.assertIn('Unauthorized', self.refusal(response, 401))
        self.assertEqual(response.headers['WWW-Authenticate'], 'Bearer')
        for header in ('Bearer wrong', f'Basic {TOKEN}', f'Bearer {TOKEN}x', 'Bearer', TOKEN, ''):
            response = self.post({'visit_id': new_visit()}, headers={'Authorization': header}, token=None)
            self.refusal(response, 401)
        self.assertEqual(self.post({'visit_id': new_visit()}, headers={'Authorization': f'bearer {TOKEN}'},
                                   token=None).status_code, 200)
        with flask_app.app_context():
            self.assertEqual(McpWalker.query.count(), 1)  # only the last call got in

    def test_origins(self):
        for origin in ('https://evil.example', 'null', 'http://localhost:3100'):
            response = self.post({'visit_id': new_visit()}, headers={'Origin': origin})
            self.assertEqual(self.refusal(response, 403), 'Forbidden: requests from this origin are not allowed.')
        flask_app.config['MCP_ALLOWED_ORIGINS'] = ['https://sujash-bharadwaj.vercel.app']
        allowed = self.post({'visit_id': new_visit()}, headers={'Origin': 'https://sujash-bharadwaj.vercel.app'})
        self.assertEqual(allowed.status_code, 200)
        lookalike = self.post({'visit_id': new_visit()},
                              headers={'Origin': 'https://sujash-bharadwaj.vercel.app.evil.example'})
        self.refusal(lookalike, 403)

    def test_body_over_1_kb(self):
        visit = new_visit()
        body = json.dumps({'visit_id': visit})
        padded = body + ' ' * (1024 - len(body))  # 1 KB exactly, still valid JSON
        self.assertEqual(len(padded), 1024)
        self.assertEqual(self.post(padded).status_code, 200)
        self.assertIn('1024 bytes or less', self.refusal(self.post(padded + ' '), 413))

    def test_ignores_the_login_session_and_sets_no_cookie(self):
        self.client.post('/login', data={'username': 'admin', 'password': 'admin123'})
        details = self.details(new_visit())
        self.assertTrue(details['username'].startswith('walker-'))


class WalkerDetailsTests(DemoWalkerTestCase):
    def test_a_new_walker_then_the_same_walker_with_a_new_password(self):
        visit = new_visit()
        first = self.details(visit)
        self.assertEqual(first['username'], 'walker-' + visit.replace('-', '')[:8])
        self.assertRegex(first['password'], r'^[A-Za-z0-9_-]{22}$')
        with flask_app.app_context():
            walker = McpWalker.query.filter_by(visit_id=visit).one()
            user = db.session.get(User, walker.user_id)
            self.assertEqual((user.username, user.email, user.role, user.status),
                             (first['username'], first['username'] + '@demo.invalid', 'trekker', 'active'))
            self.assertNotIn(first['password'], user.password_hash)
            self.assertTrue(user.password_hash.startswith('pbkdf2:sha256:'))

        second = self.details(visit)
        self.assertEqual(second['username'], first['username'])
        self.assertNotEqual(second['password'], first['password'])
        with flask_app.app_context():
            self.assertEqual(McpWalker.query.count(), 1)
            self.assertEqual(User.query.filter(User.username.like('walker-%')).count(), 1)

        # The old password stops working; the new one signs in.
        old = self.sign_in(first, flask_app.test_client())
        self.assertIn('Invalid username or password.', self.page(old))
        self.assertEqual(self.sign_in(second).status_code, 302)

    def test_other_visits_get_other_walkers(self):
        alice, bob = self.details(new_visit()), self.details(new_visit())
        self.assertNotEqual(alice['username'], bob['username'])
        self.assertIn('Invalid username or password.',
                      self.page(self.sign_in({'username': alice['username'], 'password': bob['password']})))

    def test_bad_visit_ids(self):
        bodies = [
            '', 'not json', '{"visit_id": ', '[]', '"3b8f2c1a-9d4e-4f6a-8b2c-1d3e5f7a9b0c"', 'null', '{}',
            {'visit': new_visit()},
            {'visit_id': new_visit(), 'extra': 1},
            {'visit_id': None}, {'visit_id': 42}, {'visit_id': [new_visit()]}, {'visit_id': ''},
            {'visit_id': 'not-a-uuid'},
            {'visit_id': '6f1c2b8e-1d2a-1c3b-9a8d-7e6f5a4b3c2d'},  # a version 1 UUID
            {'visit_id': new_visit().replace('-', '')},
            {'visit_id': new_visit() + 'a'},
            b'\xff\xfe',
        ]
        for body in bodies:
            self.assertEqual(self.refusal(self.post(body), 400), BAD_BODY, body)
        with flask_app.app_context():
            self.assertEqual(McpWalker.query.count(), 0)

    def test_an_upper_case_visit_id_is_the_same_visit(self):
        visit = new_visit()
        self.assertEqual(self.details(visit.upper())['username'], self.details(visit)['username'])
        with flask_app.app_context():
            self.assertEqual(McpWalker.query.filter_by(visit_id=visit).count(), 1)

    def test_the_mcp_agent_and_the_browser_share_a_visits_walker(self):
        visit = new_visit()
        mcp = McpClient(flask_app.test_client())
        reply = mcp.call('book_trek', {'trek_id': 3, 'seats': 1}, visit).get_json()['result']
        self.assertFalse(reply['isError'], reply)
        client, details = self.browser(visit)
        dashboard = self.page(client.get('/user/dashboard'))
        self.assertIn('Kedarkantha Trek', dashboard)
        with flask_app.app_context():
            self.assertEqual(McpWalker.query.filter_by(visit_id=visit).one().user_id,
                             self.user_id(details['username']))


class NewWalkerCapTests(DemoWalkerTestCase):
    def add_walkers(self, count, age):
        """`count` walkers (with their users) made `age` ago. Returns their visit ids."""
        made = []
        with flask_app.app_context():
            for _ in range(count):
                visit = new_visit()
                user = User(username=f'cap-{visit}', email=f'cap-{visit}@demo.invalid',
                            password_hash='unused', role='trekker', status='active')
                db.session.add(user)
                db.session.flush()
                db.session.add(McpWalker(visit_id=visit, user_id=user.id, created_at=utc_now() - age))
                made.append(visit)
            db.session.commit()
        return made

    def test_thirty_new_walkers_a_minute_in_all(self):
        self.assertEqual(visits.NEW_WALKERS_PER_MINUTE, 30)
        recent = self.add_walkers(30, timedelta(seconds=10))
        response = self.post({'visit_id': new_visit()})
        self.assertEqual(self.refusal(response, 429), BUSY)
        self.assertEqual(response.headers['Retry-After'], '60')
        # A visit that already has a walker still gets a new password: that adds no rows.
        self.assertEqual(self.post({'visit_id': recent[0]}).status_code, 200)
        # The cap counts walkers made over MCP too, and refuses there with the same sentence.
        mcp = McpClient(flask_app.test_client())
        reply = mcp.call('book_trek', {'trek_id': 3, 'seats': 1}, new_visit()).get_json()['result']
        self.assertTrue(reply['isError'])
        self.assertEqual(reply['content'][0]['text'], BUSY)
        with flask_app.app_context():
            self.assertEqual(McpWalker.query.count(), 30)
            self.assertEqual(User.query.count(), 9 + 30)  # the nine seeded accounts and the thirty
        self.assertEqual(self.seats(3), 30)

    def test_parallel_requests_never_pass_the_cap(self):
        self.add_walkers(29, timedelta(seconds=10))  # one place left
        statuses = []
        start = threading.Barrier(6)

        def ask():
            client = flask_app.test_client()
            start.wait()
            statuses.append(self.post({'visit_id': new_visit()}, client=client).status_code)

        threads = [threading.Thread(target=ask) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(statuses), [200] + [429] * 5, statuses)
        with flask_app.app_context():
            self.assertEqual(McpWalker.query.count(), 30)

    def test_walkers_over_a_minute_old_dont_count(self):
        self.add_walkers(30, timedelta(seconds=70))
        self.details(new_visit())
        self.add_walkers(29, timedelta(seconds=10))  # 29 recent plus the one just made: full
        self.refusal(self.post({'visit_id': new_visit()}), 429)


class HousekeepingTests(DemoWalkerTestCase):
    def test_an_hour_old_walker_goes_with_its_bookings_password_and_session(self):
        old_visit = new_visit()
        client, details = self.browser(old_visit)
        self.assertEqual(self.book(client, 3, 2).status_code, 302)
        self.assertEqual(self.seats(3), 28)
        # Things a signed-in walker could leave behind on the website go too.
        applied = client.post('/apply-staff', data={'aadhar': 'X1', 'region': 'North', 'level': 'Beginner'})
        self.assertEqual(applied.status_code, 302)
        old_user = self.user_id(details['username'])
        with flask_app.app_context():
            self.assertEqual(StaffApplication.query.filter_by(user_id=old_user).count(), 1)
            walker = McpWalker.query.filter_by(visit_id=old_visit).one()
            walker.created_at = utc_now() - timedelta(minutes=61)
            db.session.commit()

        newcomer = self.details(new_visit())  # any /demo/walker call tidies up first
        self.assertEqual(self.seats(3), 30)
        with flask_app.app_context():
            self.assertIsNone(McpWalker.query.filter_by(visit_id=old_visit).first())
            self.assertIsNone(User.query.filter_by(username=details['username']).first())
            self.assertEqual(Booking.query.filter_by(user_id=old_user).count(), 0)
            self.assertEqual(StaffApplication.query.filter_by(user_id=old_user).count(), 0)
            self.assertEqual(Booking.query.filter_by(status='Booked').count(), 4)  # the seeded ones
        self.assertIn('Invalid username or password.', self.page(self.sign_in(details, flask_app.test_client())))

        # SQLite hands the deleted walker's id to the next new account. The old
        # browser's session must not carry over to it.
        self.assertEqual(self.user_id(newcomer['username']), old_user)
        stale = client.get('/user/dashboard')
        self.assertEqual(stale.status_code, 302)
        self.assertIn('/login', stale.headers['Location'])
        self.assertEqual(client.get('/user/dashboard').status_code, 302)  # and it stays signed out

        # The same visit later gets a fresh walker, with no bookings.
        again = self.details(old_visit)
        self.assertEqual(again['username'], details['username'])
        fresh = flask_app.test_client()
        self.assertEqual(self.sign_in(again, fresh).status_code, 302)
        self.assertEqual(fresh.get('/user/dashboard').status_code, 200)
        with flask_app.app_context():
            self.assertEqual(Booking.query.filter_by(user_id=self.user_id(again['username'])).count(), 0)


class WebsiteAsWalkerTests(DemoWalkerTestCase):
    """A walker signs in on /login and uses the trekker pages like a person."""

    def test_sign_in_dashboard_trek_page_book_and_cancel(self):
        client, details = self.browser(new_visit())
        # /login sent the walker where trekkers land.
        response = self.sign_in(details, flask_app.test_client())
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers['Location'].endswith('/user/dashboard'))

        dashboard = client.get('/user/dashboard')
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(f'Hello, <strong>{details["username"]}</strong>', self.page(dashboard))

        trek_page = self.page(client.get('/trek/3'))
        self.assertIn('data-bs-target="#bookingModal"', trek_page)
        self.assertIn('action="/book/3" method="POST"', trek_page)
        for field in ('name="slots"', 'name="insurance"', 'name="medical_info"', 'name="dietary_needs"'):
            self.assertIn(field, trek_page)

        booked = self.book(client, 3, 2, insurance=True)
        self.assertEqual(booked.status_code, 302)
        self.assertTrue(booked.headers['Location'].endswith('/user/dashboard'))
        self.assertEqual(self.seats(3), 28)
        self.assertIn('Slots Available:</strong> 28 / 30', self.page(self.client.get('/trek/3')))
        with flask_app.app_context():
            booking = Booking.query.filter_by(user_id=self.user_id(details['username'])).one()
            self.assertEqual((booking.trek_id, booking.slots_booked, booking.has_insurance,
                              booking.total_price, booking.status), (3, 2, True, 12000.0, 'Booked'))
            booking_id = booking.id
        dashboard = self.page(client.get('/user/dashboard'))
        self.assertIn('booked for 2 slot(s). Total: ₹12000.00', dashboard)
        self.assertIn(f'action="/booking/cancel/{booking_id}"', dashboard)

        cancelled = self.page(client.post(f'/booking/cancel/{booking_id}', follow_redirects=True))
        self.assertIn('cancelled. Refund will be processed.', cancelled)
        self.assertEqual(self.seats(3), 30)

    def test_at_most_four_seats_a_booking(self):
        client, details = self.browser(new_visit())
        refused = client.post('/book/3', data={'slots': '5'}, follow_redirects=True)
        self.assertEqual(flashes(self.page(refused))[-1], ('danger', 'You can book at most 4 seats at a time.'))
        self.assertEqual(refused.request.path, '/trek/3')
        self.assertEqual(self.seats(3), 30)
        self.assertEqual(self.book(client, 3, 4).status_code, 302)
        self.assertEqual(self.seats(3), 26)

    def test_at_most_three_active_bookings(self):
        client, _ = self.browser(new_visit())
        for trek_id in (3, 8, 9):
            self.assertTrue(self.book(client, trek_id, 1).headers['Location'].endswith('/user/dashboard'))
        before = self.seats(10)
        refused = client.post('/book/10', data={'slots': '1'}, follow_redirects=True)
        self.assertEqual(flashes(self.page(refused))[-1], ('danger', bookings.too_many_reason(3)))
        self.assertEqual(self.seats(10), before)
        # Cancelling one makes room, as over MCP.
        dashboard = self.page(client.get('/user/dashboard'))
        first = re.search(r'action="/booking/cancel/(\d+)"', dashboard).group(1)
        client.post(f'/booking/cancel/{first}')
        self.assertTrue(self.book(client, 10, 1).headers['Location'].endswith('/user/dashboard'))

    def test_real_accounts_keep_todays_rules(self):
        self.client.post('/login', data={'username': 'user1', 'password': 'user123'})
        with flask_app.app_context():
            self.assertEqual(bookings.limits_for(User.query.filter_by(username='user1').one().id), (None, None))
        response = self.book(self.client, 3, 5)  # more than a walker may book
        self.assertTrue(response.headers['Location'].endswith('/user/dashboard'))
        for trek_id in (8, 9, 10):  # four active bookings, plus the seeded Hampta Pass
            self.assertTrue(self.book(self.client, trek_id, 1).headers['Location'].endswith('/user/dashboard'))
        with flask_app.app_context():
            user = User.query.filter_by(username='user1').one()
            self.assertEqual(Booking.query.filter_by(user_id=user.id, status='Booked').count(), 5)
        self.assertEqual(self.seats(3), 25)

    def test_the_session_names_the_user_too(self):
        # A session whose username doesn't match its id (an id SQLite gave to a new
        # account) is signed out; a normal one is unaffected.
        self.client.post('/login', data={'username': 'user1', 'password': 'user123'})
        self.assertEqual(self.client.get('/user/dashboard').status_code, 200)
        with self.client.session_transaction() as session:
            session['username'] = 'someone-else'
        response = self.client.get('/user/dashboard')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers['Location'])


if __name__ == '__main__':
    unittest.main()
