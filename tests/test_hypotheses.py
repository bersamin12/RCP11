from rcp.hypotheses import rank_hypotheses
from rcp.objects import (
    Hypothesis, PaperCard, ResearchConflict, ResearchGap, ResearchSynthesis,
)


def test_hypothesis_ranking_is_deterministic_and_filters_references():
    cards = [
        PaperCard(id="p1", title="One", selection_score=90),
        PaperCard(id="p2", title="Two", selection_score=70),
    ]
    synthesis = ResearchSynthesis(
        gaps=[ResearchGap(
            id="gap-1", category="scenario", statement="Unstudied load envelope",
            paper_ids=["p1", "p2"], model_names=["DataCenterRoom"],
        )],
        conflicts=[ResearchConflict(
            id="conflict-1", kind="tension", statement="Conditions differ",
            paper_ids=["p1", "p2"],
        )],
    )
    strong = Hypothesis(
        id="H2", statement="Setpoint affects cooling energy", rationale="Grounded",
        variables=["T_set", "Q_it"], expected_effect="Lower energy", metrics=["E_cool_kWh"],
        risks=["Conceptual model"], model_names=["DataCenterRoom", "Unknown"],
        supporting_gap_ids=["gap-1", "missing"],
        supporting_conflict_ids=["conflict-1"], supporting_paper_ids=["p1", "bad"],
    )
    weak = Hypothesis(
        id="H1", statement="Explore cooling", variables=["T_amb"], metrics=["T"],
        model_names=[],
    )
    first = rank_hypotheses([weak, strong], synthesis, cards)
    second = rank_hypotheses([weak, strong], synthesis, cards)
    assert [item.model_dump() for item in first] == [item.model_dump() for item in second]
    assert first[0].id == "H2" and first[0].rank == 1
    assert first[0].model_names == ["DataCenterRoom"]
    assert first[0].supporting_gap_ids == ["gap-1"]
    assert first[0].supporting_paper_ids == ["p1", "p2"]
    assert set(first[0].ranking_factors) == {
        "model_fit", "evidence_grounding", "testability", "novelty_opportunity",
    }
    assert first[0].rank_score > first[1].rank_score


def test_missing_model_names_are_inferred_from_registry_fit():
    hypothesis = Hypothesis(
        id="H1", statement="Load affects temperature", rationale="Physical balance",
        variables=["Q_it"], metrics=["T"], expected_effect="Temperature increases",
        risks=["Conceptual"],
    )
    ranked = rank_hypotheses([hypothesis], None, [])
    assert ranked[0].model_names == ["DataCenterRoom"]
    assert ranked[0].ranking_factors["model_fit"] == 1.0


def test_non_testable_hypotheses_are_rejected():
    ranked = rank_hypotheses([Hypothesis(id="H1", statement="Explore cooling")], None, [])
    assert ranked == []
