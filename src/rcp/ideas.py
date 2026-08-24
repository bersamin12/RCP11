"""Thesis ideation grounded in the model registry and a lightweight literature scan."""

import json

from pydantic import BaseModel, Field

from rcp.llm import llm_json
from rcp.memory.connectors import enrich_doi_metadata, search_openalex, search_semantic_scholar
from rcp.memory.dedup import dedupe
from rcp.memory.ranking import rank_papers
from rcp.objects import ThesisIdea, ThesisProfile
from rcp.simulation.registry import load_registry


class IdeaList(BaseModel):
    ideas: list[ThesisIdea] = Field(min_length=1, max_length=5)


def _fallback_ideas(profile: ThesisProfile, papers: list[dict], warning: str) -> list[ThesisIdea]:
    supporting = [str(p.get("id")) for p in papers[:3] if p.get("id")]
    templates = [
        (
            "Setpoint optimization under variable IT load",
            "How should the cooling setpoint change with IT load to reduce electricity use while maintaining a safe room temperature?",
            "Jointly maps the energy–temperature trade-off rather than testing one operating point.",
            "A bounded sweep of Q_it and T_set is directly supported by DataCenterRoom.",
            "A reproducible operating envelope and decision rule for exploratory design.",
            ["The lumped room model is not empirically calibrated.", "A proportional controller omits plant dynamics."],
        ),
        (
            "Cooling saturation and thermal resilience",
            "At what combinations of IT load and ambient temperature does cooling saturation cause unsafe temperature rise?",
            "Frames saturation as an explicit resilience boundary with interpretable physics.",
            "Q_it, T_amb, and Q_cool_max are available parameters with analytic checks.",
            "A transparent saturation-risk map and sensitivity analysis.",
            ["Extreme points may fall outside the model's credible operating range.", "No spatial hot-spot representation."],
        ),
        (
            "Thermal inertia as a demand-response resource",
            "How does effective room thermal capacitance affect the time available to respond to cooling or load disturbances?",
            "Connects lumped thermal inertia to operational response time.",
            "C_room sensitivity is fast to simulate and has a known monotonic expectation.",
            "Response-time curves that identify where empirical capacitance calibration matters most.",
            ["Effective capacitance is difficult to identify from literature alone.", "Constant load assumptions may overstate predictability."],
        ),
        (
            "Ambient-temperature sensitivity of cooling energy",
            "How strongly do ambient conditions affect cooling energy and safe operating temperature across realistic IT loads?",
            "Separates envelope heat transfer and cooling-control effects in a compact sensitivity study.",
            "T_amb, UA, Q_it, and COP are all exposed and range checked.",
            "A ranked sensitivity decomposition for subsequent high-fidelity validation.",
            ["Weather and envelope behavior are represented as constants.", "COP is fixed rather than temperature dependent."],
        ),
        (
            "Controller-gain robustness for data-center cooling",
            "Which proportional-control gains balance temperature regulation, stability, and cooling energy across uncertain loads?",
            "Tests controller robustness across a parameter envelope instead of reporting a nominal gain.",
            "The model exposes k_p, load, capacitance, and energy outputs.",
            "A feasible gain region and explicit limitations for follow-up controller studies.",
            ["The model has no actuator lag or sensor noise.", "Energy outcomes depend on the simplified constant COP."],
        ),
    ]
    ideas: list[ThesisIdea] = []
    for index, values in enumerate(templates, 1):
        title, question, novelty, feasibility, contribution, risks = values
        score = 94 - (index - 1) * 4
        ideas.append(
            ThesisIdea(
                id=f"idea-{index}", rank=index, title=title, research_question=question,
                novelty=novelty, feasibility=feasibility, contribution=contribution, risks=risks,
                supporting_paper_ids=supporting[max(0, index - 2):index + 1] or supporting,
                model_names=["DataCenterRoom"], rank_score=score,
                ranking_factors={"model_fit": 1.0, "literature_support": 0.6 if supporting else 0.2, "scope_feasibility": 0.9},
                rank_explanation="Ranked for direct model support, bounded scope, and an interpretable validation path.",
                provider_status="degraded", provider_warnings=[warning],
            )
        )
    return ideas


def generate_thesis_ideas(profile: ThesisProfile) -> list[ThesisIdea]:
    query_parts = [profile.domain, *profile.interests[:3], *profile.objectives[:2]]
    query = " ".join(part.strip() for part in query_parts if part.strip())
    provider_warnings: list[str] = []
    oa = search_openalex(query, per_page=8)
    s2 = search_semantic_scholar(query, limit=8)
    if not oa:
        provider_warnings.append("OpenAlex returned no results; suggestions use reduced literature coverage.")
    if not s2:
        provider_warnings.append("Semantic Scholar returned no results; suggestions use reduced literature coverage.")
    papers = rank_papers(enrich_doi_metadata(dedupe(oa + s2), limit=10), query)[:10]
    registry = {
        name: {
            "description": model.description,
            "parameters": list(model.parameters),
            "outputs": model.outputs,
            "validation_status": model.validation_status,
        }
        for name, model in load_registry().items()
    }
    literature = [
        {
            "id": p.get("id"), "title": p.get("title"), "year": p.get("year"),
            "publication_type": p.get("publication_type"),
            "peer_review_confidence": p.get("peer_review_confidence"),
            "score": p.get("selection_score"),
        }
        for p in papers
    ]
    try:
        result = llm_json(
            f"Research profile:\n{profile.model_dump_json()}\n\n"
            f"Available Modelica registry:\n{json.dumps(registry)}\n\n"
            f"Initial ranked literature scan:\n{json.dumps(literature)}\n\n"
            "Generate exactly five distinct, thesis-sized ideas. Every idea must be testable with a listed model. "
            "For each include novelty, feasibility, likely contribution, concrete risks, supporting paper IDs, "
            "model names, a 0-100 rank_score, ranking_factors, and a concise rank_explanation. Use IDs idea-1..idea-5.",
            IdeaList,
            system="You are a rigorous thesis supervisor. Prefer credible, feasible, evidence-grounded ideas over fashionable breadth.",
        )
        ideas = result.ideas
    except Exception as err:
        warning = " ".join(
            [*provider_warnings, f"Idea provider unavailable ({err}); deterministic registry-grounded suggestions shown."]
        )
        return _fallback_ideas(profile, papers, warning)

    if len(ideas) < 5:
        fill_warning = "The provider returned fewer than five ideas; registry-grounded ideas filled the gap."
        provider_warnings.append(fill_warning)
        fallback = _fallback_ideas(profile, papers, fill_warning)
        known = {idea.title.lower() for idea in ideas}
        ideas.extend(idea for idea in fallback if idea.title.lower() not in known)
    ideas = sorted(ideas[:5], key=lambda idea: (-idea.rank_score, idea.title.lower()))
    valid_models = set(registry)
    paper_ids = {str(p.get("id")) for p in papers}
    for index, idea in enumerate(ideas, 1):
        idea.rank = index
        idea.model_names = [name for name in idea.model_names if name in valid_models] or list(valid_models)[:1]
        idea.supporting_paper_ids = [pid for pid in idea.supporting_paper_ids if pid in paper_ids]
        idea.provider_status = "degraded" if provider_warnings else "ok"
        idea.provider_warnings = list(dict.fromkeys([*idea.provider_warnings, *provider_warnings]))
    return ideas
