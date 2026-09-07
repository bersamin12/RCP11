"""Literature retrieval for the Generation / Reflection / Evolution agents.

Methods, Generation agent: "Literature exploration via web search. The agent iteratively searches
the web, retrieves and reads relevant research articles ... and grounds its reasoning by
summarizing prior work."

We use Semantic Scholar's public graph API first (no key, heavily rate limited) and fall back to
OpenAlex — the same two sources the RCP platform's Research Memory uses. If both fail the caller
gets an empty list and the agents run *without* grounding, which is reported in the notebook.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

S2_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
OPENALEX_URL = "https://api.openalex.org/works"
MAILTO = "rcp-platform-notebooks@example.org"   # OpenAlex polite pool


@dataclass
class Article:
    title: str
    year: int | None
    abstract: str
    venue: str = ""
    citations: int = 0
    source: str = ""
    url: str = ""

    def block(self, max_abstract: int = 900) -> str:
        a = (self.abstract or "").strip().replace("\n", " ")
        if len(a) > max_abstract:
            a = a[:max_abstract] + " …"
        return f"- {self.title} ({self.year or 'n.d.'}, {self.venue or self.source}; {self.citations} citations)\n  {a or '(no abstract available)'}"


def _s2(query: str, limit: int, tries: int, pause: float, timeout: float) -> list[Article]:
    import requests

    for attempt in range(tries):
        try:
            r = requests.get(
                S2_URL,
                params={"query": query, "limit": limit,
                        "fields": "title,abstract,year,venue,citationCount,externalIds"},
                timeout=timeout,
            )
        except Exception:
            return []
        if r.status_code == 200:
            out = []
            for p in r.json().get("data", []) or []:
                out.append(Article(p.get("title") or "", p.get("year"), p.get("abstract") or "",
                                   p.get("venue") or "", int(p.get("citationCount") or 0), "semanticscholar",
                                   "https://www.semanticscholar.org/paper/" + str(p.get("paperId", ""))))
            return out
        if r.status_code in (429, 503):          # rate limited: exponential backoff, then give up
            time.sleep(pause * (2 ** attempt))
            continue
        return []
    return []


def _openalex_abstract(inv: dict | None) -> str:
    if not inv:
        return ""
    pos: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        for i in idxs:
            pos.append((i, word))
    return " ".join(w for _, w in sorted(pos))


def _openalex(query: str, limit: int, timeout: float) -> list[Article]:
    import requests

    try:
        r = requests.get(OPENALEX_URL,
                         params={"search": query, "per-page": limit, "mailto": MAILTO},
                         timeout=timeout)
        if r.status_code != 200:
            return []
        out = []
        for w in r.json().get("results", []) or []:
            loc = (w.get("primary_location") or {}).get("source") or {}
            out.append(Article(w.get("display_name") or "", w.get("publication_year"),
                               _openalex_abstract(w.get("abstract_inverted_index")),
                               loc.get("display_name") or "", int(w.get("cited_by_count") or 0),
                               "openalex", w.get("doi") or w.get("id") or ""))
        return out
    except Exception:
        return []


def search(query: str, limit: int = 5, *, tries: int = 3, pause: float = 2.0,
           timeout: float = 25.0, prefer: str = "s2") -> list[Article]:
    """Search one query; Semantic Scholar with backoff, then OpenAlex, then [] (degraded mode)."""
    arts: list[Article] = []
    if prefer == "s2":
        arts = _s2(query, limit, tries, pause, timeout)
    if not arts:
        arts = _openalex(query, limit, timeout)
    return [a for a in arts if a.title][:limit]


def search_many(queries: list[str], limit: int = 4, workers: int = 4, **kw) -> list[Article]:
    """Run several queries in parallel and de-duplicate by title."""
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(lambda q: search(q, limit, **kw), queries))
    seen, out = set(), []
    for group in results:
        for a in group:
            key = a.title.lower().strip()
            if key not in seen:
                seen.add(key)
                out.append(a)
    return out


def bibliography(arts: list[Article], max_abstract: int = 900) -> str:
    if not arts:
        return "(literature retrieval unavailable — reason from established engineering knowledge instead)"
    return "\n".join(a.block(max_abstract) for a in arts)
