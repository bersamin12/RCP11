import json
import re

import pytest

from rcp.evaluation import blind, is_revealed, load_scorecards, submit_scorecard, summarize
from rcp.objects import RUBRIC_DIMENSIONS, EvaluationScorecard

SCORES = dict.fromkeys(RUBRIC_DIMENSIONS, 4)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("RCP_DATA_DIR", str(tmp_path / "data"))
    from rcp.config import get_settings

    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def card(reviewer: str, condition: str = "platform", **overrides) -> EvaluationScorecard:
    return EvaluationScorecard(
        id=f"eval-run-1-{reviewer}-{condition}", run_id="run-1", reviewer_id=reviewer,
        condition=condition, **{**SCORES, **overrides},
    )


# ---------- the protocol's own arithmetic prohibition ----------

def test_no_composite_score_is_ever_produced(store):
    """EVALUATION.md forbids folding the dimensions into one validity score."""
    submit_scorecard("run-1", card("a"))
    submit_scorecard("run-1", card("b", claim_to_number_traceability=2))
    payload = json.loads(summarize("run-1").model_dump_json())

    flat = json.dumps(payload).lower()
    for banned in ("total", "overall", "composite", "average", "mean", "aggregate_score"):
        assert banned not in flat, f"summary must not expose a {banned}"
    assert not any(re.search(r"total|overall|composite|mean", key) for key in payload)


def test_verification_time_stays_a_list_of_raw_observations(store):
    submit_scorecard("run-1", card("a", verification_time_seconds=240.0))
    submit_scorecard("run-1", card("b", verification_time_seconds=900.0))
    summary = summarize("run-1")
    assert summary.verification_time_seconds == [240.0, 900.0]


# ---------- score range and write-once ----------

@pytest.mark.parametrize("value", [0, 6, -1, 99])
def test_scores_outside_one_to_five_are_rejected(store, value):
    with pytest.raises(ValueError):
        card("a", claim_to_number_traceability=value)


def test_a_reviewer_may_score_a_condition_only_once(store):
    submit_scorecard("run-1", card("a"))
    with pytest.raises(ValueError, match="already scored"):
        submit_scorecard("run-1", card("a"))


def test_the_same_reviewer_may_score_both_conditions(store):
    submit_scorecard("run-1", card("a", condition="platform"))
    submit_scorecard("run-1", card("a", condition="baseline"))
    assert len(load_scorecards("run-1")) == 2
    assert len(load_scorecards("run-1", "platform")) == 1


def test_a_colliding_id_can_never_replace_a_submitted_score(store):
    submit_scorecard("run-1", card("a"))
    duplicate = card("b")
    duplicate.id = "eval-run-1-a-platform"
    with pytest.raises(ValueError, match="already exists"):
        submit_scorecard("run-1", duplicate)


# ---------- independence ----------

def test_scores_stay_concealed_until_enough_reviewers_have_submitted(store):
    submit_scorecard("run-1", card("a"))
    assert is_revealed("run-1") is False
    submit_scorecard("run-1", card("b"))
    assert is_revealed("run-1") is True


def test_disagreement_is_flagged_rather_than_averaged_away(store):
    submit_scorecard("run-1", card("a", missing_evidence_visibility=5))
    submit_scorecard("run-1", card("b", missing_evidence_visibility=2))
    summary = summarize("run-1")
    dimension = next(d for d in summary.dimensions if d.dimension == "missing_evidence_visibility")
    assert dimension.minimum == 2 and dimension.maximum == 5
    assert dimension.disagreement is True
    assert "missing_evidence_visibility" in summary.disagreement_dimensions


def test_a_self_evaluation_is_excluded_from_the_reported_statistics(store):
    submit_scorecard("run-1", card("a"))
    submit_scorecard("run-1", card("runner", self_evaluated=True))
    summary = summarize("run-1")
    assert summary.reviewer_count == 1


# ---------- blinding the packet ----------

def test_the_platform_never_shows_its_own_confidence_to_a_scorer(store):
    packet = {
        "papers": [{
            "title": "A paper", "selection_score": 71.5, "ranking_factors": {"relevance": 0.9},
            "peer_review_confidence": "verified", "credibility_explanation": "corroborated",
        }],
        "claims": [{"statement": "Energy fell.", "confidence": "high"}],
        "hypotheses": [{"id": "H1", "rank_score": 88.0, "rank_explanation": "why"}],
    }
    blinded = blind(packet)
    flat = json.dumps(blinded)
    for banned in ("selection_score", "ranking_factors", "peer_review_confidence",
                   "credibility_explanation", "confidence", "rank_score", "rank_explanation"):
        assert banned not in flat, f"{banned} would anchor the judgement being measured"
    # The substance a reviewer needs is still there.
    assert blinded["papers"][0]["title"] == "A paper"
    assert blinded["claims"][0]["statement"] == "Energy fell."
