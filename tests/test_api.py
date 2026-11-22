"""Tests for the public JSON API: GET /api/treks, /api/treks/<id> and
/api/treks/<id>/itinerary, their refusals and headers, and that the list matches
the MCP list_treks tool's for the same filters.

From the repo root:  venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""
import json
import unittest
from datetime import date, timedelta

import support  # first: it points the app at a throwaway database
from support import TOKEN, McpClient, flask_app

from models import db, Itinerary, Trek
from services import catalogue

LIST_FIELDS = {'id', 'name', 'region', 'difficulty', 'start_date', 'end_date', 'days', 'price_inr',
               'seats_left'}
DETAIL_FIELDS = ['id', 'name', 'location', 'region', 'difficulty', 'start_date', 'end_date', 'days',
                 'price_inr', 'seats_left', 'total_seats', 'status', 'best_season', 'route_kms',
                 'description']
NOT_FOUND = 'Not found. The API has /api/treks, /api/treks/<id> and /api/treks/<id>/itinerary.'
REGION = '"region" must be North, East, West or South.'
DIFFICULTY = '"difficulty" must be Easy, Moderate or Hard.'


def next_june():
    today = date.today()
    return f'{today.year if today.month < 6 else today.year + 1}-06'


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        support.fresh_db()
        self.client = flask_app.test_client()

    def tearDown(self):
        flask_app.config['MCP_TOKEN'] = ''

    # --- helpers ---

    def get(self, path, status=200, client=None):
        response = (client or self.client).get(path)
        self.assertEqual(response.status_code, status, response.get_data(as_text=True))
        self.assert_api_headers(response)
        return response.get_json()

    def assert_api_headers(self, response):
        self.assertEqual(response.headers['Content-Type'], 'application/json; charset=utf-8')
        self.assertEqual(response.headers['Access-Control-Allow-Origin'], '*')
        self.assertEqual(response.headers['Cache-Control'], 'public, max-age=60')
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        self.assertNotIn('Set-Cookie', response.headers)
        self.assertNotIn('Cookie', response.headers.get('Vary', ''))

    def error(self, path, status):
        body = self.get(path, status)
        self.assertEqual(set(body), {'error'}, body)
        return body['error']

    def mcp_list(self, arguments):
        """The MCP list_treks tool's answer: its data, or its refusal's sentence."""
        flask_app.config['MCP_TOKEN'] = TOKEN
        result = McpClient(flask_app.test_client()).call('list_treks', arguments).get_json()['result']
        if result['isError']:
            return result['content'][0]['text']
        return result['structuredContent']

    def rename(self, trek_id, name):
        with flask_app.app_context():
            db.session.get(Trek, trek_id).name = name
            db.session.commit()


class ListTests(ApiTestCase):
    def test_upcoming_open_departures_soonest_first(self):
        data = self.get('/api/treks')
        self.assertEqual(set(data), {'treks', 'total'})
        self.assertEqual(len(data['treks']), 10)
        self.assertGreater(data['total'], 10)
        order = [(trek['start_date'], trek['id']) for trek in data['treks']]
        self.assertEqual(order, sorted(order))
        with flask_app.app_context():
            for trek in data['treks']:
                self.assertEqual(set(trek), LIST_FIELDS)
                row = db.session.get(Trek, trek['id'])
                self.assertEqual(row.status, 'Open')
                self.assertGreater(row.start_date, date.today())
                self.assertEqual(trek['seats_left'], row.available_slots)
                self.assertEqual(trek['price_inr'], int(row.price))

    def test_filters(self):
        data = self.get('/api/treks?region=West&difficulty=Easy')
        self.assertGreater(data['total'], 0)
        for trek in data['treks']:
            self.assertEqual((trek['region'], trek['difficulty']), ('West', 'Easy'))
        june = self.get(f'/api/treks?month={next_june()}')
        self.assertGreaterEqual(june['total'], 2)
        for trek in june['treks']:
            self.assertTrue(trek['start_date'].startswith(next_june() + '-'), trek)
        # The current month still has departures to come, so it's allowed.
        self.get('/api/treks?month=' + date.today().strftime('%Y-%m'))

    def test_bad_values(self):
        for month in ('2027-13', 'June', '2027-6', '27-06', '2027-06%0A', '%202027-06', ''):
            self.assertEqual(self.error(f'/api/treks?month={month}', 400), catalogue.MONTH_HINT, month)
        today = date.today()
        likely = today.year if today.month <= 6 else today.year + 1
        self.assertEqual(self.error(f'/api/treks?month={today.year - 1}-06', 400),
                         f'June {today.year - 1} has already passed. Try {likely}-06.')
        for region in ('Central', 'north', ''):
            self.assertEqual(self.error(f'/api/treks?region={region}', 400), REGION, region)
        self.assertEqual(self.error('/api/treks?difficulty=easy', 400), DIFFICULTY)
        unknown = 'Unknown parameter "{}". The parameters are month, region and difficulty.'
        self.assertEqual(self.error('/api/treks?sort=price', 400), unknown.format('sort'))
        self.assertEqual(self.error('/api/treks?max_price_inr=2000', 400), unknown.format('max_price_inr'))
        self.assertEqual(self.error('/api/treks?region=North&region=South', 400), 'Give "region" only once.')

    def test_a_past_month_says_which_one_was_meant(self):
        # Pinned to one day, so the sentence can be checked word for word.
        with flask_app.app_context():
            with self.assertRaises(catalogue.SearchError) as caught:
                catalogue.search(month='2026-06', today=date(2026, 11, 22))
            self.assertEqual(str(caught.exception), 'June 2026 has already passed. Try 2027-06.')
            with self.assertRaises(catalogue.SearchError) as caught:
                catalogue.search(month='2025-12', today=date(2026, 11, 22))
            self.assertEqual(str(caught.exception), 'December 2025 has already passed. Try 2026-12.')
            self.assertIn('total', catalogue.search(month='2026-11', today=date(2026, 11, 22)))  # this month is fine

    def test_the_same_treks_as_the_mcp_tool(self):
        for query, arguments in (('', {}),
                                 (f'month={next_june()}', {'month': next_june()}),
                                 ('region=West&difficulty=Easy', {'region': 'West', 'difficulty': 'Easy'}),
                                 (f'month={next_june()}&region=North', {'month': next_june(), 'region': 'North'})):
            self.assertEqual(self.get('/api/treks?' + query), self.mcp_list(arguments), query)
        # And the same sentence for the same mistake.
        last_year = f'{date.today().year - 1}-06'
        for query, arguments in ((f'month={last_year}', {'month': last_year}),
                                 ('month=June', {'month': 'June'}),
                                 ('region=Central', {'region': 'Central'}),
                                 ('difficulty=easy', {'difficulty': 'easy'})):
            self.assertEqual(self.error('/api/treks?' + query, 400), self.mcp_list(arguments), query)

    def test_seats_follow_bookings(self):
        before = self.get('/api/treks/3')['seats_left']
        self.client.post('/login', data={'username': 'user3', 'password': 'user123'})
        self.client.post('/book/3', data={'slots': '2'})
        self.assertEqual(self.get('/api/treks/3')['seats_left'], before - 2)


class DetailTests(ApiTestCase):
    def test_one_departure(self):
        data = self.get('/api/treks/1')
        self.assertEqual(list(data), DETAIL_FIELDS)
        with flask_app.app_context():
            row = db.session.get(Trek, 1)
            self.assertEqual(data, {
                'id': 1, 'name': 'Hampta Pass Trek', 'location': 'Manali, Himachal Pradesh',
                'region': 'North', 'difficulty': 'Moderate',
                'start_date': row.start_date.isoformat(), 'end_date': row.end_date.isoformat(),
                'days': 5, 'price_inr': 8500, 'seats_left': 18, 'total_seats': 20, 'status': 'Open',
                'best_season': 'Summer', 'route_kms': 26.0,
                'description': 'A crossover trek from Manali to Spiti Valley through green meadows and '
                               'snow-covered passes.',
            })
            # Its list fields are exactly the list's.
            self.assertEqual({key: data[key] for key in LIST_FIELDS}, catalogue.summary(row))
        # What the public trek page shows, the API shows.
        page = self.client.get('/trek/1').get_data(as_text=True)
        self.assertIn('Slots Available:</strong> 18 / 20', page)
        self.assertIn(data['description'], page)

    def test_other_public_statuses_are_shown(self):
        data = self.get('/api/treks/7')  # Triund, Completed: on the website, though not bookable
        self.assertEqual((data['name'], data['status']), ('Triund Trek', 'Completed'))
        self.assertNotIn(7, [trek['id'] for trek in self.get('/api/treks?region=North')['treks']])

    def test_pending_unknown_and_odd_ids(self):
        for raw, shown in (('6', '6'),  # Chadar is Pending: waiting for approval, so not public
                           ('999', '999'), ('0', '0'), ('-1', '-1'), ('1.5', '1.5'), ('abc', 'abc'),
                           (str(10 ** 30), str(10 ** 30))):
            self.assertEqual(self.error(f'/api/treks/{raw}', 404), f'No trek with id {shown}.', raw)
            self.assertEqual(self.error(f'/api/treks/{raw}/itinerary', 404), f'No trek with id {shown}.', raw)

    def test_private_details_stay_out(self):
        texts = [json.dumps(self.get(path), ensure_ascii=False)
                 for path in ('/api/treks/1', '/api/treks/5', '/api/treks/7', '/api/treks/1/itinerary',
                              '/api/treks', '/api/treks?region=North&difficulty=Hard')]
        for text in texts:
            # local_connects (phone numbers), base_camp_info, staff, emails, bookings' notes
            for private in ('+91', 'Raju', 'Hospital', 'Mall Road', 'Lohajung base camp', 'Staff Guide',
                            '@', 'asthma', 'Vegetarian', 'user1', 'user5', 'commission'):
                self.assertNotIn(private, text)

    def test_text_is_plain_and_utf8(self):
        self.rename(3, 'केदारकांठा Trek\u202e with\x00 tricks\n' + 'x' * 120)
        response = self.client.get('/api/treks/3')
        name = response.get_json()['name']
        self.assertTrue(name.startswith('केदारकांठा Trek with tricks xxx'), name)
        self.assertLessEqual(len(name), 80)
        self.assertIn('केदारकांठा'.encode('utf-8'), response.get_data())  # sent as UTF-8, not \u escapes
        flask_app.config['MCP_TOKEN'] = TOKEN
        mcp = McpClient(flask_app.test_client()).call('check_availability', {'trek_id': 3}).get_json()
        self.assertEqual(mcp['result']['structuredContent']['name'], name)


class ItineraryTests(ApiTestCase):
    def test_approved_days_in_order(self):
        with flask_app.app_context():
            db.session.add(Itinerary(trek_id=1, day_number=5, title='Chatru to Manali',
                                     description='Not approved yet', is_approved=False))
            db.session.commit()
        data = self.get('/api/treks/1/itinerary')
        self.assertEqual(set(data), {'trek_id', 'days'})
        self.assertEqual(data['trek_id'], 1)
        self.assertEqual([day['day'] for day in data['days']], [1, 2, 3, 4])
        self.assertEqual(data['days'][0], {'day': 1, 'title': 'Manali to Jobra',
                                           'details': 'Drive to Jobra and short acclimatisation walk.'})
        for day in data['days']:
            self.assertEqual(set(day), {'day', 'title', 'details'})

    def test_a_trek_without_a_published_plan(self):
        self.assertEqual(self.get('/api/treks/3/itinerary'), {'trek_id': 3, 'days': []})


class MethodAndPathTests(ApiTestCase):
    ENDPOINTS = ('/api/treks', '/api/treks?region=West', '/api/treks?region=Central', '/api/treks/1',
                 '/api/treks/1/itinerary', '/api/treks/6', '/api/treks/999/itinerary', '/api/treks/abc')

    def test_head_is_get_without_the_body(self):
        # RFC 9110: a server that answers GET must answer HEAD the same way, minus the body.
        for path in self.ENDPOINTS:
            got = self.client.get(path)
            head = self.client.head(path)
            self.assertEqual(head.status_code, got.status_code, path)
            self.assert_api_headers(head)
            self.assertEqual(head.get_data(), b'', path)
            self.assertGreater(len(got.get_data()), 0, path)
            self.assertEqual(head.headers['Content-Length'], str(len(got.get_data())), path)

    def test_options_answers_preflights(self):
        for path in self.ENDPOINTS:
            # What a browser sends before a cross-site GET with a Content-Type header.
            response = self.client.options(path, headers={'Origin': 'https://example.com',
                                                          'Access-Control-Request-Method': 'GET',
                                                          'Access-Control-Request-Headers': 'content-type'})
            self.assertEqual(response.status_code, 204, path)
            self.assertEqual(response.get_data(), b'', path)
            self.assertNotIn('Content-Type', response.headers)
            self.assertEqual(response.headers['Allow'], 'GET, HEAD, OPTIONS')
            self.assertEqual(response.headers['Access-Control-Allow-Origin'], '*')
            self.assertEqual(response.headers['Access-Control-Allow-Methods'], 'GET, HEAD, OPTIONS')
            self.assertEqual(response.headers['Access-Control-Allow-Headers'], 'Content-Type')
            self.assertNotIn('Set-Cookie', response.headers)

    def test_other_methods_are_refused(self):
        for path in self.ENDPOINTS:
            for method in ('post', 'put', 'patch', 'delete'):
                response = getattr(self.client, method)(path)
                self.assertEqual(response.status_code, 405, f'{method} {path}')
                self.assertEqual(response.headers['Allow'], 'GET, HEAD, OPTIONS')
                self.assert_api_headers(response)
                self.assertEqual(response.get_json(), {
                    'error': 'Method not allowed: the API is read-only, so it answers GET, HEAD and OPTIONS only.'})

    def test_other_paths_under_api_answer_in_json(self):
        for path in ('/api', '/api/', '/api/trek', '/api/treks/', '/api/treks/1/reviews', '/api/bookings'):
            self.assertEqual(self.error(path, 404), NOT_FOUND, path)
            for method in ('head', 'options', 'post'):  # nothing there, whatever the method
                response = getattr(self.client, method)(path)
                self.assertEqual(response.status_code, 404, f'{method} {path}')
                self.assert_api_headers(response)

    def test_ignores_the_login_session(self):
        anonymous = self.get('/api/treks/1')
        self.client.post('/login', data={'username': 'admin', 'password': 'admin123'})
        self.assertEqual(self.get('/api/treks/1'), anonymous)
        self.assertEqual(self.error('/api/treks/6', 404), 'No trek with id 6.')  # even for the admin


if __name__ == '__main__':
    unittest.main()
