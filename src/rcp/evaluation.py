"""Blind rubric scoring of a research cycle (docs/EVALUATION.md §50-71).

Deliberately separate from ``ResearchReview``. That is one supervisor's operational
decision about one run and may be made exactly once; this is a research
*measurement* taken by two or more people, independently, across two conditions
(the platform's output versus a plain baseline). Merging them would produce the
appearance of the protocol while breaking its three requirements at once.

What this module can enforce: scores stay concealed until enough independent
submissions exist, a reviewer may score a given condition only once, and no
composite number is ever computed -- the protocol explicitly forbids collapsing the
dimensions into a single "scientific validity" score.

What it cannot enforce, and says so plainly: this service has no authentication, so
``reviewer_id`` is self-declared and ``blinded`` is a claim by the submitter rather
than a property of the system. Presenting it as verified would be exactly the kind
of unearned confidence this platform exists to avoid.
"""

import statistics
import uuid
from pathlib import Path

from rcp.config import data_dir, get_settings
from rcp.objects import (
    RUBRIC_DIMENSIONS,
    DimensionSummary,
    EvaluationScorecard,
    RubricSummary,
)


def evaluation_dir(run_id: str) -> Path:
    return data_dir() / "runs" / run_id / "evaluation"


def new_scorecard_id(run_id: str) -> str:
    return f"eval-{run_id}-{uuid.uuid4().hex[:6]}"


def load_scorecards(run_id: str, condition: str | None = None) -> list[EvaluationScorecard]:
    directory = evaluation_dir(run_id)
    if not directory.is_dir():
        return []
    found: list[EvaluationScorecard] = []
    for path in sorted(directory.glob("*.json")):
        try:
            card = EvaluationScorecard.model_validate_json(path.read_text())
        except ValueError:
            continue
        if condition is None or card.condition == condition:
            found.append(card)
    return sorted(found, key=lambda card: card.created_at)


def submit_scorecard(run_id: str, scorecard: EvaluationScorecard) -> EvaluationScorecard:
    """Write once per (reviewer, condition). Revision means a new reviewer."""
    existing = load_scorecards(run_id)
    for card in existing:
        if card.reviewer_id == scorecard.reviewer_id and card.condition == scorecard.condition:
            raise ValueError(
                f"{scorecard.reviewer_id} has already scored the {scorecard.condition} condition"
            )
    directory = evaluation_dir(run_id)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{scorecard.id}.json"
    if destination.exists():
        # Write-once means write-once: never let an id collision quietly replace a
        # submitted score.
        raise ValueError(f"a scorecard with id {scorecard.id} already exists")
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(scorecard.model_dump_json(indent=2))
    temporary.replace(destination)
    return scorecard


def is_revealed(run_id: str, condition: str = "platform") -> bool:
    minimum = max(1, get_settings().rcp_min_rubric_reviewers)
    return len(load_scorecards(run_id, condition)) >= minimum


def summarize(run_id: str, condition: str = "platform") -> RubricSummary:
    """Per-dimension spread only.

    There is intentionally no total, mean, or composite: EVALUATION.md requires the
    dimensions and the verification time to be reported as separate raw
    observations, not folded into one score.
    """
    cards = [card for card in load_scorecards(run_id, condition) if not card.self_evaluated]
    dimensions: list[DimensionSummary] = []
    disagreements: list[str] = []

    for name in RUBRIC_DIMENSIONS:
        values = [getattr(card, name) for card in cards]
        if not values:
            dimensions.append(DimensionSummary(dimension=name))
            continue
        summary = DimensionSummary(
            dimension=name,
            n=len(values),
            minimum=min(values),
            median=float(statistics.median(values)),
            maximum=max(values),
            disagreement=(max(values) - min(values)) >= 2,
        )
        if summary.disagreement:
            disagreements.append(name)
        dimensions.append(summary)

    return RubricSummary(
        run_id=run_id,
        reviewer_count=len(cards),
        condition=condition,  # type: ignore[arg-type]
        dimensions=dimensions,
        verification_time_seconds=[
            card.verification_time_seconds for card in cards
            if card.verification_time_seconds is not None
        ],
        disagreement_dimensions=disagreements,
    )


def evaluation_digest(run_id: str) -> dict[str, str | int]:
    cards = load_scorecards(run_id)
    summary = summarize(run_id)
    return {
        "scorecards": len(cards),
        "reviewers": len({card.reviewer_id for card in cards}),
        "conditions": len({card.condition for card in cards}),
        "self_evaluated": sum(1 for card in cards if card.self_evaluated),
        "disagreements": len(summary.disagreement_dimensions),
    }


# Keys stripped from anything shown to a reviewer before they score. The platform's
# own confidence would otherwise anchor the very judgement being measured.
BLINDED_KEYS = frozenset({
    "rank_score", "selection_score", "ranking_factors", "rank_explanation",
    "confidence", "peer_review_confidence", "credibility_explanation",
})


def blind(value):
    """Recursively drop the platform's own scores and confidence markers."""
    if isinstance(value, dict):
        return {k: blind(v) for k, v in value.items() if k not in BLINDED_KEYS}
    if isinstance(value, list):
        return [blind(item) for item in value]
    return value
