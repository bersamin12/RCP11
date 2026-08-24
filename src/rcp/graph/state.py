"""Global workflow state shared by all nodes (PRD §5.2/§5.3)."""

from typing import Literal

from pydantic import BaseModel, Field

from rcp.objects import (
    ClaimBundle,
    ExperimentPlan,
    ExperimentResultSet,
    ExperimentSpec,
    Hypothesis,
    LiteratureTriage,
    PaperCard,
    ResearchSynthesis,
    ResearchTopic,
    ResultBundle,
    ReviewBundle,
    ThesisIdea,
    ThesisProfile,
)

# Version 2 added the literature-triage gate. Every field introduced with it is
# defaulted, so a version-1 checkpoint still validates and reports no triage.
CHECKPOINT_SCHEMA_VERSION = 2
SUPPORTED_CHECKPOINT_VERSIONS = {1, 2}


class RCPState(BaseModel):
    checkpoint_schema_version: int = CHECKPOINT_SCHEMA_VERSION
    run_id: str
    topic: ResearchTopic
    entry_point: Literal["research", "hypothesis", "spec", "reanalysis"] = "research"
    parent_run_id: str = ""
    revision_feedback: str = ""
    auto: bool = False  # auto-resolve human gates (testing/CI)
    thesis_idea: ThesisIdea | None = None
    thesis_profile: ThesisProfile | None = None

    paper_cards: list[PaperCard] = Field(default_factory=list)
    themes: dict = Field(default_factory=dict)
    memory_snapshot: str = ""
    # None means no triage was performed (any pre-version-2 checkpoint); a record
    # with mode="auto" means it was explicitly skipped. Never conflate the two.
    literature_triage: LiteratureTriage | None = None
    excluded_paper_ids: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    research_synthesis: ResearchSynthesis | None = None
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    selected_hypothesis: Hypothesis | None = None
    experiment_spec: ExperimentSpec | None = None
    experiment_plan: ExperimentPlan | None = None
    spec_approved: bool = False
    spec_feedback: str = ""
    spec_attempts: int = 0
    result_bundle: ResultBundle | None = None
    experiment_results: ExperimentResultSet | None = None
    claim_bundle: ClaimBundle | None = None
    review_bundle: ReviewBundle | None = None
    review_attempts: int = 0
    rollback_action: str = ""
    report_path: str = ""
