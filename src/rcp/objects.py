"""Standard data objects — the contracts between modules (PRD §5.3).

Defaults on newly-added fields are intentional: older memory snapshots and
LangGraph checkpoints remain readable as the contracts evolve.
"""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ResearchTopic(BaseModel):
    title: str
    constraints: list[str] = Field(default_factory=list)
    notes: str = ""


class ThesisProfile(BaseModel):
    domain: str = "Data-center digital twins"
    interests: list[str] = Field(default_factory=list)
    objectives: list[str] = Field(default_factory=list)
    preferred_methods: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    experience_level: str = "intermediate"


class ThesisIdea(BaseModel):
    id: str
    rank: int = 0
    title: str
    research_question: str = ""
    novelty: str = ""
    feasibility: str = ""
    contribution: str = ""
    risks: list[str] = Field(default_factory=list)
    supporting_paper_ids: list[str] = Field(default_factory=list)
    model_names: list[str] = Field(default_factory=list)
    rank_score: float = 0.0
    rank_explanation: str = ""
    ranking_factors: dict[str, float] = Field(default_factory=dict)
    provider_status: str = "ok"
    provider_warnings: list[str] = Field(default_factory=list)


class PdfAsset(BaseModel):
    """Record of one open-access PDF acquisition attempt, successful or not.

    A failed attempt is recorded just as deliberately as a successful one: it is
    provenance-honest to state that several open-access sources were checked and
    none published a retrievable PDF, rather than rendering an unexplained gap.
    """

    status: Literal[
        "not_attempted", "available", "unavailable", "not_pdf", "too_large", "unreadable"
    ] = "not_attempted"
    sha256: str = ""
    bytes: int = 0
    page_count: int = 0
    source_url: str = ""
    landing_page_url: str = ""
    oa_status: str = ""  # gold | green | hybrid | bronze | closed | unknown
    license: str = ""  # "" means the provider stated no licence — not that none applies
    oa_version: str = ""  # submittedVersion | acceptedVersion | publishedVersion
    provider: str = ""  # openalex | semantic_scholar | unpaywall
    content_type: str = ""
    http_status: int | None = None
    error: str = ""
    retrieved_at: str = ""
    attempted_urls: list[str] = Field(default_factory=list)


class ResearchFinding(BaseModel):
    """One source-grounded result extracted from an eligible paper record."""

    id: str
    paper_id: str
    statement: str
    intervention: str = ""
    outcome: str = ""
    direction: Literal["increase", "decrease", "no_change", "mixed", "not_reported"] = "not_reported"
    conditions: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    extraction_basis: Literal["abstract", "full_text"] = "abstract"
    # Populated only by confirmed full-text extraction, so a finding can be traced
    # back to the page it was read from.
    source_pages: list[int] = Field(default_factory=list)
    quote: str = ""


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
    findings: list[ResearchFinding] = Field(default_factory=list)
    study_conditions: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    publication_type: str = "unknown"
    peer_review_confidence: Literal["verified", "likely", "uncertain", "preprint"] = "uncertain"
    credibility_explanation: str = "Publication status has not been independently verified."
    provenance: list[str] = Field(default_factory=list)
    selection_score: float = 0.0
    ranking_factors: dict[str, float] = Field(default_factory=dict)
    extraction_basis: Literal["title", "abstract", "full_text"] = "title"
    field_provenance: dict[str, list[str]] = Field(default_factory=dict)
    insufficient_evidence: list[str] = Field(default_factory=list)
    pdf: PdfAsset | None = None

    # Run-scoped human state. A frozen snapshot card always serialises these
    # defaults; only the copy carried in RCPState after the literature-triage gate
    # holds real values. PaperCard therefore serves both as the immutable snapshot
    # record and as the live run object -- a knowing trade, since splitting them
    # would ripple through _cards(), synthesis, evidence, reports, the memory API,
    # and the TypeScript mirror.
    triage_status: Literal["pending", "included", "excluded"] = "pending"
    triage_reason: str = ""
    human_reviewed: bool = False
    human_corrected_fields: list[str] = Field(default_factory=list)
    reviewer_notes: list[str] = Field(default_factory=list)
    full_text_extraction_id: str = ""


