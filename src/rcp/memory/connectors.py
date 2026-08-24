"""Source connectors for OpenAlex and Semantic Scholar (PRD M1.2)."""

import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from rcp.config import get_settings

OPENALEX = "https://api.openalex.org/works"
OPENALEX_BY_DOI = "https://api.openalex.org/works"
CROSSREF = "https://api.crossref.org/works"
S2 = "https://api.semanticscholar.org/graph/v1/paper/search"
UNPAYWALL = "https://api.unpaywall.org/v2"


def _reconstruct_abstract(inverted: dict[str, list[int]] | None) -> str:
    if not inverted:
        return ""
    positions: dict[int, str] = {}
    for word, idxs in inverted.items():
        for i in idxs:
            positions[i] = word
    return " ".join(positions[i] for i in sorted(positions))


def _openalex_oa_fields(work: dict) -> dict:
    """Open-access location fields OpenAlex already returns in every work object.

    `is_oa` alone is not permission: it also covers bronze (free to read, licence
    unstated) and green (author manuscript under repository terms). The licence and
    status are captured alongside it so the fetcher can decide honestly.
    """
    access = work.get("open_access") or {}
    best = work.get("best_oa_location") or {}
    return {
        "is_oa": access.get("is_oa"),
        "oa_status": access.get("oa_status"),
        "oa_url": access.get("oa_url"),
        "pdf_url": best.get("pdf_url"),
        "pdf_license": best.get("license"),
        "pdf_version": best.get("version"),
        "landing_page_url": best.get("landing_page_url"),
    }


def search_openalex(query: str, per_page: int = 15) -> list[dict]:
    params: dict = {"search": query, "per-page": per_page}  # default sort = relevance
    if get_settings().rcp_mailto:
        params["mailto"] = get_settings().rcp_mailto
    try:
        resp = httpx.get(OPENALEX, params=params, timeout=30)
        resp.raise_for_status()
    except (httpx.HTTPError, ValueError):
        return []
    papers = []
    for w in resp.json().get("results", []):
        papers.append(
            {
                "source": "openalex",
                "provenance": ["openalex"],
                "id": w.get("id", ""),
                "title": w.get("title") or "",
                "doi": (w.get("doi") or "").replace("https://doi.org/", "") or None,
                "year": w.get("publication_year"),
                "abstract": _reconstruct_abstract(w.get("abstract_inverted_index")),
                "authors": [a["author"]["display_name"] for a in w.get("authorships", [])[:8]],
                "venue": ((w.get("primary_location") or {}).get("source") or {}).get("display_name"),
                "citations": w.get("cited_by_count", 0),
                "url": w.get("id"),
                "publication_type": w.get("type") or "unknown",
                **_openalex_oa_fields(w),
            }
        )
    return papers


def search_semantic_scholar(query: str, limit: int = 15) -> list[dict]:
    params = {
        "query": query,
        "limit": limit,
        "fields": (
            "title,abstract,year,externalIds,authors,venue,citationCount,url,"
            "isOpenAccess,openAccessPdf"
        ),
    }
    for attempt in range(2):
        try:
            resp = httpx.get(S2, params=params, timeout=30)
            if resp.status_code == 429:  # unauthenticated rate limit
                time.sleep(5 * (attempt + 1))
                continue
            resp.raise_for_status()
            break
        except (httpx.HTTPError, ValueError):
            return []
    else:
        return []
    papers = []
    for p in resp.json().get("data", []):
        open_pdf = p.get("openAccessPdf") or {}
        papers.append(
            {
                "source": "semantic_scholar",
                "provenance": ["semantic_scholar"],
                "id": p.get("paperId", ""),
                "title": p.get("title") or "",
                "doi": (p.get("externalIds") or {}).get("DOI"),
                "year": p.get("year"),
                "abstract": p.get("abstract") or "",
                "authors": [a["name"] for a in p.get("authors", [])[:8]],
                "venue": p.get("venue"),
                "citations": p.get("citationCount", 0),
                "url": p.get("url"),
                "is_oa": p.get("isOpenAccess"),
                "oa_status": open_pdf.get("status"),
                "pdf_url": open_pdf.get("url"),
                "pdf_license": open_pdf.get("license"),
            }
        )
    return papers


