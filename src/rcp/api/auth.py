"""HTTP Basic auth for a publicly exposed deployment (see docs/DEPLOYMENT.md).

Pure ASGI rather than ``BaseHTTPMiddleware``: this check never reads the request
body, so wrapping every request in a task group and a memory object stream buys
nothing. Staying at the ASGI layer also means it cannot perturb the two response
paths this app depends on -- the SSE run stream and ``FileResponse``'s 206 /
Content-Range replies for pdf.js. It either sends its own 401 or forwards the
scope untouched.

A shared credential is transport protection, not identity. Nothing here is
recorded, and it must never be treated as evidence of who did something.
"""

from __future__ import annotations

import base64
import binascii
import secrets

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send


def parse_basic_credentials(header: str) -> tuple[bytes, bytes] | None:
    """Decode an ``Authorization: Basic ...`` value, or None if it is malformed."""
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:  # RFC 7617: the scheme is case-insensitive
        return None
    try:
        # validate=True matters: without it base64 silently discards characters
        # outside its alphabet, so "!!!!" would decode to b"" instead of failing.
        decoded = base64.b64decode(encoded.strip(), validate=True)
    except (binascii.Error, ValueError):
        return None
    # partition, not split: a password may legitimately contain a colon.
    user, separator, password = decoded.partition(b":")
    return (user, password) if separator else None


class BasicAuthMiddleware:
    """Reject every request that does not carry the shared Basic credential.

    An empty password disables the check entirely. That is what keeps the existing
    test suite and a bare `uvicorn rcp.api.main:app` working unchanged.
    """

    def __init__(self, app: ASGIApp, username: str, password: str, realm: str = "RCP") -> None:
        self.app = app
        self.enabled = bool(password)
        # Compared as bytes: secrets.compare_digest raises TypeError on non-ASCII
        # str, which would turn an accented password -- or a hostile header -- into
        # a 500 with a traceback instead of a 401.
        self._username = username.encode("utf-8")
        self._password = password.encode("utf-8")
        self._realm = realm.replace('"', "")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # "lifespan" must pass through or startup hangs. There are no websocket
        # routes today; adding one means revisiting this line.
        if not self.enabled or scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        header = ""
        for key, value in scope["headers"]:
            if key == b"authorization":
                header = value.decode("latin-1")
                break

        credentials = parse_basic_credentials(header) if header else None
        if credentials is None:
            await self._challenge(scope, receive, send)
            return

        user, password = credentials
        # Both comparisons always run. `and` would short-circuit and leak, through
        # timing, whether the username alone was correct.
        user_ok = secrets.compare_digest(user, self._username)
        password_ok = secrets.compare_digest(password, self._password)
        if not (user_ok & password_ok):
            await self._challenge(scope, receive, send)
            return

        await self.app(scope, receive, send)

    async def _challenge(self, scope: Scope, receive: Receive, send: Send) -> None:
        # The WWW-Authenticate header is not optional politeness: the browser must
        # be challenged so it caches the credential for the origin and replays it on
        # the EventSource run stream, which cannot set an Authorization header.
        response = PlainTextResponse(
            "Unauthorized",
            status_code=401,
            headers={"WWW-Authenticate": f'Basic realm="{self._realm}", charset="UTF-8"'},
        )
        await response(scope, receive, send)