class ResearchGap(BaseModel):
    id: str
    category: Literal["method", "scenario", "metric", "scope", "validation"]
    statement: str
    paper_ids: list[str] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)
    model_names: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "low"
    testability_note: str = ""


class ResearchConflict(BaseModel):
    id: str
    kind: Literal["contradiction", "tension"] = "tension"
    statement: str
    finding_ids: list[str] = Field(default_factory=list)
    paper_ids: list[str] = Field(default_factory=list)
    explanatory_factors: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "low"


class ResearchSynthesis(BaseModel):
    source_snapshot: str = ""
    papers_total: int = 0
    papers_with_abstract: int = 0
    papers_with_findings: int = 0
    finding_count: int = 0
    gaps: list[ResearchGap] = Field(default_factory=list)
    conflicts: list[ResearchConflict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class FieldCorrection(BaseModel):
    """One human correction to an extracted paper field.

    Values are JSON-encoded strings rather than a loose Any, which keeps the model
    strictly typed for the checkpoint allowlist and makes a revert byte-exact.
    """

    id: str
    paper_id: str
    field: str  # a PaperCard field name, or "finding:<finding_id>:statement"
    previous_value: str = ""  # JSON-encoded
    new_value: str = ""  # JSON-encoded
    rationale: str = ""
    author: str = "human"
    created_at: str = Field(default_factory=utc_now)
    reverted: bool = False


class TriageDecision(BaseModel):
    paper_id: str
    action: Literal["include", "exclude"] = "include"
    reason: str = ""  # required and non-empty for every exclusion
    notes: list[str] = Field(default_factory=list)
    decided_by: str = "human"
    decided_at: str = Field(default_factory=utc_now)


class LiteratureTriage(BaseModel):
    """Run-scoped overlay recording which papers a human kept, and why.

    This never rewrites the frozen memory snapshot. The effective paper set is a
    pure function of (snapshot cards, this overlay, accepted full-text extractions),
    so two runs may triage the same snapshot differently and both stay reproducible.
    """

    schema_version: int = 1
    run_id: str
    memory_snapshot: str = ""
    memory_snapshot_cards_sha256: str = ""  # binds the decision to the exact card set
    mode: Literal["human", "auto"] = "human"
    reviewer: str = ""
    decisions: list[TriageDecision] = Field(default_factory=list)
    corrections: list[FieldCorrection] = Field(default_factory=list)
    accepted_full_text_ids: list[str] = Field(default_factory=list)
    included_paper_ids: list[str] = Field(default_factory=list)
    excluded_paper_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)


class PaperCardPatch(BaseModel):
    """The subset of a PaperCard that full-text extraction may propose."""

    problem: str = ""
    method: str = ""
    metrics: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    study_conditions: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    findings: list[ResearchFinding] = Field(default_factory=list)


class FullTextExtraction(BaseModel):
    """A proposed full-text re-reading of one paper, pending human confirmation.

    Storing this never changes the card. Only an explicit human confirmation at the
    literature-triage gate may raise a card's extraction_basis to "full_text".
    """

    id: str
    run_id: str
    paper_id: str
    pdf_sha256: str
    page_count: int = 0
    pages_used: list[int] = Field(default_factory=list)
    chars_used: int = 0
    llm_model: str = ""
    status: Literal["proposed", "accepted", "rejected", "superseded"] = "proposed"
    proposed: PaperCardPatch = Field(default_factory=PaperCardPatch)
    superseded_finding_ids: list[str] = Field(default_factory=list)
    confirmed_by: str = ""
    confirmed_at: str = ""
    warnings: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)


