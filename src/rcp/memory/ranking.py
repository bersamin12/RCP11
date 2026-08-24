"""Deterministic, disclosure-first literature quality ranking."""

import math
import re
from datetime import datetime, timezone


PREPRINT_MARKERS = {"preprint", "posted-content", "arxiv", "ssrn", "biorxiv", "medrxiv"}
PEER_REVIEWED_TYPES = {"article", "journal-article", "book-chapter"}
LIKELY_REVIEWED_TYPES = {"proceedings-article", "conference-paper", "review"}


def _tokens(text: str) -> set[str]:
    return {
        word for word in re.findall(r"[a-z0-9]+", text.lower())
        if len(word) > 2 and word not in {"the", "and", "for", "with", "from", "into"}
    }


def classify_publication(paper: dict) -> tuple[str, str]:
    publication_type = str(paper.get("publication_type") or "unknown").lower()
    venue = str(paper.get("venue") or "").lower()
    combined = {publication_type, *(_tokens(venue) & PREPRINT_MARKERS)}
    provenance = set(paper.get("provenance") or [])
    if combined & PREPRINT_MARKERS:
        return "preprint", "Identified as a preprint or posted manuscript; peer review is not verified."
    if (
        publication_type in PEER_REVIEWED_TYPES and paper.get("doi") and venue
        and "crossref" in provenance and provenance & {"openalex", "openalex-doi"}
    ):
        return "verified", "Journal/book publication type, venue, and DOI were corroborated across Crossref and OpenAlex."
    if publication_type in PEER_REVIEWED_TYPES and paper.get("doi") and venue:
        return "likely", "Journal/book publication metadata and a DOI are present, but cross-provider corroboration is incomplete."
    if publication_type in LIKELY_REVIEWED_TYPES and venue:
        return "likely", "Proceedings or review venue metadata suggests editorial review, but review status is not guaranteed."
    if paper.get("doi") and venue:
        return "likely", "A DOI and named venue are present, but the publication type is inconclusive."
    return "uncertain", "Peer-review status could not be verified from the available provider metadata."


def rank_papers(papers: list[dict], topic: str) -> list[dict]:
    """Rank by relevance first, then credibility, completeness, impact, recency."""
    now = datetime.now(timezone.utc).year
    topic_tokens = _tokens(topic)
    impacts = []
    for paper in papers:
        age = max(1, now - int(paper.get("year") or now) + 1)
        impacts.append(math.log1p(max(0, int(paper.get("citations") or 0)) / age))
    max_impact = max(impacts, default=1.0) or 1.0

    ranked: list[dict] = []
    credibility_value = {"verified": 1.0, "likely": 0.72, "uncertain": 0.35, "preprint": 0.18}
    for index, paper in enumerate(papers):
        row = dict(paper)
        haystack = " ".join(
            [str(row.get("title") or ""), str(row.get("abstract") or ""), " ".join(row.get("tags") or [])]
        )
        words = _tokens(haystack)
        relevance = len(topic_tokens & words) / max(1, len(topic_tokens))
        # Search providers already order by relevance; retain a small deterministic prior.
        relevance = min(1.0, relevance * 1.6 + max(0.0, 0.12 - index * 0.003))
        confidence, explanation = classify_publication(row)
        completeness = sum(
            bool(row.get(field)) for field in ("doi", "venue", "year", "authors", "abstract")
        ) / 5
        impact = impacts[index] / max_impact if index < len(impacts) else 0.0
        year = int(row.get("year") or 0)
        recency = max(0.0, min(1.0, 1 - max(0, now - year) / 15)) if year else 0.0
        factors = {
            "relevance": round(relevance, 4),
            "credibility": credibility_value[confidence],
            "evidence_completeness": round(completeness, 4),
            "normalized_citation_impact": round(impact, 4),
            "recency": round(recency, 4),
        }
        row["peer_review_confidence"] = confidence
        row["credibility_explanation"] = explanation
        row["ranking_factors"] = factors
        row["selection_score"] = round(
            100 * (
                0.50 * relevance
                + 0.20 * credibility_value[confidence]
                + 0.12 * completeness
                + 0.10 * impact
                + 0.08 * recency
            ),
            2,
        )
        ranked.append(row)
    return sorted(
        ranked,
        key=lambda p: (-p["selection_score"], str(p.get("title") or "").lower(), str(p.get("id") or "")),
    )
