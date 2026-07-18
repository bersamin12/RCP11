"""Source connectors for OpenAlex and Semantic Scholar (PRD M1.2)."""

import time

import httpx

from rcp.config import get_settings

OPENALEX = "https://api.openalex.org/works"
S2 = "https://api.semanticscholar.org/graph/v1/paper/search"


def _reconstruct_abstract(inverted: dict[str, list[int]] | None) -> str:
    if not inverted:
        return ""
    positions: dict[int, str] = {}
    for word, idxs in inverted.items():
        for i in idxs:
            positions[i] = word
    return " ".join(positions[i] for i in sorted(positions))


def search_openalex(query: str, per_page: int = 15) -> list[dict]:
    params: dict = {"search": query, "per-page": per_page}  # default sort = relevance
    if get_settings().rcp_mailto:
        params["mailto"] = get_settings().rcp_mailto
    try:
        resp = httpx.get(OPENALEX, params=params, timeout=30)
        resp.raise_for_status()
    except httpx.HTTPError:
        return []
    papers = []
    for w in resp.json().get("results", []):
        papers.append(
            {
                "source": "openalex",
                "id": w.get("id", ""),
                "title": w.get("title") or "",
                "doi": (w.get("doi") or "").replace("https://doi.org/", "") or None,
                "year": w.get("publication_year"),
                "abstract": _reconstruct_abstract(w.get("abstract_inverted_index")),
                "authors": [a["author"]["display_name"] for a in w.get("authorships", [])[:8]],
                "venue": ((w.get("primary_location") or {}).get("source") or {}).get("display_name"),
                "citations": w.get("cited_by_count", 0),
                "url": w.get("id"),
            }
        )
    return papers


def search_semantic_scholar(query: str, limit: int = 15) -> list[dict]:
    params = {
        "query": query,
        "limit": limit,
        "fields": "title,abstract,year,externalIds,authors,venue,citationCount,url",
    }
    for attempt in range(2):
        try:
            resp = httpx.get(S2, params=params, timeout=30)
            if resp.status_code == 429:  # unauthenticated rate limit
                time.sleep(5 * (attempt + 1))
                continue
            resp.raise_for_status()
            break
        except httpx.HTTPError:
            return []
    else:
        return []
    papers = []
    for p in resp.json().get("data", []):
        papers.append(
            {
                "source": "semantic_scholar",
                "id": p.get("paperId", ""),
                "title": p.get("title") or "",
                "doi": (p.get("externalIds") or {}).get("DOI"),
                "year": p.get("year"),
                "abstract": p.get("abstract") or "",
                "authors": [a["name"] for a in p.get("authors", [])[:8]],
                "venue": p.get("venue"),
                "citations": p.get("citationCount", 0),
                "url": p.get("url"),
            }
        )
    return papers
