"""HTTP Basic auth for the exposed deployment.

The middleware is a plain ASGI app, so these tests wrap it around a small stand-in
that exercises exactly the three response shapes it must not disturb: a JSON route,
a StreamingResponse (the run event stream) and a FileResponse (range-served PDFs).
That is faster and far more direct than reloading the real app, and it keeps the
tests honest about what is actually being checked.
"""

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.testclient import TestClient

from rcp.api.auth import BasicAuthMiddleware

USER = "rcp"
PASSWORD = "correct-horse-battery-staple"
CREDENTIALS = (USER, PASSWORD)


@pytest.fixture()
def inner(tmp_path):
    api = FastAPI()
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.7\n" + b"x" * 1000)

    @api.get("/api/ping")
    def ping():
        return {"ok": True}

    @api.get("/api/stream")
    async def stream():
        async def gen():
            for index in range(3):
                yield f"data: {index}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    @api.get("/api/pdf")
    def get_pdf():
        return FileResponse(pdf, media_type="application/pdf")

    return api


def client(inner, password: str = PASSWORD, user: str = USER) -> TestClient:
    return TestClient(BasicAuthMiddleware(inner, username=user, password=password))


def test_an_empty_password_disables_the_check(inner):
    """The default. This is what keeps CI and local development unchanged."""
    assert client(inner, password="").get("/api/ping").status_code == 200


def test_the_challenge_carries_www_authenticate(inner):
    # Without this header the browser never prompts and never caches the
    # credential, so the EventSource run stream can never authenticate.
    response = client(inner).get("/api/ping")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith('Basic realm="')


def test_correct_credentials_pass_through(inner):
    assert client(inner).get("/api/ping", auth=CREDENTIALS).status_code == 200


@pytest.mark.parametrize(
    "credentials", [(USER, "wrong"), ("wrong", PASSWORD), ("wrong", "wrong")]
)
def test_a_wrong_user_and_a_wrong_password_are_indistinguishable(inner, credentials):
    response = client(inner).get("/api/ping", auth=credentials)
    assert response.status_code == 401
    assert response.text == "Unauthorized"


@pytest.mark.parametrize(
    "header",
    [
        "",
        "Basic",
        "Basic ",
        "Basic !!!!",           # not base64 at all
        "Basic bm9jb2xvbg==",   # valid base64, decodes to "nocolon"
        "Bearer abc",           # wrong scheme
        "Basic ****",
    ],
)
def test_a_malformed_header_is_401_and_never_500(inner, header):
    assert client(inner).get("/api/ping", headers={"Authorization": header}).status_code == 401


def test_the_scheme_is_case_insensitive(inner):
    import base64

    encoded = base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
    response = client(inner).get("/api/ping", headers={"Authorization": f"bAsIc {encoded}"})
    assert response.status_code == 200


def test_a_password_containing_a_colon_survives(inner):
    # partition() rather than split() -- a colon in the password must not truncate it.
    secret = "a:b:c-and-more"
    assert client(inner, password=secret).get("/api/ping", auth=(USER, secret)).status_code == 200


def test_a_non_ascii_password_does_not_500(inner):
    # secrets.compare_digest raises TypeError on non-ASCII str; we compare bytes.
    secret = "pässwörd-with-ümlauts"
    authorized = client(inner, password=secret)
    assert authorized.get("/api/ping", auth=(USER, secret)).status_code == 200
    assert authorized.get("/api/ping", auth=(USER, "wrong")).status_code == 401


def test_sse_still_streams_under_auth(inner):
    """Invariant 3: the middleware must not disturb a StreamingResponse."""
    with client(inner).stream("GET", "/api/stream", auth=CREDENTIALS) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "data: 2" in "".join(response.iter_text())


def test_range_requests_still_return_206_under_auth(inner):
    """Invariant 3: pdf.js depends on FileResponse's 206 and Content-Range."""
    response = client(inner).get(
        "/api/pdf", auth=CREDENTIALS, headers={"Range": "bytes=0-7"}
    )
    assert response.status_code == 206
    assert response.headers["Content-Range"] == "bytes 0-7/1009"
    assert response.content == b"%PDF-1.7"


def test_auth_is_registered_inside_cors():
    """Starlette's add_middleware inserts at index 0, so a LOWER index is further out.

    CORS has to stay outside auth: a preflight OPTIONS never carries an
    Authorization header, so auth-outermost would 401 every cross-origin request
    before CORSMiddleware could answer it, and strip the CORS headers off the 401
    as well -- surfacing in the browser as an opaque network error.
    """
    import rcp.api.main as api_main

    classes = [middleware.cls for middleware in api_main.app.user_middleware]
    assert classes.index(CORSMiddleware) < classes.index(BasicAuthMiddleware)


@pytest.fixture()
def guarded_app(tmp_path, monkeypatch):
    """The real app, reloaded with auth configured.

    Restores an unauthenticated module afterwards: `rcp.api.main` is a module-level
    singleton and later test modules import it, so leaving auth switched on here
    would leak into them.
    """
    import importlib

    import rcp.api.main as api_main
    from rcp.config import get_settings

    monkeypatch.setenv("RCP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RCP_AUTH_PASSWORD", PASSWORD)
    monkeypatch.setenv("RCP_AUTH_USER", USER)
    get_settings.cache_clear()
    importlib.reload(api_main)
    yield TestClient(api_main.app)

    monkeypatch.undo()
    get_settings.cache_clear()
    importlib.reload(api_main)


def test_the_real_app_protects_the_api_and_the_spa(guarded_app):
    for path in ("/api/health", "/"):
        response = guarded_app.get(path)
        assert response.status_code == 401, path
        assert "WWW-Authenticate" in response.headers, path

    # /api/health is deliberately not exempted: it returns NODE_ORDER and
    # checkpoint-store internals, and nothing external probes it.
    assert guarded_app.get("/api/health", auth=CREDENTIALS).status_code == 200


def test_the_interactive_docs_are_withdrawn_when_auth_is_on(guarded_app):
    for path in ("/openapi.json", "/docs"):
        # The catch-all SPA mount answers unknown paths, so the assertion is that
        # it is no longer the schema -- not that the path 404s.
        response = guarded_app.get(path, auth=CREDENTIALS)
        assert "openapi" not in response.text[:200].lower(), path


def test_a_preflight_is_answered_while_auth_is_enabled(inner):
    """The behavioural half of the ordering test above."""
    guarded = FastAPI()

    @guarded.get("/api/ping")
    def ping():
        return {"ok": True}

    guarded.add_middleware(
        BasicAuthMiddleware, username=USER, password=PASSWORD, realm="test"
    )
    guarded.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    probe = TestClient(guarded)

    preflight = probe.options(
        "/api/ping",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:5173"

    # And an unauthenticated GET still carries CORS headers, so the browser can
    # read the real 401 rather than reporting a generic failure.
    denied = probe.get("/api/ping", headers={"Origin": "http://localhost:5173"})
    assert denied.status_code == 401
    assert denied.headers["access-control-allow-origin"] == "http://localhost:5173"
