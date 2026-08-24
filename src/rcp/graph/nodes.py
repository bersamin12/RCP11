"""Workflow nodes (PRD §5.2). Phase 1-2 nodes are full implementations; the
idea/analysis/writing nodes are functional MVP versions to close the loop, to be
deepened in Phases 3-5."""

import json
import re
import statistics
from pathlib import Path

from langgraph.types import interrupt
from pydantic import BaseModel, Field

from rcp.annotations import load_annotations
from rcp.config import data_dir, get_settings
from rcp.graph.state import RCPState
from rcp.hypotheses import rank_hypotheses
from rcp.literature.fulltext import apply_extraction, load_extractions, save_extraction
from rcp.literature.triage import apply_triage, auto_triage, build_triage, write_triage
from rcp.llm import llm_json
from rcp.memory.pipeline import build_research_memory
from rcp.memory.synthesis import build_research_synthesis
from rcp.evidence import review_claims
from rcp.objects import Claim, ClaimBundle, ExperimentSpec, Hypothesis, PaperCard, utc_now
from rcp.provenance import write_manifest
from rcp.reports import seed_report_document
from rcp.simulation.batch import benchmark_plan, plan_from_spec, run_plan, validate_plan
from rcp.simulation.collector import build_result_bundle
from rcp.simulation.registry import get_model, load_registry, validate_spec
from rcp.simulation.runner import SimulationError, run_simulation
from rcp.simulation.validation import validate_model

MAX_SPEC_ATTEMPTS = 3


def _exploratory_wording(text: str) -> str:
    replacements = {
        r"\bproves?\b": "suggests",
        r"\bdemonstrates conclusively\b": "indicates",
        r"\bvalidates?\b": "provides exploratory support for",
        r"\bconfirms?\b": "is consistent with",
        r"\bestablishes?\b": "suggests",
        r"\bgeneralizes?\b": "may apply",
    }
    cleaned = text
    for pattern, replacement in replacements.items():
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
    if cleaned.strip() and "exploratory model" not in cleaned.lower():
        cleaned = "Within this exploratory model, " + cleaned[0].lower() + cleaned[1:]
    return cleaned


def _cards(state: RCPState) -> list[PaperCard]:
    return [PaperCard.model_validate(c) if isinstance(c, dict) else c for c in state.paper_cards]


def _cards_digest(cards: list[PaperCard], limit: int = 12) -> str:
    return "\n\n".join(
        f"[{i}] {c.title} ({c.year})\nProblem: {c.problem}\nMethod: {c.method}\n"
        f"Limitations: {'; '.join(c.limitations)}"
        for i, c in enumerate(cards[:limit])
    )


def research_memory_build(state: RCPState) -> dict:
    if state.memory_snapshot:
        root = (data_dir() / "memory").resolve()
        snapshot = Path(state.memory_snapshot).resolve()
        if not snapshot.is_relative_to(root):
            raise ValueError("memory snapshot must be inside the configured memory directory")
        cards = [
            PaperCard.model_validate(item)
            for item in json.loads((snapshot / "paper_cards.json").read_text())
        ]
        themes = json.loads((snapshot / "themes.json").read_text())
        return {"paper_cards": cards, "themes": themes, "memory_snapshot": str(snapshot)}
    cards, themes, snapshot = build_research_memory(state.topic.title)
    return {
        "paper_cards": [c.model_dump() for c in cards], "themes": themes,
        "memory_snapshot": str(snapshot),
    }


