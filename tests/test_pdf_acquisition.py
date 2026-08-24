import hashlib

import httpx
import pytest

from rcp.literature import acquire
from rcp.literature.acquire import (
    attach_open_access_pdfs,
    candidate_pdf_urls,
    fetch_open_access_pdf,
    is_open_access,
    pdf_path,
)
from tests.pdf_fixture import make_pdf

MINIMAL_PDF = make_pdf()
# Structurally a PDF (right magic bytes) but not parseable -- the case that must be
# kept on disk for a human while being refused for full-text extraction.
CORRUPT_PDF = b"%PDF-1.4\nthis file is truncated and has no xref table\n"

GOLD = {
    "source": "openalex",
    "doi": "10.1000/gold",
    "oa_status": "gold",
    "pdf_license": "cc-by",
    "pdf_url": "https://oa.example/paper.pdf",
}


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("RCP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RCP_MAILTO", "researcher@example.edu")
    from rcp.config import get_settings

    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def stub_transport(monkeypatch, handler):
    """Route every httpx.Client stream through a mock transport, counting calls."""
    calls: list[httpx.Request] = []

    def build(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    real_client = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(build)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(acquire.httpx, "Client", factory)
    return calls


# ---------- the licence gate: is_oa is not permission ----------

def test_closed_access_is_never_attempted(store, monkeypatch):
    calls = stub_transport(monkeypatch, lambda r: httpx.Response(200, content=MINIMAL_PDF))
    asset = fetch_open_access_pdf(
        {"source": "openalex", "oa_status": "closed", "is_oa": False,
         "pdf_url": "https://publisher.example/locked.pdf"}
    )
    assert asset.status == "unavailable"
    assert asset.attempted_urls == []
    assert calls == [], "a closed-access record must never be requested"


def test_bronze_requires_explicit_opt_in(store, monkeypatch):
    bronze = {"source": "openalex", "oa_status": "bronze", "pdf_url": "https://oa.example/b.pdf"}
    assert is_open_access(bronze) is False

    monkeypatch.setenv("RCP_PDF_ALLOW_BRONZE", "true")
    from rcp.config import get_settings

    get_settings.cache_clear()
    assert is_open_access(bronze) is True


def test_licensed_gold_record_is_open(store):
    assert is_open_access(GOLD) is True


def test_open_status_without_licence_still_needs_a_published_location(store):
    assert is_open_access({"oa_status": "gold"}) is False
    assert is_open_access({"oa_status": "gold", "pdf_url": "https://oa.example/x.pdf"}) is True


# ---------- fetch policy ----------

def test_html_landing_page_is_rejected_even_when_declared_as_pdf(store, monkeypatch):
    stub_transport(
        monkeypatch,
        lambda r: httpx.Response(
            200, content=b"<!doctype html><html>choose a download</html>",
            headers={"content-type": "application/pdf"},
        ),
    )
    asset = fetch_open_access_pdf(dict(GOLD))
    assert asset.status == "not_pdf"
    assert not list((store / "data" / "literature" / "pdfs").rglob("*.pdf"))


def test_octet_stream_is_accepted_when_the_magic_bytes_are_right(store, monkeypatch):
    stub_transport(
        monkeypatch,
        lambda r: httpx.Response(
            200, content=MINIMAL_PDF, headers={"content-type": "application/octet-stream"}
        ),
    )
    asset = fetch_open_access_pdf(dict(GOLD))
    assert asset.status == "available"
    assert asset.sha256 == hashlib.sha256(MINIMAL_PDF).hexdigest()
    assert pdf_path(asset.sha256).read_bytes() == MINIMAL_PDF


def test_unparseable_pdf_is_kept_but_marked_unreadable(store, monkeypatch):
    stub_transport(monkeypatch, lambda r: httpx.Response(200, content=CORRUPT_PDF))
    asset = fetch_open_access_pdf(dict(GOLD))
    assert asset.status == "unreadable"
    assert asset.page_count == 0
    # The bytes stay available for a human to open, but nothing may extract from them.
    assert pdf_path(asset.sha256).read_bytes() == CORRUPT_PDF


def test_oversized_download_is_abandoned(store, monkeypatch):
    monkeypatch.setenv("RCP_PDF_MAX_BYTES", "128")
    from rcp.config import get_settings

    get_settings.cache_clear()
    stub_transport(
        monkeypatch,
        lambda r: httpx.Response(200, content=MINIMAL_PDF + b"0" * 5000),
    )
    asset = fetch_open_access_pdf(dict(GOLD))
    assert asset.status == "too_large"
    assert not list((store / "data" / "literature" / "pdfs").rglob("*.pdf"))


@pytest.mark.parametrize("status", [403, 404, 410, 429, 500])
def test_http_errors_degrade_without_raising(store, monkeypatch, status):
    stub_transport(monkeypatch, lambda r: httpx.Response(status))
    asset = fetch_open_access_pdf(dict(GOLD))
    assert asset.status == "unavailable"
    assert asset.http_status == status


def test_timeout_degrades_without_raising(store, monkeypatch):
    def boom(request):
        raise httpx.ReadTimeout("too slow", request=request)

    stub_transport(monkeypatch, boom)
    asset = fetch_open_access_pdf(dict(GOLD))
    assert asset.status == "unavailable"
    assert asset.error


def test_candidate_urls_fall_back_in_order(store, monkeypatch):
    paper = {**GOLD, "pdf_url": "https://oa.example/broken.pdf",
             "oa_url": "https://repo.example/good.pdf"}
    assert [url for url, _ in candidate_pdf_urls(paper)] == [
        "https://oa.example/broken.pdf", "https://repo.example/good.pdf",
    ]

    def handler(request):
        if "broken" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(200, content=MINIMAL_PDF)

    stub_transport(monkeypatch, handler)
    asset = fetch_open_access_pdf(paper)
    assert asset.status == "available"
    assert asset.attempted_urls == [
        "https://oa.example/broken.pdf", "https://repo.example/good.pdf",
    ]


def test_refetching_the_same_url_does_not_touch_the_network_again(store, monkeypatch):
    calls = stub_transport(monkeypatch, lambda r: httpx.Response(200, content=MINIMAL_PDF))
    first = fetch_open_access_pdf(dict(GOLD))
    assert first.status == "available"
    assert len(calls) == 1

    second = fetch_open_access_pdf(dict(GOLD))
    assert second.sha256 == first.sha256
    assert len(calls) == 1, "a cached URL must not be requested from the host again"


def test_the_request_identifies_us_with_a_contact_address(store, monkeypatch):
    calls = stub_transport(monkeypatch, lambda r: httpx.Response(200, content=MINIMAL_PDF))
    fetch_open_access_pdf(dict(GOLD))
    assert "researcher@example.edu" in calls[0].headers["user-agent"]


def test_a_failed_fetch_records_why_rather_than_leaving_a_blank(store, monkeypatch):
    stub_transport(monkeypatch, lambda r: httpx.Response(404))
    asset = fetch_open_access_pdf(dict(GOLD))
    assert asset.error
    assert asset.attempted_urls == ["https://oa.example/paper.pdf"]
    assert asset.oa_status == "gold"


# ---------- batch behaviour ----------

def test_attach_preserves_every_paper_even_when_all_fetches_fail(store, monkeypatch):
    stub_transport(monkeypatch, lambda r: httpx.Response(404))
    papers = [dict(GOLD, doi=f"10.1000/{i}") for i in range(4)]
    rows = attach_open_access_pdfs(papers)
    assert len(rows) == 4
    assert all(row["pdf"]["status"] == "unavailable" for row in rows)


def test_fetching_is_skipped_entirely_when_disabled(store, monkeypatch):
    monkeypatch.setenv("RCP_FETCH_OA_PDFS", "false")
    from rcp.config import get_settings

    get_settings.cache_clear()
    calls = stub_transport(monkeypatch, lambda r: httpx.Response(200, content=MINIMAL_PDF))
    rows = attach_open_access_pdfs([dict(GOLD)])
    assert calls == []
    assert "pdf" not in rows[0]
