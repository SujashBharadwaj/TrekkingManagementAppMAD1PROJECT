"""GET /api/...: a small public, read-only JSON API for the treks (see docs/API.md).

    GET /api/treks                  upcoming Open departures: the MCP list_treks tool's search
    GET /api/treks/<id>             one departure, as its public trek page shows it
    GET /api/treks/<id>/itinerary   its approved day-by-day plan

Everything here is already on the public pages (services/catalogue.py decides the
fields), so there's no token. Every answer carries Access-Control-Allow-Origin: *,
so a reader can try it from a browser console, and may be cached for a minute.
Nothing reads the login session or sets a cookie. HEAD is answered like GET
(RFC 9110 asks for that wherever GET works), OPTIONS answers browser preflights,
and every other method is refused. Refusals are {"error": "<one plain sentence>"}.
"""
import json

from flask import Blueprint, Response, request

from services import catalogue
from services.catalogue import SearchError

FILTERS = ('month', 'region', 'difficulty')
ALLOWED = 'GET, HEAD, OPTIONS'
NOT_FOUND = 'Not found. The API has /api/treks, /api/treks/<id> and /api/treks/<id>/itinerary.'
NOT_ALLOWED = 'Method not allowed: the API is read-only, so it answers GET, HEAD and OPTIONS only.'

# Every common method reaches the views, so each answers HEAD, OPTIONS and the rest
# itself, with these headers (Flask would otherwise answer OPTIONS on its own).
_METHODS = ['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']

api_bp = Blueprint('api', __name__)


@api_bp.route('/api/treks', methods=_METHODS, provide_automatic_options=False)
def list_treks():
    other = _other_method()
    if other is not None:
        return other
    filters = {}
    for name in request.args:
        if name not in FILTERS:
            return _send(400, _error(f'Unknown parameter "{catalogue.plain_text(name, 40)}". '
                                     f'The parameters are {catalogue.join_words(FILTERS, "and")}.'))
        values = request.args.getlist(name)
        if len(values) > 1:
            return _send(400, _error(f'Give "{name}" only once.'))
        filters[name] = values[0]
    try:
        return _send(200, catalogue.search(**filters))
    except SearchError as problem:
        return _send(400, _error(str(problem)))


@api_bp.route('/api/treks/<int:trek_id>', methods=_METHODS, provide_automatic_options=False)
def one_trek(trek_id):
    other = _other_method()
    if other is not None:
        return other
    trek = catalogue.public_trek(trek_id)
    if trek is None:
        return _send(404, _error(f'No trek with id {trek_id}.'))
    return _send(200, catalogue.detail(trek))


@api_bp.route('/api/treks/<int:trek_id>/itinerary', methods=_METHODS, provide_automatic_options=False)
def trek_itinerary(trek_id):
    other = _other_method()
    if other is not None:
        return other
    trek = catalogue.public_trek(trek_id)
    if trek is None:
        return _send(404, _error(f'No trek with id {trek_id}.'))
    return _send(200, catalogue.itinerary(trek))


# An id that isn't a whole number (abc, -1, 1.5) is just an unknown id. Werkzeug tries
# the <int:...> rules above first, so these only see what those turned down.
@api_bp.route('/api/treks/<raw_id>', methods=_METHODS, provide_automatic_options=False)
@api_bp.route('/api/treks/<raw_id>/itinerary', methods=_METHODS, provide_automatic_options=False)
def unknown_trek(raw_id):
    other = _other_method()
    if other is not None:
        return other
    return _send(404, _error(f'No trek with id {catalogue.plain_text(raw_id, 40)}.'))


# Anything else under /api answers in JSON too, rather than with the website's HTML
# 404 page, whatever the method: there's nothing there to describe.
@api_bp.route('/api/', defaults={'rest': ''}, strict_slashes=False,  # /api too, without a redirect
              methods=_METHODS, provide_automatic_options=False)
@api_bp.route('/api/<path:rest>', methods=_METHODS, provide_automatic_options=False)
def not_found(rest):
    return _send(404, _error(NOT_FOUND))


def _other_method():
    """None for GET and HEAD, which the view answers (Werkzeug leaves the body out of
    a HEAD answer and keeps its headers). Otherwise the answer itself: 204 with the
    CORS headers for OPTIONS, so a browser's preflight passes, and 405 for the rest."""
    if request.method in ('GET', 'HEAD'):
        return None
    if request.method == 'OPTIONS':
        response = Response(status=204)
        response.headers.pop('Content-Type', None)  # no body to describe
        _common_headers(response)
        response.headers['Allow'] = ALLOWED
        response.headers['Access-Control-Allow-Methods'] = ALLOWED
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response
    return _send(405, _error(NOT_ALLOWED), {'Allow': ALLOWED})


def _error(sentence):
    return {'error': sentence}


def _send(status, body, headers=None):
    # Indented, because people read these answers as often as programs do.
    text = json.dumps(body, ensure_ascii=False, indent=2) + '\n'
    response = Response(text, status=status, content_type='application/json; charset=utf-8')
    _common_headers(response)
    for name, value in (headers or {}).items():
        response.headers[name] = value
    return response


def _common_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'  # public, read-only data
    response.headers['Cache-Control'] = 'public, max-age=60'
    response.headers['X-Content-Type-Options'] = 'nosniff'