def _confirm_full_text(
    run_id: str, cards: list[PaperCard], confirmations: list[dict],
    included: set[str], triage,
) -> list[PaperCard]:
    """Apply the full-text proposals a human explicitly accepted.

    This is the only path by which a card reaches extraction_basis "full_text".
    There is deliberately no automatic variant: a machine confirming a machine's
    reading would leave the tier meaning nothing.
    """
    if not confirmations:
        return cards

    by_id = {card.id: card for card in cards}
    available = {item.id: item for item in load_extractions(run_id)}
    updated = {card.id: card for card in cards}

    for entry in confirmations:
        extraction_id = str(entry.get("extraction_id") or "")
        extraction = available.get(extraction_id)
        if extraction is None:
            raise ValueError(f"unknown full-text extraction: {extraction_id}")
        if not entry.get("accepted"):
            extraction.status = "rejected"
            save_extraction(run_id, extraction)
            continue
        card = by_id.get(extraction.paper_id)
        if card is None or extraction.paper_id not in included:
            raise ValueError(
                f"cannot accept full text for a paper outside the included set: {extraction.paper_id}"
            )
        asset = card.pdf
        # Re-verify the file identity: a proposal is only about the bytes it read.
        if not asset or asset.sha256 != extraction.pdf_sha256:
            raise ValueError(
                f"the PDF for {extraction.paper_id} no longer matches the extraction it was read from"
            )
        extraction.status = "accepted"
        extraction.confirmed_by = triage.reviewer or "human"
        extraction.confirmed_at = utc_now()
        save_extraction(run_id, extraction)
        updated[card.id] = apply_extraction(
            card, extraction, entry.get("accepted_fields"), confirmed_by=extraction.confirmed_by,
        )
        triage.accepted_full_text_ids.append(extraction.id)

    return [updated[card.id] for card in cards]


def literature_triage(state: RCPState) -> dict:
    """Human gate (PRD §5.4): confirm the literature set before evidence synthesis.

    This is the only gate that runs before anything has been built on the papers,
    which is precisely why corrections and exclusions belong here. Excluding a paper
    later would orphan the gap, conflict, and claim references already built on it.
    """
    cards = _cards(state)
    if not cards:
        return {"literature_triage": None, "excluded_paper_ids": []}

    if state.auto:
        triage = auto_triage(state.run_id, state.memory_snapshot, cards)
        write_triage(state.run_id, triage)
        return {
            "paper_cards": apply_triage(cards, triage),
            "literature_triage": triage,
            "excluded_paper_ids": [],
        }

    # The payload stays lean: the manager re-serialises the whole run record on
    # every version bump and the SSE stream repeats it every 0.7s. Full abstracts
    # here would be tens of kilobytes per tick. The UI fetches detail separately.
    answer = interrupt({
        "gate": "literature_triage",
        "question": "Confirm the literature set for this run",
        "memory_snapshot": state.memory_snapshot,
        "papers": [
            {
                "id": card.id,
                "title": card.title,
                "year": card.year,
                "venue": card.venue,
                "doi": card.doi,
                "url": card.url,
                "extraction_basis": card.extraction_basis,
                "peer_review_confidence": card.peer_review_confidence,
                "selection_score": card.selection_score,
                "insufficient_evidence": card.insufficient_evidence,
                "finding_count": len(card.findings),
                "pdf_status": card.pdf.status if card.pdf else "not_attempted",
                "pdf_sha256": card.pdf.sha256 if card.pdf else "",
                "pdf_href": (
                    f"/api/literature/pdf/{card.pdf.sha256}"
                    if card.pdf and card.pdf.status == "available" and card.pdf.sha256
                    else None
                ),
                "license": card.pdf.license if card.pdf else "",
            }
            for card in cards
        ],
        "defaults": {"included_paper_ids": [card.id for card in cards]},
    })

    if isinstance(answer, dict):
        triage = build_triage(
            state.run_id, state.memory_snapshot, cards,
            included_paper_ids=answer.get("included_paper_ids"),
            exclusions=answer.get("exclusions"),
            notes=answer.get("notes"),
            corrections=answer.get("corrections"),
            reviewer=str(answer.get("reviewer") or ""),
        )
        cards = _confirm_full_text(
            state.run_id, cards, answer.get("full_text_confirmations") or [],
            set(triage.included_paper_ids), triage,
        )
    else:
        # CLI parity with the other gates, which resume with a bare string.
        text = str(answer).strip().lower()
        if text and text not in {"all", "include_all", "yes", "y", "ok"}:
            raise ValueError(f"invalid literature triage answer: {answer}")
        triage = build_triage(state.run_id, state.memory_snapshot, cards)
        triage.warnings = ["Every screened record was included without per-paper review."]

    write_triage(state.run_id, triage)
    # Hash the human input now: write_manifest is otherwise not called until
    # run_modelica, so a run that stops earlier would leave it unrecorded.
    try:
        write_manifest(state.run_id, memory_snapshot=state.memory_snapshot, literature={
            "included": len(triage.included_paper_ids),
            "excluded": len(triage.excluded_paper_ids),
            "corrections": len(triage.corrections),
            "mode": triage.mode,
            "reviewer": triage.reviewer,
        })
    except (OSError, ValueError):
        # Bookkeeping must not fail the gate, but a programming error here should
        # still surface rather than be swallowed silently.
        pass

    return {
        "paper_cards": apply_triage(cards, triage),
        "literature_triage": triage,
        "excluded_paper_ids": list(triage.excluded_paper_ids),
    }


