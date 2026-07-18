"""Dedup & normalize raw papers by DOI, falling back to normalized title (PRD M1.3)."""

import re


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", title.lower()).strip()


def dedupe(papers: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for p in papers:
        if not p.get("title"):
            continue
        key = (p.get("doi") or "").lower() or normalize_title(p["title"])
        if key in merged:
            existing = merged[key]
            # Fill gaps and keep the larger citation count.
            for field, value in p.items():
                if value and not existing.get(field):
                    existing[field] = value
            existing["citations"] = max(existing.get("citations", 0), p.get("citations", 0))
        else:
            merged[key] = dict(p)
    # Preserve first-seen (relevance) order — sorting by citations here would
    # surface highly-cited but off-topic papers.
    return list(merged.values())