class Hypothesis(BaseModel):
    id: str
    statement: str
    rationale: str = ""
    variables: list[str] = Field(default_factory=list)
    expected_effect: str = ""
    metrics: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    model_names: list[str] = Field(default_factory=list)
    supporting_gap_ids: list[str] = Field(default_factory=list)
    supporting_conflict_ids: list[str] = Field(default_factory=list)
    supporting_paper_ids: list[str] = Field(default_factory=list)
    rank: int = 0
    rank_score: float = 0.0
    ranking_factors: dict[str, float] = Field(default_factory=dict)
    rank_explanation: str = ""


class ExperimentSpec(BaseModel):
    id: str
    hypothesis_id: str
    model_name: str
    parameters: dict[str, float] = Field(default_factory=dict)
    outputs: list[str] = Field(default_factory=list)
    start_time: float = 0.0
    stop_time: float = 86400.0
    intervals: int = 500
    description: str = ""


class ExperimentCase(BaseModel):
    """One executable case within a comparative experiment plan."""

    id: str
    label: str = ""
    role: Literal["baseline", "candidate", "ablation", "sweep"] = "sweep"
    model_name: str
    parameters: dict[str, float] = Field(default_factory=dict)
    outputs: list[str] = Field(default_factory=list)
    start_time: float = 0.0
    stop_time: float = 86400.0
    intervals: int = 1440
    factor_values: dict[str, float] = Field(default_factory=dict)


class ComparisonPair(BaseModel):
    id: str
    baseline_case_id: str
    candidate_case_id: str
    label: str = ""


class AnalysisProtocol(BaseModel):
    """Methods frozen with an experiment plan before any case is executed."""

    id: str = "generic-analysis-v1"
    version: str = "1.0"
    thermal_threshold_degC: float = 27.0
    hvac_power_screen_min_W: float = 0.0
    hvac_power_screen_max_W: float = 2_000_000.0
    power_screen_method: Literal["linear_bridge"] = "linear_bridge"
    max_power_screen_fraction: float = 0.01
    pue_min: float = 1.0
    pue_max: float = 3.0
    mode_hours_tolerance: float = 0.05
    comparison_absolute_tolerance: float = 1e-9
    comparison_relative_tolerance: float = 1e-6
    require_complete_pair_metrics: bool = True
    require_it_energy_load_monotonicity: bool = True
    metric_directions: dict[str, Literal["lower_is_better", "higher_is_better", "neutral"]] = Field(default_factory=dict)
    metric_units: dict[str, str] = Field(default_factory=dict)
    metric_methods: dict[str, str] = Field(default_factory=dict)


class ExperimentPlan(BaseModel):
    id: str
    hypothesis_id: str
    cases: list[ExperimentCase] = Field(default_factory=list)
    comparison_pairs: list[ComparisonPair] = Field(default_factory=list)
    primary_metrics: list[str] = Field(default_factory=list)
    analysis_protocol: AnalysisProtocol = Field(default_factory=AnalysisProtocol)
    description: str = ""
    validation_issues: list[str] = Field(default_factory=list)


class ResultBundle(BaseModel):
    spec_id: str
    case_id: str = ""
    model_name: str = ""
    parameters: dict[str, float] = Field(default_factory=dict)
    status: str = "pending"  # ok | failed
    workdir: str = ""
    result_file: str | None = None
    execution_spec_sha256: str = ""
    result_file_sha256: str = ""
    observed_result_file_sha256: str = ""
    result_file_bytes: int = 0
    result_file_integrity: Literal["verified", "unverified", "mismatch"] = "unverified"
    sample_count: int = 0
    metrics: dict[str, float] = Field(default_factory=dict)
    metric_methods: dict[str, str] = Field(default_factory=dict)
    log_excerpt: str = ""
    validation_status: str = "unknown"
    warnings: list[str] = Field(default_factory=list)
    validation_report_id: str | None = None


class MetricComparison(BaseModel):
    id: str
    pair_id: str
    metric: str
    baseline_case_id: str
    candidate_case_id: str
    baseline_value: float
    candidate_value: float
    absolute_delta: float
    percent_delta: float | None = None
    direction: Literal["lower_is_better", "higher_is_better", "neutral"] = "neutral"
    candidate_better: bool | None = None
    unit: str = ""