def gap_mining(state: RCPState) -> dict:
    cards = _cards(state)
    synthesis = build_research_synthesis(
        state.topic.title, cards, state.memory_snapshot, generate=llm_json,
    )
    # State the human's effect on the evidence base here, not only in the triage
    # file, so it travels with the synthesis every consumer reads.
    if state.excluded_paper_ids:
        count = len(state.excluded_paper_ids)
        synthesis.warnings.append(
            f"{count} screened paper{'' if count == 1 else 's'} were excluded by human "
            "triage and did not contribute evidence."
        )
    elif state.literature_triage and state.literature_triage.mode == "auto":
        synthesis.warnings.extend(state.literature_triage.warnings)
    destination = data_dir() / "runs" / state.run_id / "research_synthesis.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(synthesis.model_dump_json(indent=2))
    temporary.replace(destination)
    return {
        "gaps": [gap.statement for gap in synthesis.gaps],
        "research_synthesis": synthesis,
    }


class HypothesisList(BaseModel):
    hypotheses: list[Hypothesis] = Field(min_length=1, max_length=5)


def hypothesis_gen(state: RCPState) -> dict:
    registry = load_registry()
    registry_desc = {
        name: {
            "description": model.description,
            "parameters": list(model.parameters),
            "outputs": model.outputs,
            "metric_profile": model.metric_profile,
        }
        for name, model in registry.items()
    }
    synthesis = state.research_synthesis
    result = llm_json(
        f"Research topic: {state.topic.title}\n\nValidated research synthesis:\n"
        + (synthesis.model_dump_json() if synthesis else json.dumps({"gaps": state.gaps}))
        + f"\n\nAvailable simulation models (hypotheses MUST be testable with one of these):\n"
        f"{json.dumps(registry_desc)}\n\n"
        + (f"\n\nSupervisor feedback from the preceding research cycle:\n{state.revision_feedback}" if state.revision_feedback else "")
        + "\n\nGenerate 3 structured, physically plausible hypotheses testable by simulation. "
        "Use only canonical parameter, output, metric, model, gap, conflict, and paper IDs from the supplied data. "
        "For each hypothesis include variables, expected effect, metrics, risks, model_names, and supporting IDs. "
        "Do not assign ranking scores. Give each an id like H1, H2, H3.",
        HypothesisList,
        system="You are a hypothesis-generation agent. Hypotheses must be concrete and simulation-testable.",
    )
    ranked = rank_hypotheses(result.hypotheses, synthesis, _cards(state), registry)
    if not ranked:
        raise ValueError("hypothesis generation produced no simulation-testable candidates")
    return {"hypotheses": ranked}


def route_from_entry(state: RCPState) -> str:
    return state.entry_point


