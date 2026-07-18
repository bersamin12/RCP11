"""Standard data objects — the contracts between modules (PRD §5.3)."""

from pydantic import BaseModel, Field


class ResearchTopic(BaseModel):
    title: str
    constraints: list[str] = Field(default_factory=list)
    notes: str = ""


class PaperCard(BaseModel):
    id: str
    title: str
    year: int | None = None
    doi: str | None = None
    url: str | None = None
    venue: str | None = None
    authors: list[str] = Field(default_factory=list)
    citations: int = 0
    abstract: str = ""
    problem: str = ""
    method: str = ""
    metrics: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class Hypothesis(BaseModel):
    id: str
    statement: str
    rationale: str = ""
    variables: list[str] = Field(default_factory=list)
    expected_effect: str = ""
    metrics: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class ExperimentSpec(BaseModel):
    id: str
    hypothesis_id: str
    model_name: str
    parameters: dict[str, float] = Field(default_factory=dict)
    outputs: list[str] = Field(default_factory=list)
    stop_time: float = 86400.0
    intervals: int = 500
    description: str = ""


class ResultBundle(BaseModel):
    spec_id: str
    status: str = "pending"  # ok | failed
    workdir: str = ""
    result_file: str | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    log_excerpt: str = ""


class Claim(BaseModel):
    statement: str
    evidence: str = ""  # which metrics/results support it
    confidence: str = "medium"  # low | medium | high


class ClaimBundle(BaseModel):
    hypothesis_id: str
    claims: list[Claim] = Field(default_factory=list)
    summary: str = ""
