"""The door shared by the two token-guarded endpoints, POST /mcp and POST /demo/walker.

Both are off (404) until MCP_TOKEN is set. From then on they take POST only, refuse
an Origin header that isn't on MCP_ALLOWED_ORIGINS, need "Authorization: Bearer
<MCP_TOKEN>" and cap the body. Each route runs these checks in that order and words
its refusals in its own format (JSON-RPC for /mcp, a plain sentence for /demo/walker).
Neither reads the Flask session, so a browser's cookies can't change what they do.
"""
import hashlib
import hmac

from flask import current_app, request

# Every common method is routed to a guarded endpoint, so that while it is off each
# one gets the same 404 (Flask would otherwise answer OPTIONS or PUT by itself).
METHODS = ['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']


def configured_token():
    """MCP_TOKEN, or '' while the guarded endpoints are off."""
    return current_app.config.get('MCP_TOKEN') or ''


def origin_allowed(origin):
    allowed = current_app.config.get('MCP_ALLOWED_ORIGINS') or []
    if isinstance(allowed, str):
        allowed = allowed.split(',')
    wanted = origin.strip().rstrip('/').lower()
    return any(wanted == entry.strip().rstrip('/').lower() for entry in allowed if entry.strip())


def token_matches(header, token):
    scheme, _, value = (header or '').strip().partition(' ')
    if scheme.lower() != 'bearer' or not value.strip():
        return False
    # Compare fixed-length digests in constant time, so timing reveals neither the
    # token nor its length.
    return hmac.compare_digest(hashlib.sha256(value.strip().encode('utf-8')).digest(),
                               hashlib.sha256(token.encode('utf-8')).digest())


def read_body(limit):
    """The request body, or None if it's over `limit` bytes (read no further than that)."""
    length = request.content_length
    if length is not None and length > limit:
        return None
    raw = request.stream.read(limit + 1)
    return None if len(raw) > limit else raw
