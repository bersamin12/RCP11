"""Evidence-bounded PaperCard extraction (PRD M1.4)."""

from typing import Literal

from pydantic import BaseModel, Field

from rcp.llm import llm_json
from rcp.objects import PaperCard, PdfAsset, ResearchFinding


class RelevanceScreen(BaseModel):
    relevant_indices: list[int]


def _pdf_asset(paper: dict) -> PdfAsset | None:
    """Carry an acquired PDF onto the card without reading it.

    Attaching a file must never raise extraction_basis: a PDF sitting on disk is
    not evidence that anything in it was read. Only a human confirming a full-text
    proposal at the triage gate can do that.
    """
    raw = paper.get("pdf")
    if not raw:
        return None
    try:
        return PdfAsset.model_validate(raw)
    except ValueError:
        return None


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
    except Exception:
        return candidates


class CardFields(BaseModel):
    problem: str = ""
    method: str = ""
    metrics: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    study_conditions: list[str] = Field(default_factory=list)
    findings: list["FindingFields"] = Field(default_factory=list)


class FindingFields(BaseModel):
    statement: str
    intervention: str = ""
    outcome: str = ""
    direction: Literal["increase", "decrease", "no_change", "mixed", "not_reported"] = "not_reported"
    conditions: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)


def extract_card(paper: dict, topic: str) -> PaperCard:
    abstract = (paper.get("abstract") or "").strip()
    if not abstract:
        return PaperCard(
            id=paper.get("id") or paper["title"][:60],
            title=paper["title"],
            year=paper.get("year"),
            doi=paper.get("doi"),
            url=paper.get("url"),
            venue=paper.get("venue"),
            authors=paper.get("authors", []),
            citations=paper.get("citations", 0),
            publication_type=paper.get("publication_type", "unknown"),
            peer_review_confidence=paper.get("peer_review_confidence", "uncertain"),
            credibility_explanation=paper.get(
                "credibility_explanation", "Publication status has not been independently verified."
            ),
            provenance=paper.get("provenance", [paper.get("source", "unknown")]),
            selection_score=paper.get("selection_score", 0.0),
            ranking_factors=paper.get("ranking_factors", {}),
            extraction_basis="title",
            pdf=_pdf_asset(paper),
            insufficient_evidence=[
                "problem", "method", "metrics", "limitations", "tags", "findings",
                "study_conditions",
            ],
        )
    fields = llm_json(
        f"Research topic under study: {topic}\n\n"
        f"Paper title: {paper['title']}\n"
        f"Venue: {paper.get('venue') or 'unknown'} ({paper.get('year') or '?'})\n"
        f"Abstract: {abstract}\n\n"
        "Extract only information explicitly supported by this abstract: the problem, method "
        "(including mathematical models when stated), metrics, stated limitations, study "
        "conditions, 3-6 topical tags, and discrete reported findings. For each finding, "
        "record the intervention, outcome, direction, conditions, and metrics when stated. "
        "Use empty values instead of inferring information that the abstract does not contain.",
        CardFields,
        system=(
            "You extract structured scientific evidence. Never invent a result, condition, "
            "method, or limitation that is absent from the supplied abstract."
        ),
    )
    paper_id = paper.get("id") or paper["title"][:60]
    raw = fields.model_dump(exclude={"findings"})
    findings = [
        ResearchFinding(
            id=f"{paper_id}:finding:{index}", paper_id=paper_id,
            extraction_basis="abstract", **finding.model_dump(),
        )
        for index, finding in enumerate(fields.findings, 1)
        if finding.statement.strip()
    ]
    insufficient = []
    for name in ("problem", "method", "metrics", "limitations", "study_conditions"):
        if not raw.get(name):
            insufficient.append(name)
    if not findings:
        insufficient.append("findings")
    return PaperCard(
        id=paper_id,
        title=paper["title"],
        year=paper.get("year"),
        doi=paper.get("doi"),
        url=paper.get("url"),
        venue=paper.get("venue"),
        authors=paper.get("authors", []),
        citations=paper.get("citations", 0),
        abstract=paper.get("abstract", ""),
        publication_type=paper.get("publication_type", "unknown"),
        peer_review_confidence=paper.get("peer_review_confidence", "uncertain"),
        credibility_explanation=paper.get(
            "credibility_explanation", "Publication status has not been independently verified."
        ),
        provenance=paper.get("provenance", [paper.get("source", "unknown")]),
        selection_score=paper.get("selection_score", 0.0),
        ranking_factors=paper.get("ranking_factors", {}),
        extraction_basis="abstract",
        pdf=_pdf_asset(paper),
        field_provenance={
            "problem": ["abstract"], "method": ["abstract"], "metrics": ["abstract"],
            "limitations": ["abstract"], "tags": ["abstract"],
            "findings": ["abstract"], "study_conditions": ["abstract"],
        },
        findings=findings, insufficient_evidence=insufficient, **raw,
    )
