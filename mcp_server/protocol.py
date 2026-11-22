"""JSON-RPC 2.0 and MCP for the /mcp endpoint, written by hand.

It speaks MCP 2026-07-28 ("modern"): no sessions and no handshake, and every
request carries its protocol version, both in the MCP-Protocol-Version header
and in params._meta, with Mcp-Method (and Mcp-Name for tools/call) mirroring the
body. It also serves 2025-11-25 and 2025-06-18 clients ("legacy", such as MCP
Inspector's default mode): their initialize gets a stateless answer with no
session id, and their later requests are served by the version in their header.

Every reply is one application/json body. Nothing is streamed, because every
tool finishes in milliseconds.
"""
import base64
import binascii
import json

from flask import current_app

from models import db
from . import tools
from .visits import Visit, housekeeping

MODERN_VERSIONS = ('2026-07-28',)
LEGACY_VERSIONS = ('2025-11-25', '2025-06-18')
SUPPORTED_VERSIONS = MODERN_VERSIONS + LEGACY_VERSIONS

SERVER_INFO = {'name': 'mountains-and-maggi', 'title': 'Mountains & Maggi', 'version': '1.0.0'}
CAPABILITIES = {'tools': {'listChanged': False}}
INSTRUCTIONS = (
    "Mountains & Maggi is a demo trekking app with made-up data. The tools act as this "
    "visit's own demo trekker, whose bookings are deleted after an hour. Dates are "
    "YYYY-MM-DD, and prices are whole rupees per seat.")
CACHE_TTL_MS = 60 * 60 * 1000  # the tool list changes only with a new deploy

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
HEADER_MISMATCH = -32020
UNSUPPORTED_PROTOCOL_VERSION = -32022

META_VERSION = 'io.modelcontextprotocol/protocolVersion'
META_CAPABILITIES = 'io.modelcontextprotocol/clientCapabilities'
META_SERVER_INFO = 'io.modelcontextprotocol/serverInfo'

# Methods whose name the client mirrors into the Mcp-Name header, and the field it comes from.
NAMED_METHODS = {'tools/call': 'name', 'prompts/get': 'name', 'resources/read': 'uri'}


class Reply:
    """An HTTP status and a JSON body for the route to send (body None means no body)."""

    def __init__(self, status, body=None):
        self.status = status
        self.body = body


def handle(raw, headers):
    """Answer one POSTed body. `headers` is the request's (case-insensitive) headers."""
    try:
        return _handle(raw, headers)
    except Exception:  # an error reply, never an HTML error page
        db.session.rollback()
        current_app.logger.exception('MCP request failed')
        return Reply(500, error(None, INTERNAL_ERROR, 'Internal error: the app hit a problem. Please try again.'))