def enrich_doi_metadata(papers: list[dict], limit: int = 20) -> list[dict]:
    """Add publication metadata for DOI-bearing records.

    OpenAlex enrichment is batched and Crossref DOI lookups run concurrently so
    high-confidence records can be corroborated across providers. Provider
    failures degrade to the original records rather than failing a run.
    """
    rows = [dict(p) for p in papers]
    doi_rows = [p for p in rows if p.get("doi")][:limit]
    if not doi_rows:
        return rows

    dois = [str(p["doi"]).lower().replace("https://doi.org/", "") for p in doi_rows]
    oa_by_doi: dict[str, dict] = {}
    try:
        params = {"filter": "doi:" + "|".join(dois), "per-page": len(dois)}
        if get_settings().rcp_mailto:
            params["mailto"] = get_settings().rcp_mailto
        resp = httpx.get(OPENALEX_BY_DOI, params=params, timeout=30)
        resp.raise_for_status()
        for work in resp.json().get("results", []):
            doi = (work.get("doi") or "").lower().replace("https://doi.org/", "")
            if doi:
                oa_by_doi[doi] = work
    except (httpx.HTTPError, ValueError):
        pass

    crossref_needed: list[tuple[dict, str]] = []
    for paper in doi_rows:
        doi = str(paper["doi"]).lower().replace("https://doi.org/", "")
        work = oa_by_doi.get(doi)
        if work:
            paper["publication_type"] = work.get("type") or paper.get("publication_type")
            paper["venue"] = paper.get("venue") or (
                ((work.get("primary_location") or {}).get("source") or {}).get("display_name")
            )
            paper["citations"] = max(paper.get("citations") or 0, work.get("cited_by_count") or 0)
            # Prefer OpenAlex's open-access locations, but never discard one a
            # search provider already supplied.
            for key, value in _openalex_oa_fields(work).items():
                if value or not paper.get(key):
                    paper[key] = value
            paper["provenance"] = list(dict.fromkeys((paper.get("provenance") or []) + ["openalex-doi"]))

        crossref_needed.append((paper, doi))

    def fetch_crossref(item: tuple[dict, str]) -> tuple[dict, dict | None]:
        paper, doi = item
        try:
            resp = httpx.get(f"{CROSSREF}/{doi}", timeout=8)
            resp.raise_for_status()
            message = resp.json().get("message", {})
        except (httpx.HTTPError, ValueError):
            return paper, None
        return paper, message

    with ThreadPoolExecutor(max_workers=min(8, len(crossref_needed) or 1)) as pool:
        crossref_results = list(pool.map(fetch_crossref, crossref_needed))
    for paper, message in crossref_results:
        if not message:
            continue
        paper["publication_type"] = message.get("type") or paper.get("publication_type") or "unknown"
        containers = message.get("container-title") or []
        paper["venue"] = paper.get("venue") or (containers[0] if containers else None)
        paper["publisher"] = message.get("publisher")
        paper["provenance"] = list(dict.fromkeys((paper.get("provenance") or []) + ["crossref"]))
    return rows


def unpaywall_oa_pdf(doi: str) -> dict | None:
    """Last-resort open-access lookup for a DOI-bearing record.

    Unpaywall requires a contact address in every request. Without one configured
    we decline to call it at all rather than identify ourselves as nobody.
    """
    settings = get_settings()
    if not settings.rcp_unpaywall_enabled or not settings.rcp_mailto or not doi:
        return None
    try:
        resp = httpx.get(
            f"{UNPAYWALL}/{doi}", params={"email": settings.rcp_mailto}, timeout=8
        )
        resp.raise_for_status()
        best = resp.json().get("best_oa_location") or {}
    except (httpx.HTTPError, ValueError):
        return None
    if not best.get("url_for_pdf"):
        return None
    return {
        "pdf_url": best.get("url_for_pdf"),
        "oa_status": (best.get("host_type") or ""),
        "pdf_license": best.get("license"),
        "pdf_version": best.get("version"),
        "landing_page_url": best.get("url_for_landing_page"),
        "provider": "unpaywall",
    }
