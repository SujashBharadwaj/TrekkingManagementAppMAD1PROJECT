"""POST /demo/walker: sign-in details for one visit's walker, for the browser agent.

The portfolio's live demo drives a real (headless) Chrome through this website, so
its agent books the way a person does: it signs in on /login and fills in the trek
page's booking form. This endpoint gives it the details to sign in with: the
visit's throwaway trekker (mcp_server/visits.py, made now if it has none) and a new
random password, which replaces the last one. The walker goes after an hour, with
its bookings and its password, like the MCP agent's.

The door is the same as /mcp's (routes/door.py): off (404) without MCP_TOKEN, POST
only, the Origin allowlist, the bearer token, and a body of 1 KB at most. Refusals
are {"error": "<one plain sentence>"}.

    POST /demo/walker
    Authorization: Bearer <MCP_TOKEN>
    {"visit_id": "<uuid v4>"}

    200 {"username": "walker-3b8f2c1a", "password": "<22 characters>"}
"""
import json

from flask import Blueprint, Response, abort, current_app, request

from mcp_server.visits import DemoBusy, Visit, housekeeping, sign_in_details
from models import db
from . import door

MAX_BODY_BYTES = 1024
BAD_BODY = 'Bad request: send a JSON object with one field, "visit_id", a UUID v4.'
NOT_SET_UP = "This visit's demo trekker couldn't be set up. Please try again."

demo_bp = Blueprint('demo', __name__)


@demo_bp.route('/demo/walker', methods=door.METHODS, provide_automatic_options=False)
def demo_walker():
    token = door.configured_token()
    if not token:
        abort(404)
    if request.method != 'POST':
        return _send(405, _error('Method not allowed: this endpoint takes POST only.'), {'Allow': 'POST'})
    origin = request.headers.get('Origin')
    if origin is not None and not door.origin_allowed(origin):
        return _send(403, _error('Forbidden: requests from this origin are not allowed.'))
    if not door.token_matches(request.headers.get('Authorization'), token):
        return _send(401, _error('Unauthorized: send "Authorization: Bearer <MCP_TOKEN>".'),
                     {'WWW-Authenticate': 'Bearer'})
    raw = door.read_body(MAX_BODY_BYTES)
    if raw is None:
        return _send(413, _error(f'Payload too large: the body must be {MAX_BODY_BYTES} bytes or less.'))
    visit = _visit(raw)
    if visit is None:
        return _send(400, _error(BAD_BODY))
    try:
        return _walker_details(visit)
    except Exception:  # a JSON error, never an HTML error page
        db.session.rollback()
        current_app.logger.exception('Demo walker request failed')
        return _send(500, _error('Internal error: the app hit a problem. Please try again.'))


def _walker_details(visit):
    housekeeping()
    try:
        walker = visit.walker_or_create()
    except DemoBusy as busy:
        return _send(429, _error(str(busy)), {'Retry-After': '60'})
    details = sign_in_details(walker) if walker is not None else None
    if details is None:
        return _send(503, _error(NOT_SET_UP))
    username, password = details
    return _send(200, {'username': username, 'password': password})


def _visit(raw):
    """The Visit named by a body of exactly {"visit_id": "<uuid v4>"}, or None."""
    try:
        body = json.loads(raw.decode('utf-8'))
    except (ValueError, RecursionError):  # bad UTF-8 and bad JSON are both ValueErrors
        return None
    if not isinstance(body, dict) or set(body) != {'visit_id'} or not isinstance(body['visit_id'], str):
        return None
    visit = Visit(body['visit_id'])
    return visit if visit.id is not None else None


def _error(sentence):
    return {'error': sentence}


def _send(status, body, headers=None):
    response = Response(json.dumps(body, ensure_ascii=False), status=status, mimetype='application/json')
    # The password must never sit in a cache, and refusals shouldn't either.
    response.headers['Cache-Control'] = 'no-store'
    for name, value in (headers or {}).items():
        response.headers[name] = value
    return response