def _handle(raw, headers):
    try:
        message = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_keys,
                             parse_constant=_no_constants)
    except (ValueError, RecursionError):  # bad UTF-8 and bad JSON are both ValueErrors
        return Reply(400, error(None, PARSE_ERROR, 'Parse error: the body is not valid JSON.'))
    if isinstance(message, list):
        return Reply(400, error(None, INVALID_REQUEST,
                                'Invalid request: send one JSON-RPC message per request, not a batch.'))
    if not isinstance(message, dict):
        return Reply(400, error(None, INVALID_REQUEST, 'Invalid request: the body must be a JSON-RPC object.'))

    has_id = 'id' in message
    request_id = message.get('id')
    id_ok = has_id and isinstance(request_id, (str, int)) and not isinstance(request_id, bool)
    known_id = request_id if id_ok else None
    if message.get('jsonrpc') != '2.0':
        return Reply(400, error(known_id, INVALID_REQUEST, 'Invalid request: "jsonrpc" must be "2.0".'))
    method = message.get('method')
    if not isinstance(method, str) or not method:
        return Reply(400, error(known_id, INVALID_REQUEST, 'Invalid request: "method" must be a non-empty string.'))
    if not has_id:
        # A notification: accepted with no reply. Legacy clients send
        # notifications/initialized after initialize.
        if method.startswith('notifications/'):
            return Reply(202)
        return Reply(400, error(None, INVALID_REQUEST, 'Invalid request: a request needs an "id".'))
    if not id_ok:
        return Reply(400, error(None, INVALID_REQUEST, 'Invalid request: "id" must be a string or an integer.'))
    params = message.get('params')
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return Reply(400, error(request_id, INVALID_PARAMS, 'Invalid params: "params" must be an object.'))

    if method == 'initialize':  # the legacy handshake
        problem = _header_problem(method, params, headers, modern=False)
        if problem:
            return Reply(400, error(request_id, HEADER_MISMATCH, problem))
        return _initialize(request_id, params)

    version = headers.get('MCP-Protocol-Version')
    if version is None:
        return Reply(400, error(request_id, HEADER_MISMATCH, 'Missing MCP-Protocol-Version header.'))
    if version not in SUPPORTED_VERSIONS:
        return Reply(400, error(request_id, UNSUPPORTED_PROTOCOL_VERSION, 'Unsupported protocol version',
                                {'supported': list(SUPPORTED_VERSIONS), 'requested': version}))
    modern = version in MODERN_VERSIONS
    problem = _header_problem(method, params, headers, modern)
    if problem:
        return Reply(400, error(request_id, HEADER_MISMATCH, problem))

    meta = params.get('_meta')
    if modern:
        missing = [key for key, kind in ((META_VERSION, str), (META_CAPABILITIES, dict))
                   if not isinstance(meta, dict) or not isinstance(meta.get(key), kind)]
        if missing:
            return Reply(400, error(request_id, INVALID_PARAMS,
                                    f'Invalid params: _meta must include {" and ".join(missing)}.'))
    if isinstance(meta, dict) and META_VERSION in meta and meta[META_VERSION] != version:
        return Reply(400, error(request_id, HEADER_MISMATCH,
                                f"Header mismatch: MCP-Protocol-Version header value '{_short(version)}' "
                                f"does not match body value '{_short(meta[META_VERSION])}'"))

    handler = _METHODS.get(method)
    if handler is None:
        # The 2026-07-28 transport answers an unknown method with 404; older
        # clients expect the error in an ordinary 200 reply.
        return Reply(404 if modern else 200, error(request_id, METHOD_NOT_FOUND, f'Method not found: {_short(method)}'))
    housekeeping()
    return handler(request_id, params, headers, modern)


# --- Methods ----------------------------------------------------------------

def _initialize(request_id, params):
    requested = params.get('protocolVersion')
    if not isinstance(requested, str):
        return Reply(200, error(request_id, INVALID_PARAMS, 'Invalid params: initialize needs a "protocolVersion".'))
    housekeeping()
    # Stateless: no Mcp-Session-Id, so every later request stands on its own.
    version = requested if requested in LEGACY_VERSIONS else LEGACY_VERSIONS[0]
    return Reply(200, result(request_id, {
        'protocolVersion': version,
        'capabilities': CAPABILITIES,
        'serverInfo': SERVER_INFO,
        'instructions': INSTRUCTIONS,
    }, modern=False))


def _discover(request_id, params, headers, modern):
    return Reply(200, result(request_id, {
        'supportedVersions': list(SUPPORTED_VERSIONS),
        'capabilities': CAPABILITIES,
        'instructions': INSTRUCTIONS,
        'ttlMs': CACHE_TTL_MS,
        'cacheScope': 'public',
    }, modern))


def _tools_list(request_id, params, headers, modern):
    if params.get('cursor') is not None:
        return Reply(200, error(request_id, INVALID_PARAMS,
                                'Invalid params: unknown cursor. All tools fit on one page.'))
    listing = {'tools': [tool.definition() for tool in tools.TOOLS]}
    if modern:
        listing.update(ttlMs=CACHE_TTL_MS, cacheScope='public')
    return Reply(200, result(request_id, listing, modern))


