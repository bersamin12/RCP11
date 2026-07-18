"""Global workflow state shared by all nodes (PRD §5.2/§5.3)."""

from pydantic import BaseModel, Field

from rcp.objects import (
    ClaimBundle,
    ExperimentSpec,
    Hypothesis,
    ResearchTopic,
    ResultBundle,
)


class RCPState(BaseModel):
    run_id: str
    topic: ResearchTopic
    auto: bool = False  # auto-resolve human gates (testing/CI)

    paper_cards: list = Field(default_factory=list)
    themes: dict = Field(default_factory=dict)
    gaps: list[str] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    selected_hypothesis: Hypothesis | None = None
    experiment_spec: ExperimentSpec | None = None
    spec_approved: bool = False
    spec_feedback: str = ""
    spec_attempts: int = 0
    result_bundle: ResultBundle | None = None
    claim_bundle: ClaimBundle | None = None
    report_path: str = ""