def select_hypothesis(state: RCPState) -> dict:
    """Human gate 1 (PRD §5.4): hypothesis selection."""
    if state.auto:
        return {"selected_hypothesis": state.hypotheses[0]}
    answer = interrupt(
        {
            "gate": "hypothesis_selection",
            "question": "Select a hypothesis",
            "options": [{"id": h.id, "label": h.statement} for h in state.hypotheses],
        }
    )
    if isinstance(answer, dict):
        selected_id = str(answer.get("selected_id") or "")
        selected = next((hypothesis for hypothesis in state.hypotheses if hypothesis.id == selected_id), None)
        if selected is None:
            raise ValueError(f"unknown hypothesis ID: {selected_id}")
        return {"selected_hypothesis": selected}
    text = str(answer).strip()
    selected = next((hypothesis for hypothesis in state.hypotheses if hypothesis.id == text), None)
    if selected:
        return {"selected_hypothesis": selected}
    try:
        idx = int(text)
        return {"selected_hypothesis": state.hypotheses[idx]}
    except (ValueError, IndexError) as err:
        raise ValueError(f"invalid hypothesis selection: {text}") from err


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
    if spec.model_name in {"ChillerCooledIntegrated", "ChillerCooledNonIntegrated"}:
        plan = benchmark_plan(hyp.id, state.run_id)
    else:
        plan = plan_from_spec(spec, state.run_id)
    plan.validation_issues = validate_plan(plan, max_cases=get_settings().rcp_max_batch_cases)
    run_dir = data_dir() / "runs" / state.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "experiment_plan.json").write_text(plan.model_dump_json(indent=2))
    return {
        "experiment_spec": spec, "experiment_plan": plan,
        "spec_attempts": state.spec_attempts + 1, "spec_feedback": "",
        "spec_approved": False, "rollback_action": "",
    }


def approve_spec(state: RCPState) -> dict:
    """Human gate 2 (PRD §5.4): experiment spec approval, with revision loop."""
    plan = state.experiment_plan
    assert plan is not None
    if state.auto:
        if plan.validation_issues:
            raise ValueError("automatic execution refused an invalid experiment plan")
        return {"spec_approved": True}
    spec = state.experiment_spec
    assert spec is not None
    answer = interrupt(
        {
            "gate": "spec_approval",
            "question": "Approve this experiment plan?",
            "spec": spec.model_dump(),
            "plan": plan.model_dump(),
            "model_validation": {
                name: validate_model(name).model_dump() for name in sorted({case.model_name for case in plan.cases})
            },
        }
    )
    if isinstance(answer, dict):
        decision = str(answer.get("decision") or "").lower()
        if decision == "approve":
            if plan.validation_issues:
                raise ValueError("cannot approve an invalid experiment plan")
            return {"spec_approved": True}
        if decision == "abort":
            return {"spec_approved": False, "rollback_action": "abort"}
        return {"spec_approved": False, "spec_feedback": str(answer.get("feedback") or "Revision requested")}
    text = str(answer).strip()
    if text.lower() in {"yes", "y", "approve", "approved", "ok"}:
        return {"spec_approved": True}
    return {"spec_approved": False, "spec_feedback": text}


def route_after_approval(state: RCPState) -> str:
    if state.spec_approved:
        return "run"
    if state.rollback_action == "abort" or state.spec_attempts >= MAX_SPEC_ATTEMPTS:
        return "abort"
    return "revise"


def run_modelica(state: RCPState) -> dict:
    plan = state.experiment_plan
    assert plan is not None
    workdir = data_dir() / "runs" / state.run_id / "sim"
    try:
        results = run_plan(plan, workdir, runner=run_simulation)
    except SimulationError as err:
        raise RuntimeError(str(err)) from err
    bundle = next((result for result in results.cases if result.status == "ok"), results.cases[0])
    write_manifest(
        state.run_id,
        inputs={
            "topic": state.topic.model_dump(mode="json"),
            "experiment_plan": plan.model_dump(mode="json"),
        },
        memory_snapshot=state.memory_snapshot,
        model_names=[case.model_name for case in plan.cases],
    )
    return {"result_bundle": bundle, "experiment_results": results}


def route_after_run(state: RCPState) -> str:
    results = state.experiment_results
    if results and results.status == "ok":
        return "analyze"
    return "failure"


