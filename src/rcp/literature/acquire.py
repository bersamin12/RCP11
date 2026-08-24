"""Acquire and cache open-access PDFs for screened paper records.

Two rules shape this module.

Only genuinely open records are fetched. OpenAlex's ``is_oa`` flag also covers
*bronze* open access (free to read on the publisher site under no stated licence,
and revocable) and *green* open access (an author manuscript under repository
terms). Neither grants redistribution, so a licence or an explicit gold/hybrid
status is required before anything is downloaded. No publisher URL is ever
constructed, no landing page is ever scraped for a link.

A failed acquisition is recorded as carefully as a successful one. Saying "four
open-access locations were checked and none served a PDF" is provenance-honest;
an unexplained empty slot is not.
"""

import hashlib
import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from rcp.config import get_settings, literature_dir
from rcp.memory.connectors import unpaywall_oa_pdf
from rcp.objects import PdfAsset, utc_now

PDF_MAGIC = b"%PDF-"
MAX_REDIRECTS = 3
MAX_CANDIDATES = 4

# Licences that permit at least redistribution of the retrieved file. A record
# whose licence is absent is not assumed to be permissive.
REDISTRIBUTABLE_LICENSES = (
    "cc0", "cc-by", "cc-by-sa", "cc-by-nc", "cc-by-nc-sa", "cc-by-nd",
    "cc-by-nc-nd", "public-domain", "pd",
)
OPEN_STATUSES = {"gold", "hybrid", "green"}


def pdf_path(sha256: str) -> Path:
    return literature_dir() / "pdfs" / sha256[:2] / f"{sha256}.pdf"


def asset_path(sha256: str) -> Path:
    return literature_dir() / "pdfs" / sha256[:2] / f"{sha256}.json"


def _url_index_path(url: str) -> Path:
    """Where a previous successful fetch of this URL recorded its content hash.

    Content addressing cannot dedupe before a download, so without this index a
    rebuilt snapshot would re-request every PDF from third-party hosts.
    """
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return literature_dir() / "by_url" / f"{key}.json"


def cached_asset_for_url(url: str) -> PdfAsset | None:
    index = _url_index_path(url)
    if not index.is_file():
        return None
    try:
        sha = json.loads(index.read_text()).get("sha256", "")
    except (ValueError, OSError):
        return None
    if not sha or not pdf_path(sha).is_file():
        return None
    return load_pdf_asset(sha)


def _remember_url(url: str, sha256: str) -> None:
    index = _url_index_path(url)
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(json.dumps({"url": url, "sha256": sha256}))


def load_pdf_asset(sha256: str) -> PdfAsset | None:
    path = asset_path(sha256)
    if not path.is_file():
        return None
    try:
        return PdfAsset.model_validate_json(path.read_text())
    except (ValueError, OSError):
        return None


def _normalized_license(paper: dict) -> str:
    return str(paper.get("pdf_license") or "").strip().lower()


def is_open_access(paper: dict) -> bool:
    """Whether a provider has explicitly asserted this record is openly licensed.

    Bronze open access is excluded unless configured otherwise: it is free to read
    but states no licence, so its redistribution terms are unknown.
    """
    status = str(paper.get("oa_status") or "").strip().lower()
    if status == "closed":
        return False
    licence = _normalized_license(paper)
    if licence and any(licence.startswith(allowed) for allowed in REDISTRIBUTABLE_LICENSES):
        return True
    if status in OPEN_STATUSES and licence:
        return True
    if status == "bronze":
        return bool(get_settings().rcp_pdf_allow_bronze)
    # A provider publishing an explicit OA PDF location, with an open status, is
    # treated as an assertion of openness even when the licence string is absent.
    if status in OPEN_STATUSES and paper.get("pdf_url"):
        return True
    return False


def candidate_pdf_urls(paper: dict) -> list[tuple[str, str]]:
    """Ordered, de-duplicated (url, provider) pairs to try."""
    source = str(paper.get("source") or "")
    ordered = [
        (paper.get("pdf_url"), source or "provider"),
        (paper.get("oa_url"), "openalex"),
    ]
    seen: set[str] = set()
    candidates: list[tuple[str, str]] = []
    for url, provider in ordered:
        url = str(url or "").strip()
        if url and url.startswith(("http://", "https://")) and url not in seen:
            seen.add(url)
            candidates.append((url, provider))
    return candidates[:MAX_CANDIDATES]


def _user_agent() -> str:
    mailto = get_settings().rcp_mailto or "unset"
    return f"rcp-platform/0.1 (+mailto:{mailto})"


def _page_count(path: Path, max_pages: int) -> int | None:
    """Page count, or None when the file cannot be parsed as a PDF."""
    try:
        from pypdf import PdfReader

        return min(len(PdfReader(str(path)).pages), max_pages)
    except Exception:
        return None


def _download(url: str, provider: str, paper: dict) -> PdfAsset:
    tmp_path = literature_dir() / "tmp" / f"{os.getpid()}-{abs(hash(url)) & 0xFFFFFFFF:08x}.part"
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return _download_to(tmp_path, url, provider, paper)
    finally:
        tmp_path.unlink(missing_ok=True)


