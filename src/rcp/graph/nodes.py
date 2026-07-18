"""Workflow nodes (PRD §5.2). Phase 1-2 nodes are full implementations; the
idea/analysis/writing nodes are functional MVP versions to close the loop, to be
deepened in Phases 3-5."""

import json
from pathlib import Path

from langgraph.types import interrupt
from pydantic import BaseModel, Field

from rcp.config import data_dir
from rcp.graph.state import RCPState
from rcp.llm import llm_json
from rcp.memory.pipeline import build_research_memory
from rcp.objects import Claim, ClaimBundle, ExperimentSpec, Hypothesis, PaperCard
from rcp.simulation.collector import build_result_bundle
from rcp.simulation.registry import get_model, load_registry, validate_spec
from rcp.simulation.runner import SimulationError, run_simulation

MAX_SPEC_ATTEMPTS = 3


def _cards(state: RCPState) -> list[PaperCard]:
    return [PaperCard.model_validate(c) if isinstance(c, dict) else c for c in state.paper_cards]


def _cards_digest(cards: list[PaperCard], limit: int = 12) -> str:
    return "\n\n".join(
        f"[{i}] {c.title} ({c.year})\nProblem: {c.problem}\nMethod: {c.method}\n"
        f"Limitations: {'; '.join(c.limitations)}"
        for i, c in enumerate(cards[:limit])
    )


def research_memory_build(state: RCPState) -> dict:
    cards, themes, _snapshot = build_research_memory(state.topic.title)
    return {"paper_cards": [c.model_dump() for c in cards], "themes": themes}


class GapList(BaseModel):
    gaps: list[str] = Field(min_length=1, max_length=8)


def gap_mining(state: RCPState) -> dict:
    result = llm_json(
        f"Research topic: {state.topic.title}\nConstraints: {state.topic.constraints}\n\n"
        f"Paper cards from the knowledge base:\n{_cards_digest(_cards(state))}\n\n"
        "Identify research gaps: methods not tried, scenarios not covered, metrics not "
        "evaluated, unexplained differences across papers. Be specific and grounded in the cards.",
        GapList,
        system="You are a research-gap mining agent for data center research.",
    )
    return {"gaps": result.gaps}


class HypothesisList(BaseModel):
    hypotheses: list[Hypothesis] = Field(min_length=1, max_length=5)


def hypothesis_gen(state: RCPState) -> dict:
    registry_desc = {name: m.description for name, m in load_registry().items()}
    result = llm_json(
        f"Research topic: {state.topic.title}\n\nIdentified gaps:\n"
        + "\n".join(f"- {g}" for g in state.gaps)
        + f"\n\nAvailable simulation models (hypotheses MUST be testable with one of these):\n"
        f"{json.dumps(registry_desc)}\n\n"
        "Generate 3 structured, physically plausible hypotheses testable by simulation. "
        "Give each an id like H1, H2, H3.",
        HypothesisList,
        system="You are a hypothesis-generation agent. Hypotheses must be concrete and simulation-testable.",
    )
    return {"hypotheses": result.hypotheses}


def select_hypothesis(state: RCPState) -> dict:
    """Human gate 1 (PRD §5.4): hypothesis selection."""
    if state.auto:
        return {"selected_hypothesis": state.hypotheses[0]}
    answer = interrupt(
        {
            "gate": "hypothesis_selection",
            "question": "Select a hypothesis by number",
            "options": [f"{h.id}: {h.statement}" for h in state.hypotheses],
        }
    )
    idx = int(str(answer).strip())
    return {"selected_hypothesis": state.hypotheses[idx]}


def spec_compile(state: RCPState) -> dict:
    """Scientific compiler (PRD M3.1-M3.2): hypothesis -> validated ExperimentSpec."""
    hyp = state.selected_hypothesis
    assert hyp is not None
    registry = load_registry()
    model_docs = {
        name: {
            "description": m.description,
            "parameters": {p: s.model_dump() for p, s in m.parameters.items()},
            "outputs": m.outputs,
            "default_stop_time": m.default_stop_time,
        }
        for name, m in registry.items()
    }
    feedback = f"\nReviewer feedback on previous spec: {state.spec_feedback}" if state.spec_feedback else ""
    spec = llm_json(
        f"Hypothesis to test:\n{hyp.model_dump_json()}\n\n"
        f"Available models:\n{json.dumps(model_docs)}\n{feedback}\n\n"
        "Compile an ExperimentSpec: pick a model, set parameter overrides (within the "
        "documented ranges, only parameters that exist), choose outputs, and a stop_time. "
        f"Use id 'spec-{state.run_id}-{state.spec_attempts + 1}' and hypothesis_id '{hyp.id}'.",
        ExperimentSpec,
        system="You are a scientific compiler mapping hypotheses to simulation-ready specs.",
    )
    violations = validate_spec(spec)
    if violations:
        # One corrective round: clamp/drop invalid entries deterministically.
        model = get_model(spec.model_name) if spec.model_name in registry else None
        if model:
            spec.parameters = {
                k: min(max(v, model.parameters[k].min), model.parameters[k].max)
                for k, v in spec.parameters.items()
                if k in model.parameters
            }
            spec.outputs = [o for o in spec.outputs if o in model.outputs] or model.outputs
            if spec.stop_time <= 0:
                spec.stop_time = model.default_stop_time
    return {"experiment_spec": spec, "spec_attempts": state.spec_attempts + 1, "spec_feedback": ""}


