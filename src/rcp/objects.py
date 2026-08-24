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
    spec_hash: str = ""  # sealed spec digest (PRD X.3)
    result_file_hash: str = ""  # SHA-256 of the raw result file (PRD X.3)


class Claim(BaseModel):
    statement: str
    evidence: str = ""  # which metrics/results support it (human-readable)
    metric_keys: list[str] = Field(default_factory=list)  # cited metric names (PRD X.3)
    paper_ids: list[str] = Field(default_factory=list)  # cited source papers (PRD X.3)
    confidence: str = "medium"  # low | medium | high


class ClaimBundle(BaseModel):
    hypothesis_id: str
    spec_id: str = ""  # spec the claims trace to (PRD X.3)
    result_hash: str = ""  # result-file fingerprint the claims trace to (PRD X.3)
    claims: list[Claim] = Field(default_factory=list)
    summary: str = ""