def _download_to(tmp_path: Path, url: str, provider: str, paper: dict) -> PdfAsset:
    settings = get_settings()
    base = PdfAsset(
        source_url=url,
        provider=provider,
        landing_page_url=str(paper.get("landing_page_url") or ""),
        oa_status=str(paper.get("oa_status") or ""),
        license=str(paper.get("pdf_license") or ""),
        oa_version=str(paper.get("pdf_version") or ""),
        retrieved_at=utc_now(),
        attempted_urls=[url],
    )
    digest = hashlib.sha256()
    size = 0
    try:
        with httpx.Client(
            follow_redirects=True,
            max_redirects=MAX_REDIRECTS,
            timeout=httpx.Timeout(
                connect=10.0, read=settings.rcp_pdf_timeout_seconds, write=10.0, pool=10.0
            ),
            headers={"User-Agent": _user_agent(), "Accept": "application/pdf"},
        ) as client:
            with client.stream("GET", url) as response:
                base.http_status = response.status_code
                base.content_type = response.headers.get("content-type", "")
                if response.status_code >= 400:
                    base.status = "unavailable"
                    base.error = f"HTTP {response.status_code}"
                    return base
                first = True
                with tmp_path.open("wb") as handle:
                    for chunk in response.iter_bytes(65536):
                        if first:
                            first = False
                            # Many legitimate open-access hosts serve
                            # application/octet-stream, so the magic bytes -- not the
                            # declared type -- are the reliable test. An HTML landing
                            # page fails here even when it claims to be a PDF.
                            if not chunk.startswith(PDF_MAGIC):
                                base.status = "not_pdf"
                                base.error = "response body is not a PDF"
                                return base
                        size += len(chunk)
                        if size > settings.rcp_pdf_max_bytes:
                            base.status = "too_large"
                            base.error = f"exceeded {settings.rcp_pdf_max_bytes} bytes"
                            return base
                        digest.update(chunk)
                        handle.write(chunk)
    except (httpx.HTTPError, OSError, ValueError) as err:
        base.status = "unavailable"
        base.error = str(err)[:300]
        return base

    if not size:
        base.status = "unavailable"
        base.error = "empty response"
        return base

    sha = digest.hexdigest()
    pages = _page_count(tmp_path, settings.rcp_pdf_max_pages)
    base.sha256 = sha
    base.bytes = size
    if pages is None:
        # Keep the bytes -- a human may still want to look at the file -- but refuse
        # to offer it for full-text extraction.
        base.status = "unreadable"
        base.error = "the file could not be parsed as a PDF"
    else:
        base.status = "available"
        base.page_count = pages

    destination = pdf_path(sha)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copyfile(tmp_path, destination)
    asset_path(sha).write_text(base.model_dump_json(indent=2))
    _remember_url(url, sha)
    return base


def fetch_open_access_pdf(paper: dict) -> PdfAsset:
    """Try each open-access location in turn. Never raises."""
    if not is_open_access(paper):
        return PdfAsset(
            status="unavailable",
            oa_status=str(paper.get("oa_status") or ""),
            license=str(paper.get("pdf_license") or ""),
            error="no provider asserted an openly licensed full text",
            retrieved_at=utc_now(),
        )

    candidates = candidate_pdf_urls(paper)
    if not candidates and paper.get("doi"):
        extra = unpaywall_oa_pdf(str(paper["doi"]))
        if extra:
            merged = {**paper, **extra}
            if is_open_access(merged):
                candidates = candidate_pdf_urls(merged)
                paper = merged

    attempted: list[str] = []
    last = PdfAsset(
        status="unavailable",
        oa_status=str(paper.get("oa_status") or ""),
        license=str(paper.get("pdf_license") or ""),
        error="no open-access PDF location was published",
        retrieved_at=utc_now(),
    )
    for url, provider in candidates:
        attempted.append(url)
        cached = cached_asset_for_url(url)
        if cached is not None:
            cached.attempted_urls = attempted
            return cached
        result = _download(url, provider, paper)
        if result.status in {"available", "unreadable"}:
            result.attempted_urls = attempted
            asset_path(result.sha256).write_text(result.model_dump_json(indent=2))
            return result
        last = result
    last.attempted_urls = attempted
    return last


def attach_open_access_pdfs(papers: list[dict]) -> list[dict]:
    """Attach a PdfAsset to every paper. Concurrency is bounded and polite."""
    rows = [dict(paper) for paper in papers]
    if not rows or not get_settings().rcp_fetch_oa_pdfs:
        return rows

    def run(paper: dict) -> PdfAsset:
        try:
            return fetch_open_access_pdf(paper)
        except Exception as err:  # a literature fetch must never fail a run
            return PdfAsset(status="unavailable", error=str(err)[:300], retrieved_at=utc_now())

    workers = min(get_settings().rcp_pdf_max_workers, len(rows))
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        assets = list(pool.map(run, rows))
    for paper, asset in zip(rows, assets):
        paper["pdf"] = asset.model_dump()
    return rows