def _tools_call(request_id, params, headers, modern):
    name = params.get('name')
    if not isinstance(name, str):
        return Reply(200, error(request_id, INVALID_PARAMS, 'Invalid params: tools/call needs a tool "name".'))
    tool = tools.TOOLS_BY_NAME.get(name)
    if tool is None:
        return Reply(200, error(request_id, INVALID_PARAMS, f'Unknown tool: {_short(name)}'))
    arguments = params.get('arguments')
    if arguments is not None and not isinstance(arguments, dict):
        return Reply(200, error(request_id, INVALID_PARAMS, 'Invalid params: "arguments" must be an object.'))
    try:
        outcome = tools.call(tool, arguments, Visit(headers.get('MM-Visit-Id')))
    except Exception:
        db.session.rollback()
        current_app.logger.exception('MCP tool %s failed', name)
        return Reply(500, error(request_id, INTERNAL_ERROR, 'Internal error: the app hit a problem. Please try again.'))
    return Reply(200, result(request_id, outcome, modern))


def _ping(request_id, params, headers, modern):
    # 2026-07-28 removed ping; it's still answered for older clients and simple checks.
    return Reply(200, result(request_id, {}, modern))


_METHODS = {
    'server/discover': _discover,
    'tools/list': _tools_list,
    'tools/call': _tools_call,
    'ping': _ping,
}


# --- Envelopes and checks ---------------------------------------------------

def result(request_id, body, modern):
    """A JSON-RPC result. Modern results also carry resultType and the server's identity."""
    if modern:
        meta = dict(body.get('_meta') or {})
        meta[META_SERVER_INFO] = SERVER_INFO
        body = dict({'resultType': 'complete'}, **body)
        body['_meta'] = meta
    return {'jsonrpc': '2.0', 'id': request_id, 'result': body}


def error(request_id, code, message, data=None):
    """A JSON-RPC error. Without a readable request id the id is left out, as MCP's schema allows."""
    reply = {'jsonrpc': '2.0'}
    if request_id is not None:
        reply['id'] = request_id
    reply['error'] = {'code': code, 'message': message}
    if data is not None:
        reply['error']['data'] = data
    return reply


def _header_problem(method, params, headers, modern):
    """Why the Mcp-Method and Mcp-Name headers don't fit the body, or None.

    Modern clients must send them. Legacy clients don't, but if they do, they must match.
    """
    sent_method = headers.get('Mcp-Method')
    if sent_method is None:
        if modern:
            return 'Missing Mcp-Method header.'
    elif not _header_safe(sent_method):
        return 'The Mcp-Method header contains characters that are not allowed.'
    elif sent_method != method:
        return (f"Header mismatch: Mcp-Method header value '{_short(sent_method)}' "
                f"does not match body value '{_short(method)}'")
    field = NAMED_METHODS.get(method)
    if field is None:
        return None
    sent_name = headers.get('Mcp-Name')
    if sent_name is None:
        return 'Missing Mcp-Name header.' if modern else None
    decoded = _decode_header(sent_name)
    if decoded is None:
        return 'The Mcp-Name header is not a valid header value.'
    if decoded != params.get(field):
        return (f"Header mismatch: Mcp-Name header value '{_short(decoded)}' "
                f"does not match body value '{_short(params.get(field))}'")
    return None


def _decode_header(value):
    """A header value with the spec's =?base64?...?= form decoded, or None if it's invalid."""
    if not _header_safe(value):
        return None
    if value.startswith('=?base64?') and value.endswith('?=') and len(value) >= 11:
        try:
            return base64.b64decode(value[9:-2], validate=True).decode('utf-8')
        except (binascii.Error, UnicodeDecodeError):
            return None
    return value


def _header_safe(value):
    return all(ch == '\t' or 32 <= ord(ch) <= 126 for ch in value)


def _short(value, limit=60):
    text = str(value)
    return text if len(text) <= limit else text[:limit] + '...'


def _unique_keys(pairs):
    # A repeated key could mean one thing to a proxy and another here, so refuse it.
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f'repeated key {key!r}')
        seen[key] = value
    return seen


def _no_constants(name):
    raise ValueError(f'{name} is not valid JSON')