def handle_run_failure(state: RCPState) -> dict:
    results = state.experiment_results
    assert results is not None
    if state.auto:
        return {"rollback_action": "abort"}
    answer = interrupt({
        "gate": "rollback_decision",
        "question": "Some experiment cases failed. Revise, continue with partial evidence, or abort?",
        "options": [
            {"id": "revise", "label": "Revise the experiment plan"},
            {"id": "continue_partial", "label": "Continue with successful cases"},
            {"id": "abort", "label": "Abort the run"},
        ],
        "results": results.model_dump(mode="json"),
    })
    decision = str(answer.get("decision") if isinstance(answer, dict) else answer).lower()
    if decision == "continue_partial" and any(result.status == "ok" for result in results.cases):
        return {"rollback_action": "continue"}
    if decision == "revise":
        return {
            "rollback_action": "revise", "spec_approved": False,
            "spec_feedback": str(answer.get("feedback") or "Revise failed cases") if isinstance(answer, dict) else "Revise failed cases",
        }
    return {"rollback_action": "abort"}


def route_after_failure(state: RCPState) -> str:
    return {"continue": "analyze", "revise": "revise"}.get(state.rollback_action, "abort")


def abort_run(_state: RCPState) -> dict:
    raise RuntimeError("run aborted before producing scientific output")


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
    result_set = state.experiment_results
    if result_set and result_set.comparisons:
        paper_ids = [card.id for card in _cards(state)[:3]]
        by_metric = {
            metric: [item for item in result_set.comparisons if item.metric == metric]
            for metric in (state.experiment_plan.primary_metrics if state.experiment_plan else [])
        }
        generated: list[Claim] = []
        for metric, comparisons in by_metric.items():
            if not comparisons or len(generated) >= 4:
                continue
            pct_values = [item.percent_delta for item in comparisons if item.percent_delta is not None]
            median_pct = statistics.median(pct_values) if pct_values else None
            wins = sum(item.candidate_better is True for item in comparisons)
            direction_text = (
                f"a median change of {median_pct:+.2f}%" if median_pct is not None
                else "a measurable absolute change"
            )
            statement = (
                f"Across {len(comparisons)} matched cases, the integrated economizer produced "
                f"{direction_text} in {metric}; it performed better in {wins} cases under the "
                "pre-registered metric direction."
            )
            comparison_ids = [item.id for item in comparisons]
            case_ids = list(dict.fromkeys(
                case_id for item in comparisons
                for case_id in (item.baseline_case_id, item.candidate_case_id)
            ))
            generated.append(Claim(
                statement=statement,
                evidence=(
                    f"Deterministic matched comparisons for {metric}: "
                    + ", ".join(
                        f"{item.baseline_value:g}→{item.candidate_value:g}" for item in comparisons
                    )
                ),
                confidence="medium", evidence_ids=comparison_ids,
                comparison_ids=comparison_ids, case_ids=case_ids, paper_ids=paper_ids,
            ))
        warnings = list(dict.fromkeys(
            [
                *(warning for result in result_set.cases for warning in result.warnings),
                *result_set.warnings,
            ]
        ))
        for claim in generated:
            if any(result.validation_status != "validated" for result in result_set.cases):
                claim.statement = _exploratory_wording(claim.statement)
                claim.warnings = warnings
        return {"claim_bundle": ClaimBundle(
            hypothesis_id=hyp.id, claims=generated,
            summary=(
                f"Compared {len(result_set.cases)} cases across "
                f"{len(state.experiment_plan.comparison_pairs) if state.experiment_plan else 0} matched pairs."
            ),
            credibility_warnings=warnings,
        )}
    claims = llm_json(
        f"Hypothesis tested: {hyp.statement}\n"
        f"Experiment spec: {state.experiment_spec.model_dump_json() if state.experiment_spec else ''}\n"
        f"Computed metrics (ground truth — every claim must cite these): {json.dumps(bundle.metrics)}\n\n"
        f"Produce 2-4 claims about whether the results support the hypothesis, each citing "
        f"specific metric values as evidence, with physical reasoning. Use hypothesis_id '{hyp.id}'.",
        ClaimBundle,
        system=(
            "You are an analysis agent. Claims must be tied to computed metrics and physical constraints — never invent numbers. "
            + ("The model is not fully validated: use explicitly exploratory wording and do not claim proof, empirical validation, or generalizability."
               if bundle.validation_status != "validated" else "")
        ),
    )
    metric_ids = [f"metric:{name}" for name in bundle.metrics]
    for claim in claims.claims:
        normalized_evidence = []
        for evidence_id in claim.evidence_ids:
            metric_name = evidence_id.removeprefix("metric:")
            if metric_name in bundle.metrics:
                normalized_evidence.append(f"metric:{metric_name}")
        claim.evidence_ids = list(dict.fromkeys(normalized_evidence)) or metric_ids
        claim.case_ids = claim.case_ids or [bundle.case_id or bundle.spec_id]
        claim.paper_ids = claim.paper_ids or [card.id for card in _cards(state)[:3]]
        if bundle.validation_status != "validated":
            claim.statement = _exploratory_wording(claim.statement)
            if claim.confidence == "high":
                claim.confidence = "medium"
            claim.warnings = list(dict.fromkeys(claim.warnings + bundle.warnings))
    claims.credibility_warnings = list(dict.fromkeys(claims.credibility_warnings + bundle.warnings))
    return {"claim_bundle": claims}


