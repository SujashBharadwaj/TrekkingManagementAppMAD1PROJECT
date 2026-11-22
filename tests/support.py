"""Shared setup for the tests: a throwaway database and a small MCP client.

Import this before anything from the app: it points DATABASE_URL at a temporary
file first, so the module-level `app = create_app()` seeds that file and never
touches trekking.db. Seeding hashes nine passwords (a few seconds), so it runs
once, and fresh_db() copies the seeded file back before each test.
"""
import atexit
import json
import os
import shutil
import sys
import tempfile
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_TMP = tempfile.mkdtemp(prefix='mm-tests-')
DB_PATH = os.path.join(_TMP, 'test.db')
_SEEDED = os.path.join(_TMP, 'seeded.db')
os.environ['DATABASE_URL'] = 'sqlite:///' + DB_PATH.replace('\\', '/')
os.environ.pop('MCP_TOKEN', None)
os.environ.pop('MCP_ALLOWED_ORIGINS', None)

import app as app_module  # noqa: E402  (creates and seeds the throwaway database)
from models import db  # noqa: E402

flask_app = app_module.app
flask_app.config['TESTING'] = True

TOKEN = 'test-token-not-a-secret'
MODERN = '2026-07-28'
LEGACY = '2025-11-25'
META_VERSION = 'io.modelcontextprotocol/protocolVersion'
META_CAPABILITIES = 'io.modelcontextprotocol/clientCapabilities'


def _close_connections():
    with flask_app.app_context():
        db.session.remove()
        db.engine.dispose()


def _clean_up():
    _close_connections()
    shutil.rmtree(_TMP, ignore_errors=True)


_close_connections()
shutil.copyfile(DB_PATH, _SEEDED)
atexit.register(_clean_up)


def fresh_db():
    """Put the freshly seeded database back."""
    _close_connections()
    shutil.copyfile(_SEEDED, DB_PATH)


def new_visit():
    return str(uuid.uuid4())


class McpClient:
    """Sends JSON-RPC to /mcp the way a 2026-07-28 client does, unless told otherwise."""

    def __init__(self, client):
        self.client = client

    def post(self, body, headers=None, token=TOKEN):
        sent = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
        if token:
            sent['Authorization'] = f'Bearer {token}'
        sent.update(headers or {})
        sent = {name: value for name, value in sent.items() if value is not None}
        data = body if isinstance(body, (bytes, str)) else json.dumps(body)
        return self.client.post('/mcp', data=data, headers=sent)

    def request(self, method, params=None, era=MODERN, visit=None, headers=None, request_id=1):
        params = dict(params or {})
        sent = {}
        if era == MODERN:
            params.setdefault('_meta', {
                META_VERSION: MODERN,
                META_CAPABILITIES: {},
                'io.modelcontextprotocol/clientInfo': {'name': 'tests', 'version': '1.0.0'},
            })
            sent['Mcp-Method'] = method
            if method == 'tools/call':
                sent['Mcp-Name'] = params.get('name', '')
        if era is not None:
            sent['MCP-Protocol-Version'] = era
        if visit:
            sent['MM-Visit-Id'] = visit
        sent.update(headers or {})
        return self.post({'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params}, sent)

    def call(self, tool, arguments=None, visit=None, era=MODERN, headers=None):
        params = {'name': tool}
        if arguments is not None:
            params['arguments'] = arguments
        return self.request('tools/call', params, era=era, visit=visit, headers=headers)
