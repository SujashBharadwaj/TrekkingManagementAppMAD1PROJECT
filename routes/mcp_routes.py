"""POST /mcp: the app's MCP endpoint for AI agents (see docs/MCP.md).

This file is the door. Without MCP_TOKEN the endpoint doesn't exist (404). With
it, other HTTP methods, browser origins that aren't on the allowlist, wrong
tokens and bodies over 8 KB are turned away here (with the checks in door.py,
which POST /demo/walker shares), and the rest goes to mcp_server/protocol.py. It
never touches the Flask session or the login decorators, so a browser's cookies
can't make the agent act as a signed-in user.
"""
import json

from flask import Blueprint, Response, abort, request

from mcp_server import protocol
from . import door

MAX_BODY_BYTES = 8 * 1024

mcp_bp = Blueprint('mcp', __name__)


@mcp_bp.route('/mcp', methods=door.METHODS, provide_automatic_options=False)
def mcp_endpoint():
    token = door.configured_token()
    if not token:
        abort(404)
    if request.method != 'POST':
        return _refuse(405, -31405, 'Method not allowed: the MCP endpoint takes POST only.',
                       {'Allow': 'POST'})
    origin = request.headers.get('Origin')
    if origin is not None and not door.origin_allowed(origin):
        # A browser page on another site (or a DNS rebinding attack) sends an Origin;
        # the portfolio's server-to-server calls don't.
        return _refuse(403, -31403, 'Forbidden: requests from this origin are not allowed.')
    if not door.token_matches(request.headers.get('Authorization'), token):
        return _refuse(401, -31401, 'Unauthorized: send "Authorization: Bearer <MCP_TOKEN>".',
                       {'WWW-Authenticate': 'Bearer'})
    raw = door.read_body(MAX_BODY_BYTES)
    if raw is None:
        return _refuse(413, -31413, f'Payload too large: the body must be {MAX_BODY_BYTES} bytes or less.')
    reply = protocol.handle(raw, request.headers)
    return _send(reply.status, reply.body)


def _refuse(status, code, message, headers=None):
    # Codes outside JSON-RPC's reserved range, as MCP asks for application errors.
    response = _send(status, protocol.error(None, code, message))
    for name, value in (headers or {}).items():
        response.headers[name] = value
    return response


def _send(status, body):
    if body is None:
        response = Response(status=status)
    else:
        response = Response(json.dumps(body, ensure_ascii=False), status=status,
                            mimetype='application/json')
    response.headers['Cache-Control'] = 'no-store'
    return response