def review_evidence(state: RCPState) -> dict:
    assert state.claim_bundle is not None
    review = review_claims(
        state.claim_bundle, state.experiment_plan, state.experiment_results, _cards(state),
        annotations=load_annotations(state.run_id),
    )
    return {"review_bundle": review, "review_attempts": state.review_attempts + 1}


def route_after_review(state: RCPState) -> str:
    if state.review_bundle and state.review_bundle.valid:
        return "draft"
    if state.review_bundle and any(
        issue.code.startswith("study-quality:") and issue.severity == "error"
        for issue in state.review_bundle.issues
    ):
        return "abort"
    if state.review_attempts < 2:
        return "reanalyze"
    return "abort"


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
        f"Experiment comparisons: {state.experiment_results.model_dump_json() if state.experiment_results else ''}\n"
        f"Approved analysis protocol: {state.experiment_plan.analysis_protocol.model_dump_json() if state.experiment_plan else ''}\n"
        f"Study quality report: {state.experiment_results.quality_report.model_dump_json() if state.experiment_results and state.experiment_results.quality_report else ''}\n"
        f"Metrics: {json.dumps(state.result_bundle.metrics if state.result_bundle else {})}\n"
        f"Model validation status: {state.result_bundle.validation_status if state.result_bundle else 'unknown'}\n"
        f"Credibility warnings: {state.result_bundle.warnings if state.result_bundle else []}\n"
        f"Claims: {claim_bundle.model_dump_json()}\n"
        f"Literature (cite as [n]):\n"
        + "\n".join(f"[{i + 1}] {c.title} ({c.year})" for i, c in enumerate(cards[:12]))
        + "\n\nWrite the four report sections in markdown (no headers — just body text). "
        "Conclusions must match the claims and metrics exactly.",
        ReportBody,
        system=(
            "You are a technical-report writing agent for data center research. "
            "When model validation is not 'validated', describe simulation findings as exploratory and never as proof, empirical validation, or generalizable fact."
        ),
    )
    if state.result_bundle and state.result_bundle.validation_status != "validated":
        body.results_discussion = _exploratory_wording(body.results_discussion)
        body.conclusion = _exploratory_wording(body.conclusion)
    document = seed_report_document(
        run_id=state.run_id,
        title=state.topic.title,
        bodies={
            "introduction": body.introduction,
            "method": (
                f"*Run `{state.run_id}` — automated draft, RCP2026/11 platform*\n\n"
                + body.method
            ),
            "results_discussion": (
                body.results_discussion
                + f"\n\n**Metrics:** `{json.dumps(state.result_bundle.metrics) if state.result_bundle else '{}'}`"
            ),
            "conclusion": body.conclusion,
        },
        cards=cards,
        claim_bundle=claim_bundle,
        result_bundle=state.result_bundle,
        experiment_plan=state.experiment_plan,
        experiment_results=state.experiment_results,
        research_synthesis=state.research_synthesis,
        selected_hypothesis=hyp,
    )
    out = data_dir() / "runs" / state.run_id / "report.md"
    # ``seed_report_document`` writes both the structured document and this
    # compatibility Markdown projection.
    assert out.exists() and document.run_id == state.run_id
    return {"report_path": str(out)}
