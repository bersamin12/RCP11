"""Session-wide test setup.

At the repository root rather than in `tests/` on purpose: pytest inserts the
directory holding the *rootmost* conftest into `sys.path`, and several test
modules do `from tests.pdf_fixture import make_pdf`. With this file in `tests/`
only that directory would be added, and `.venv/bin/pytest` would still fail
collection with `ModuleNotFoundError: No module named 'tests'`.
"""

import pytest


@pytest.fixture(autouse=True)
def _auth_disabled_by_default(monkeypatch):
    """Neutralise a real `.env` password for every test.

    `rcp.config.Settings` reads the repo-root `.env`, so once a deployment
    password is configured there the Basic auth middleware switches on and every
    unauthenticated `TestClient` call in `tests/test_api.py` gets a 401 instead
    of JSON. CI has no `.env` and never saw this; the machine actually serving
    the platform does. Tests that need auth *on* (`tests/test_auth.py`) set the
    variable themselves -- an explicitly requested fixture is set up after the
    autouse one, so their value wins.
    """
    monkeypatch.setenv("RCP_AUTH_PASSWORD", "")

    from rcp.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