class StudyQualityCheck(BaseModel):
    id: str
    status: Literal["passed", "warning", "failed"]
    message: str
    observed: str = ""
    expected: str = ""
    case_ids: list[str] = Field(default_factory=list)


class StudyQualityReport(BaseModel):
    valid: bool = False
    protocol_id: str = ""
    protocol_sha256: str = ""
    checks: list[StudyQualityCheck] = Field(default_factory=list)
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ExperimentResultSet(BaseModel):
    plan_id: str
    status: Literal["pending", "ok", "partial", "failed"] = "pending"
    cases: list[ResultBundle] = Field(default_factory=list)
    comparisons: list[MetricComparison] = Field(default_factory=list)
    experiment_plan_sha256: str = ""
    analysis_protocol_sha256: str = ""
    analysis_protocol_snapshot: AnalysisProtocol | None = None
    raw_dataset_sha256: str = ""
    analysis_revision_id: str = ""
    quality_report: StudyQualityReport | None = None
    warnings: list[str] = Field(default_factory=list)
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AnalysisRevision(BaseModel):
    id: str
    plan_id: str
    experiment_plan_sha256: str = ""
    protocol_id: str = ""
    protocol_sha256: str = ""
    raw_dataset_sha256: str = ""
    generated_at: str = ""
    status: Literal["ok", "partial", "failed"]
    quality_valid: bool | None = None
    case_count: int = 0
    comparison_count: int = 0
    current: bool = False
    warnings: list[str] = Field(default_factory=list)


class MetricOutcome(BaseModel):
    """Decision-oriented summary of one pre-registered comparison metric."""

    metric: str
    wins: int = 0
    losses: int = 0
    ties: int = 0
    median_percent_delta: float | None = None
    direction: Literal["lower_is_better", "higher_is_better", "neutral"] = "neutral"
    unit: str = ""


class RunOutcome(BaseModel):
    """Deterministic run synopsis exposed to the research cockpit."""

    primary_finding: str
    quality_status: Literal["pending", "passed", "qualified", "failed"] = "pending"
    qualifications: list[str] = Field(default_factory=list)
    metrics: list[MetricOutcome] = Field(default_factory=list)
    next_action: str = ""
    elapsed_seconds: float | None = None
    token_usage: dict[str, int | float] = Field(default_factory=dict)


class CheckpointHealth(BaseModel):
    status: Literal["ok", "empty", "missing", "incompatible", "corrupt"] = "empty"
    detail: str = ""
    resumable: bool = False
    schema_version: int = 1


class ProtocolChanges(BaseModel):
    """Supervisor-editable numeric analysis settings; methods remain immutable."""

    thermal_threshold_degC: float | None = None
    hvac_power_screen_min_W: float | None = None
    hvac_power_screen_max_W: float | None = None
    max_power_screen_fraction: float | None = None
    pue_min: float | None = None
    pue_max: float | None = None
    mode_hours_tolerance: float | None = None
    comparison_absolute_tolerance: float | None = None
    comparison_relative_tolerance: float | None = None


class PdfAnchor(BaseModel):
    """A passage in a cached PDF, anchored by page and quote rather than pixels.

    Quote plus page survives re-render and zoom changes and is what a human
    actually cites; rects are normalised 0-1 so they stay resolution-independent.
    """

    paper_id: str = ""
    pdf_sha256: str = ""
    page: int = 0
    quote: str = ""
    prefix: str = ""  # up to 48 characters before the quote, for re-anchoring
    suffix: str = ""  # up to 48 characters after
    char_start: int = 0
    char_end: int = 0
    rects: list[dict[str, float]] = Field(default_factory=list)
    extractor: str = ""  # e.g. "pdfjs-4/text-layer" -- makes a stale anchor detectable


