"""PaperCard extractor: problem, method, metrics, limitations per paper (PRD M1.4)."""

from pydantic import BaseModel, Field

from rcp.llm import llm_json
from rcp.objects import PaperCard


class RelevanceScreen(BaseModel):
    relevant_indices: list[int]


def screen_relevant(papers: list[dict], topic: str, limit: int = 40) -> list[dict]:
    """Drop papers whose titles are off-topic before spending tokens on extraction."""
    candidates = papers[:limit]
    listing = "\n".join(f"[{i}] {p['title']}" for i, p in enumerate(candidates))
    try:
        screen = llm_json(
            f"Research topic: {topic}\n\nCandidate papers:\n{listing}\n\n"
            "Return the indices of papers directly relevant to the research topic. "
            "Exclude papers from unrelated fields even if they share keywords.",
            RelevanceScreen,
            system="You are a strict relevance filter for a literature search.",
        )
        keep = [candidates[i] for i in screen.relevant_indices if 0 <= i < len(candidates)]
        return keep or candidates
    except RuntimeError:
        return candidates


class CardFields(BaseModel):
    problem: str
    method: str
    metrics: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


def extract_card(paper: dict, topic: str) -> PaperCard:
    fields = llm_json(
        f"Research topic under study: {topic}\n\n"
        f"Paper title: {paper['title']}\n"
        f"Venue: {paper.get('venue') or 'unknown'} ({paper.get('year') or '?'})\n"
        f"Abstract: {paper.get('abstract') or '(no abstract available — infer from title only)'}\n\n"
        "Extract a structured paper card: the problem addressed, the method (including "
        "mathematical models if identifiable), the evaluation metrics used, stated or likely "
        "limitations, and 3-6 short topical tags.",
        CardFields,
        system="You extract structured knowledge from research papers for a scientific knowledge base.",
    )
    return PaperCard(
        id=paper.get("id") or paper["title"][:60],
        title=paper["title"],
        year=paper.get("year"),
        doi=paper.get("doi"),
        url=paper.get("url"),
        venue=paper.get("venue"),
        authors=paper.get("authors", []),
        citations=paper.get("citations", 0),
        abstract=paper.get("abstract", ""),
        **fields.model_dump(),
    )
