"""A small JSON Schema checker for the MCP tools' arguments.

The usual validators are separate packages, and this app adds none. The tools'
schemas use a handful of keywords, and this checks exactly those: type,
properties, required, additionalProperties (false only), enum, minimum, maximum,
minLength, maxLength, pattern, items, minItems and maxItems. Every other keyword
(description, title, default, format, examples) is an annotation, which is how
JSON Schema 2020-12 treats keywords a validator doesn't assert. The schemas are
written in mcp_server/tools.py, never sent by clients, so nothing else can turn up.

validate() returns the value with defaults filled in, or raises SchemaError with
one plain sentence that names the field.
"""
import math
import re

_TYPE_WORDS = {
    'integer': 'a whole number',
    'number': 'a number',
    'string': 'text',
    'boolean': 'true or false',
    'object': 'an object',
    'array': 'a list',
    'null': 'null',
}


class SchemaError(ValueError):
    """The value doesn't fit the schema. str(error) is one plain sentence."""


def validate(schema, value, hints=None, what='The arguments'):
    """Check `value` against `schema` and return a copy with defaults filled in.

    hints maps a field path (for example "month") to the sentence to use when that
    field's format is wrong, since a regular expression makes a poor error message.
    what names the whole value in messages about it.
    """
    return _check(schema, value, '', hints or {}, what)


def _check(schema, value, path, hints, what):
    label = f'"{path}"' if path else what
    types = schema.get('type')
    if types is not None:
        allowed = [types] if isinstance(types, str) else list(types)
        matched = next((t for t in allowed if _is_type(value, t)), None)
        if matched is None:
            raise SchemaError(f'{label} must be {_join([_TYPE_WORDS.get(t, t) for t in allowed], "or")}.')
        if matched == 'integer' and isinstance(value, float):
            value = int(value)  # 2.0 counts as an integer in JSON Schema

    if 'enum' in schema and value not in schema['enum']:
        raise SchemaError(f'{label} must be {_join([_show(v) for v in schema["enum"]], "or")}.')

    if _is_type(value, 'number'):
        low, high = schema.get('minimum'), schema.get('maximum')
        if (low is not None and value < low) or (high is not None and value > high):
            if low is not None and high is not None:
                raise SchemaError(f'{label} must be from {low} to {high}.')
            if low is not None:
                raise SchemaError(f'{label} must be {low} or more.')
            raise SchemaError(f'{label} must be {high} or less.')

    if isinstance(value, str):
        if 'minLength' in schema and len(value) < schema['minLength']:
            raise SchemaError(f'{label} must be at least {schema["minLength"]} characters long.')
        if 'maxLength' in schema and len(value) > schema['maxLength']:
            raise SchemaError(f'{label} must be at most {schema["maxLength"]} characters long.')
        if 'pattern' in schema:
            match = re.search(schema['pattern'], value)
            # Python's $ also matches just before a final newline; JSON Schema's doesn't.
            if match is None or (schema['pattern'].endswith('$') and match.end() != len(value)):
                raise SchemaError(hints.get(path) or f'{label} is not in the expected format.')

    if isinstance(value, dict):
        value = _check_object(schema, value, path, hints, what)

    if isinstance(value, list):
        if 'minItems' in schema and len(value) < schema['minItems']:
            raise SchemaError(f'{label} must have at least {schema["minItems"]} items.')
        if 'maxItems' in schema and len(value) > schema['maxItems']:
            raise SchemaError(f'{label} must have at most {schema["maxItems"]} items.')
        if 'items' in schema:
            value = [_check(schema['items'], item, f'{path}[{i}]', hints, what)
                     for i, item in enumerate(value)]
    return value


def _check_object(schema, value, path, hints, what):
    properties = schema.get('properties', {})
    if schema.get('additionalProperties') is False:
        for key in value:
            if key not in properties:
                where = f' in "{path}"' if path else ''
                if properties:
                    known = _join([f'"{name}"' for name in properties], 'and')
                    raise SchemaError(f'Unknown argument "{key}"{where}. The arguments are {known}.')
                raise SchemaError(f'Unknown argument "{key}"{where}. This takes no arguments.')
    for name in schema.get('required', []):
        if name not in value:
            raise SchemaError(f'"{_child(path, name)}" is required.')
    checked = {}
    for key, item in value.items():
        if key in properties:
            checked[key] = _check(properties[key], item, _child(path, key), hints, what)
        else:
            checked[key] = item
    for name, sub in properties.items():
        if name not in checked and 'default' in sub:
            checked[name] = sub['default']
    return checked


def _is_type(value, name):
    if name == 'integer':
        if isinstance(value, bool):
            return False
        return isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    if name == 'number':
        if isinstance(value, bool):
            return False
        # An int is always finite, and math.isfinite() can't take one too big for a float.
        return isinstance(value, int) or (isinstance(value, float) and math.isfinite(value))
    if name == 'string':
        return isinstance(value, str)
    if name == 'boolean':
        return isinstance(value, bool)
    if name == 'object':
        return isinstance(value, dict)
    if name == 'array':
        return isinstance(value, list)
    if name == 'null':
        return value is None
    return False


def _child(path, name):
    return f'{path}.{name}' if path else name


def _show(value):
    return 'null' if value is None else str(value)


def _join(words, last):
    words = list(words)
    if len(words) <= 1:
        return ''.join(words)
    return f'{", ".join(words[:-1])} {last} {words[-1]}'
