"""Deterministic, registry- and evidence-grounded hypothesis ranking."""

import re

from rcp.objects import Hypothesis, PaperCard, ResearchSynthesis
from rcp.simulation.registry import ModelInfo, load_registry


PROFILE_METRICS = {
    "default": {"T_peak_degC", "T_avg_degC", "T_final_degC", "P_cool_avg_W", "E_cool_kWh"},
    "chiller_benchmark": {
        "E_HVAC_kWh", "PUE", "T_room_peak_degC", "thermal_exceedance_degree_hours",
        "free_cooling_hours", "partial_mechanical_hours", "full_mechanical_hours", "mode_switches",
    },
}


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _coverage(values: list[str], available: set[str]) -> float:
    if not values:
        return 0.0
    known = {_key(item) for item in available}
    return sum(_key(value) in known for value in values) / len(values)


def _model_fit(hypothesis: Hypothesis, model: ModelInfo) -> float:
    variables = _coverage(hypothesis.variables, set(model.parameters))
    metrics = _coverage(
        hypothesis.metrics,
        {*model.outputs, *PROFILE_METRICS.get(model.metric_profile, set())},
    )
    return 0.4 + 0.3 * variables + 0.3 * metrics


def rank_hypotheses(
    hypotheses: list[Hypothesis], synthesis: ResearchSynthesis | None,
    cards: list[PaperCard], registry: dict[str, ModelInfo] | None = None,
) -> list[Hypothesis]:
    registry = registry or load_registry()
    if not registry:
        raise ValueError("hypothesis ranking requires at least one registered simulation model")
    card_by_id = {card.id: card for card in cards}
    gap_ids = {gap.id for gap in (synthesis.gaps if synthesis else [])}
    conflict_ids = {conflict.id for conflict in (synthesis.conflicts if synthesis else [])}
    gap_papers = {
        gap.id: gap.paper_ids for gap in (synthesis.gaps if synthesis else [])
    }
    conflict_papers = {
        conflict.id: conflict.paper_ids for conflict in (synthesis.conflicts if synthesis else [])
    }
    ranked: list[Hypothesis] = []
    for hypothesis in hypotheses:
        proposed_models = list(dict.fromkeys(name for name in hypothesis.model_names if name in registry))
        candidates = proposed_models or list(registry)
        best_name, best_fit = max(
            ((name, _model_fit(hypothesis, registry[name])) for name in candidates),
            key=lambda item: (item[1], item[0]),
        )
        if not hypothesis.variables or not hypothesis.metrics or best_fit <= 0.4:
            continue
        models = proposed_models or [best_name]

        valid_gaps = list(dict.fromkeys(item for item in hypothesis.supporting_gap_ids if item in gap_ids))
        valid_conflicts = list(dict.fromkeys(
            item for item in hypothesis.supporting_conflict_ids if item in conflict_ids
        ))
        inherited_papers = [
            paper_id
            for item_id in [*valid_gaps, *valid_conflicts]
            for paper_id in (gap_papers.get(item_id) or conflict_papers.get(item_id) or [])
        ]
        valid_papers = list(dict.fromkeys(
            paper_id for paper_id in [*hypothesis.supporting_paper_ids, *inherited_papers]
            if paper_id in card_by_id
        ))
        synthesis_reference_score = 1.0 if valid_gaps or valid_conflicts else 0.0
        paper_count_score = min(len(valid_papers) / 3, 1.0)
        paper_quality_score = (
            sum(card_by_id[paper_id].selection_score / 100 for paper_id in valid_papers)
            / len(valid_papers)
            if valid_papers else 0.0
        )
        evidence_grounding = (
            0.4 * synthesis_reference_score + 0.4 * paper_count_score + 0.2 * paper_quality_score
        )
        testability = sum((
            bool(hypothesis.statement.strip() and hypothesis.rationale.strip()),
            bool(hypothesis.variables), bool(hypothesis.metrics),
            bool(hypothesis.expected_effect.strip()), bool(hypothesis.risks),
        )) / 5
        novelty_opportunity = (
            0.6 * min(len(valid_gaps) / 2, 1.0)
            + 0.4 * min(len(valid_conflicts), 1.0)
        )
        factors = {
            "model_fit": round(best_fit, 4),
            "evidence_grounding": round(evidence_grounding, 4),
            "testability": round(testability, 4),
            "novelty_opportunity": round(novelty_opportunity, 4),
        }
        score = round(100 * (
            0.35 * best_fit + 0.30 * evidence_grounding
            + 0.20 * testability + 0.15 * novelty_opportunity
        ), 2)
        ranked.append(hypothesis.model_copy(update={
            "model_names": models,
            "supporting_gap_ids": valid_gaps,
            "supporting_conflict_ids": valid_conflicts,
            "supporting_paper_ids": valid_papers,
            "rank_score": score,
            "ranking_factors": factors,
            "rank_explanation": (
                f"Fixed score: model fit {best_fit:.0%}, evidence grounding "
                f"{evidence_grounding:.0%}, testability {testability:.0%}, and "
                f"research opportunity {novelty_opportunity:.0%}."
            ),
        }))
    ranked.sort(key=lambda item: (-item.rank_score, item.id))
    return [item.model_copy(update={"rank": index}) for index, item in enumerate(ranked, 1)]
