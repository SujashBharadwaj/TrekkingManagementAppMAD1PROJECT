"""Unit tests for the hand-written JSON Schema checker in mcp_server/schema.py."""
import unittest

import support  # noqa: F401  (puts the repo root on sys.path)
from mcp_server.schema import SchemaError, validate

SEATS = {'type': 'object',
         'properties': {'seats': {'type': 'integer', 'minimum': 1, 'maximum': 4, 'default': 1},
                        'insurance': {'type': 'boolean', 'default': False}},
         'additionalProperties': False}


class SchemaTests(unittest.TestCase):
    def fails(self, schema, value):
        with self.assertRaises(SchemaError) as caught:
            validate(schema, value)
        return str(caught.exception)

    def test_fills_defaults_and_keeps_given_values(self):
        self.assertEqual(validate(SEATS, {}), {'seats': 1, 'insurance': False})
        self.assertEqual(validate(SEATS, {'seats': 3}), {'seats': 3, 'insurance': False})

    def test_integers(self):
        self.assertEqual(validate(SEATS, {'seats': 2.0})['seats'], 2)
        self.assertIsInstance(validate(SEATS, {'seats': 2.0})['seats'], int)
        for value in (True, 2.5, '2', None, [2]):
            self.assertEqual(self.fails(SEATS, {'seats': value}), '"seats" must be a whole number.')
        self.assertEqual(self.fails(SEATS, {'seats': 0}), '"seats" must be from 1 to 4.')

    def test_booleans_are_strict(self):
        for value in (1, 'true', None):
            self.assertEqual(self.fails(SEATS, {'insurance': value}), '"insurance" must be true or false.')

    def test_unknown_and_missing_keys(self):
        self.assertEqual(self.fails(SEATS, {'seats': 1, 'admin': True}),
                         'Unknown argument "admin". The arguments are "seats" and "insurance".')
        self.assertEqual(self.fails({'type': 'object', 'properties': {}, 'additionalProperties': False}, {'x': 1}),
                         'Unknown argument "x". This takes no arguments.')
        self.assertEqual(self.fails(dict(SEATS, required=['seats']), {}), '"seats" is required.')
        self.assertEqual(self.fails(SEATS, ['seats']), 'The arguments must be an object.')

    def test_nested_values_name_their_path(self):
        shape = {'type': 'object', 'properties': {
            'treks': {'type': 'array', 'maxItems': 2, 'items': {
                'type': 'object', 'properties': {'id': {'type': 'integer'}}, 'required': ['id'],
                'additionalProperties': False}}}}
        self.assertEqual(self.fails(shape, {'treks': [{'id': 1}, {'id': 'two'}]}),
                         '"treks[1].id" must be a whole number.')
        self.assertEqual(self.fails(shape, {'treks': [{'id': 1}, {}]}), '"treks[1].id" is required.')
        self.assertEqual(self.fails(shape, {'treks': [{'id': 1}] * 3}), '"treks" must have at most 2 items.')

    def test_enums_patterns_and_nullable_types(self):
        shape = {'type': 'object', 'properties': {
            'region': {'type': 'string', 'enum': ['North', 'South']},
            'month': {'type': 'string', 'pattern': '^[0-9]{4}-(0[1-9]|1[0-2])$'},
            'reason': {'type': ['string', 'null']}}}
        self.assertEqual(self.fails(shape, {'region': 'West'}), '"region" must be North or South.')
        self.assertEqual(self.fails(shape, {'month': '2027-13'}), '"month" is not in the expected format.')
        with self.assertRaises(SchemaError) as caught:
            validate(shape, {'month': 'June'}, hints={'month': 'Write the month as YYYY-MM.'})
        self.assertEqual(str(caught.exception), 'Write the month as YYYY-MM.')
        self.assertEqual(validate(shape, {'reason': None}), {'reason': None})
        self.assertEqual(self.fails(shape, {'reason': 3}), '"reason" must be text or null.')


if __name__ == '__main__':
    unittest.main()