class Annotation(BaseModel):
    """A human remark attached to any evidence object.

    Annotations are advisory and append-only. They never enter a generation prompt
    and never change routing: review_claims remains the only thing that can fail a
    claim closed. An edit or a resolution is a new record with `supersedes` set.
    """

    id: str
    run_id: str
    evidence_id: str
    evidence_kind: str = ""
    evidence_fingerprint: str = ""  # detects drift of positional ids such as claim:2
    kind: Literal["comment", "flag", "correction"] = "comment"
    severity: Literal["info", "concern", "blocker"] = "info"
    body: str
    proposed_value: str = ""  # corrections only; NEVER applied automatically
    applied: bool = False
    anchor: PdfAnchor | None = None
    author: str = "human"
    created_at: str = Field(default_factory=utc_now)
    supersedes: str | None = None
    resolved: bool = False
    resolution_note: str = ""


RUBRIC_DIMENSIONS: tuple[str, ...] = (
    "claim_to_number_traceability",
    "claim_to_literature_traceability",
    "missing_evidence_visibility",
    "experiment_comparability_preregistration",
    "reproducibility_from_captured_inputs",
    "calibration_validation_disclosure",
    "claim_verification_effort",
)


class EvaluationScorecard(BaseModel):
    """One reviewer's blind 1-5 scoring of one output (docs/EVALUATION.md §50-71).

    There is deliberately no composite field. The protocol forbids combining these
    dimensions into a single "scientific validity" score, and verification time is
    kept as a separate raw observation rather than folded into a rating.

    `blinded` and `blinding_method` are claims recorded by the submitter, not
    guarantees: this service has no authentication and `reviewer_id` is
    self-declared. Presenting them as verified would itself be a provenance
    dishonesty.
    """

    id: str
    run_id: str
    reviewer_id: str
    condition: Literal["platform", "baseline"] = "platform"
    blinded: bool = True
    blinding_method: str = ""
    self_evaluated: bool = False  # reviewer also ran the cycle; excluded from statistics
    claim_to_number_traceability: int = Field(ge=1, le=5)
    claim_to_literature_traceability: int = Field(ge=1, le=5)
    missing_evidence_visibility: int = Field(ge=1, le=5)
    experiment_comparability_preregistration: int = Field(ge=1, le=5)
    reproducibility_from_captured_inputs: int = Field(ge=1, le=5)
    calibration_validation_disclosure: int = Field(ge=1, le=5)
    claim_verification_effort: int = Field(ge=1, le=5)
    verification_time_seconds: float | None = None
    challenged_claim_id: str = ""
    observations: str = ""
    created_at: str = Field(default_factory=utc_now)


class DimensionSummary(BaseModel):
    dimension: str
    n: int = 0
    minimum: int = 0
    median: float = 0.0
    maximum: int = 0
    disagreement: bool = False  # True when maximum - minimum >= 2


class RubricSummary(BaseModel):
    run_id: str
    reviewer_count: int = 0
    condition: Literal["platform", "baseline"] = "platform"
    dimensions: list[DimensionSummary] = Field(default_factory=list)
    verification_time_seconds: list[float] = Field(default_factory=list)
    disagreement_dimensions: list[str] = Field(default_factory=list)
    generated_at: str = Field(default_factory=utc_now)


class ResearchReview(BaseModel):
    decision: Literal["accept", "reanalyse", "revise_plan", "refine_hypothesis"]
    feedback: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    parent_version: int
    protocol_changes: dict[str, float] = Field(default_factory=dict)
    successor_run_id: str | None = None
    # Frozen at decision time, so a scorecard submitted later cannot retroactively
    # change what the supervisor saw.
    scorecard_ids: list[str] = Field(default_factory=list)
    rubric_summary: RubricSummary | None = None
    reviewer_count: int = 0
    discussion_note: str = ""


class ResearchLineageItem(BaseModel):
    run_id: str
    topic: str
    status: str
    iteration: int = 0
    parent_run_id: str | None = None
    revision_decision: str | None = None
    review: ResearchReview | None = None