def approve_spec(state: RCPState) -> dict:
    """Human gate 2 (PRD §5.4): experiment spec approval, with revision loop."""
    if state.auto:
        return {"spec_approved": True}
    spec = state.experiment_spec
    assert spec is not None
    answer = interrupt(
        {
            "gate": "spec_approval",
            "question": "Approve this experiment spec? (yes / or type feedback to revise)",
            "spec": spec.model_dump(),
        }
    )
    text = str(answer).strip()
    if text.lower() in {"yes", "y", "approve", "approved", "ok"}:
        return {"spec_approved": True}
    return {"spec_approved": False, "spec_feedback": text}


def route_after_approval(state: RCPState) -> str:
    if state.spec_approved or state.spec_attempts >= MAX_SPEC_ATTEMPTS:
        return "run"
    return "revise"


def run_modelica(state: RCPState) -> dict:
    spec = state.experiment_spec
    assert spec is not None
    workdir = data_dir() / "runs" / state.run_id / "sim"
    try:
        result_csv, log = run_simulation(spec, workdir)
        bundle = build_result_bundle(spec, workdir, result_csv, log)
    except SimulationError as err:
        bundle = build_result_bundle(spec, workdir, None, "", error=str(err))
    return {"result_bundle": bundle}


def analyze_results(state: RCPState) -> dict:
    """Analysis MVP (PRD M5.1/M5.4): metrics computed numerically; claims via LLM."""
    bundle = state.result_bundle
    hyp = state.selected_hypothesis
    assert bundle is not None and hyp is not None
    if bundle.status != "ok":
        claims = ClaimBundle(
            hypothesis_id=hyp.id,
            summary=f"Simulation failed: {bundle.log_excerpt[:300]}",
        )
        return {"claim_bundle": claims}
    claims = llm_json(
        f"Hypothesis tested: {hyp.statement}\n"
        f"Experiment spec: {state.experiment_spec.model_dump_json() if state.experiment_spec else ''}\n"
        f"Computed metrics (ground truth — every claim must cite these): {json.dumps(bundle.metrics)}\n\n"
        f"Produce 2-4 claims about whether the results support the hypothesis, each citing "
        f"specific metric values as evidence, with physical reasoning. Use hypothesis_id '{hyp.id}'.",
        ClaimBundle,
        system="You are an analysis agent. Claims must be tied to the computed metrics and physical constraints — never invent numbers.",
    )
    return {"claim_bundle": claims}


def draft_report(state: RCPState) -> dict:
    """Writing MVP (PRD M6.1): assemble a markdown technical report with evidence links."""
    cards = _cards(state)
    hyp = state.selected_hypothesis
    claim_bundle = state.claim_bundle or ClaimBundle(hypothesis_id=hyp.id if hyp else "")

    class ReportBody(BaseModel):
        introduction: str
        method: str
        results_discussion: str
        conclusion: str

    body = llm_json(
        f"Topic: {state.topic.title}\n"
        f"Gaps found: {state.gaps}\n"
        f"Hypothesis: {hyp.model_dump_json() if hyp else ''}\n"
        f"Experiment spec: {state.experiment_spec.model_dump_json() if state.experiment_spec else ''}\n"
        f"Metrics: {json.dumps(state.result_bundle.metrics if state.result_bundle else {})}\n"
        f"Claims: {claim_bundle.model_dump_json()}\n"
        f"Literature (cite as [n]):\n"
        + "\n".join(f"[{i + 1}] {c.title} ({c.year})" for i, c in enumerate(cards[:12]))
        + "\n\nWrite the four report sections in markdown (no headers — just body text). "
        "Conclusions must match the claims and metrics exactly.",
        ReportBody,
        system="You are a technical-report writing agent for data center research.",
    )
    report = "\n".join(
        [
            f"# {state.topic.title}",
            f"\n*Run `{state.run_id}` — automated draft, RCP2026/11 platform*\n",
            "## Introduction\n", body.introduction,
            "\n## Method\n", body.method,
            "\n## Results & Discussion\n", body.results_discussion,
            f"\n**Metrics:** `{json.dumps(state.result_bundle.metrics) if state.result_bundle else '{}'}`\n",
            "\n## Conclusion\n", body.conclusion,
            "\n## Claims & Evidence\n",
            "\n".join(
                f"- **{c.statement}** — evidence: {c.evidence} (confidence: {c.confidence})"
                for c in claim_bundle.claims
            ),
            "\n## References\n",
            "\n".join(f"{i + 1}. {c.title} ({c.year}) {c.url or ''}" for i, c in enumerate(cards[:12])),
        ]
    )
    out = data_dir() / "runs" / state.run_id / "report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(report)
    return {"report_path": str(out)}