class ResearchLineage(BaseModel):
    root_run_id: str
    current_run_id: str
    runs: list[ResearchLineageItem] = Field(default_factory=list)


class Claim(BaseModel):
    statement: str
    evidence: str = ""  # which metrics/results support it
    confidence: str = "medium"  # low | medium | high
    evidence_ids: list[str] = Field(default_factory=list)
    comparison_ids: list[str] = Field(default_factory=list)
    case_ids: list[str] = Field(default_factory=list)
    paper_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ClaimBundle(BaseModel):
    hypothesis_id: str
    claims: list[Claim] = Field(default_factory=list)
    summary: str = ""
    credibility_warnings: list[str] = Field(default_factory=list)


class ReviewIssue(BaseModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    claim_index: int | None = None


class ReviewBundle(BaseModel):
    valid: bool = False
    issues: list[ReviewIssue] = Field(default_factory=list)
    checked_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ArtifactHash(BaseModel):
    path: str
    sha256: str
    bytes: int = 0


class RunManifest(BaseModel):
    schema_version: int = 1
    run_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    code_revision: str = "unknown"
    code_dirty: bool = False
    runtime: dict[str, str] = Field(default_factory=dict)
    models: dict[str, dict[str, str]] = Field(default_factory=dict)
    llm: dict[str, str | float | bool] = Field(default_factory=dict)
    inputs: dict = Field(default_factory=dict)
    memory_snapshot: str = ""
    memory_snapshot_cards_sha256: str = ""
    artifacts: list[ArtifactHash] = Field(default_factory=list)
    timings_seconds: dict[str, float] = Field(default_factory=dict)
    token_usage: dict[str, int | float] = Field(default_factory=dict)
    lineage: dict[str, str | int | None] = Field(default_factory=dict)
    # Human-input summaries, so the manifest states what a person contributed.
    literature: dict[str, str | int] = Field(default_factory=dict)
    annotations: dict[str, str | int] = Field(default_factory=dict)
    evaluation: dict[str, str | int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ValidationReferenceCase(BaseModel):
    id: str
    name: str
    status: Literal["passed", "failed", "warning"]
    tolerance: str = ""
    observed: str = ""
    expected: str = ""
    details: str = ""


class ModelValidationReport(BaseModel):
    id: str
    model_name: str
    model_version: str
    status: str
    checks_status: str = "not_run"
    generated_at: str
    assumptions: list[str] = Field(default_factory=list)
    operating_range: dict[str, dict[str, float | str]] = Field(default_factory=dict)
    reference_cases: list[ValidationReferenceCase] = Field(default_factory=list)
    tolerances: dict[str, float | str] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    disclosure: str = ""


class ReportMetadata(BaseModel):
    title: str
    run_id: str
    authors: list[str] = Field(default_factory=list)
    abstract: str = ""
    keywords: list[str] = Field(default_factory=list)
    disclosures: list[str] = Field(default_factory=list)


class ReportSection(BaseModel):
    id: str
    title: str
    kind: str = "custom"
    content: str = ""
    locked: bool = False
    generated: bool = True
    stale: bool = False
    citation_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    generated_content: str = ""
    updated_at: str = Field(default_factory=utc_now)


class ReportReference(BaseModel):
    id: str
    paper_id: str
    citation: str
    doi: str | None = None
    url: str | None = None


class ReportFigure(BaseModel):
    id: str
    title: str
    path: str = ""
    caption: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class EvidenceLink(BaseModel):
    id: str
    kind: str
    label: str
    source: str = ""


class ReportDocument(BaseModel):
    schema_version: int = 1
    version: int = 1
    run_id: str
    metadata: ReportMetadata
    sections: list[ReportSection] = Field(default_factory=list)
    references: list[ReportReference] = Field(default_factory=list)
    figures: list[ReportFigure] = Field(default_factory=list)
    evidence_links: list[EvidenceLink] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    migrated_from_legacy: bool = False


class ReportRevision(BaseModel):
    id: str
    version: int
    created_at: str = Field(default_factory=utc_now)
    summary: str = ""
