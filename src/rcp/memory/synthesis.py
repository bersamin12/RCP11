"""Validated literature synthesis for gaps, contradictions, and tensions."""

import json
import re
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from rcp.llm import llm_json
from rcp.objects import PaperCard, ResearchConflict, ResearchFinding, ResearchGap, ResearchSynthesis
from rcp.simulation.registry import load_registry


class SynthesisProposal(BaseModel):
    gaps: list[ResearchGap] = Field(default_factory=list, max_length=8)
    conflicts: list[ResearchConflict] = Field(default_factory=list, max_length=8)


INSUFFICIENT_GAP = (
    "The available records do not contain enough abstract-level evidence to establish a specific research gap."
)


def _tokens(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) > 2 and token not in {"the", "and", "for", "with", "from", "that"}
    }


def _compatible_findings(left: ResearchFinding, right: ResearchFinding) -> bool:
    """Require recognizable overlap in both intervention and outcome when supplied."""
    for first, second in ((left.intervention, right.intervention), (left.outcome, right.outcome)):
        a, b = _tokens(first), _tokens(second)
        if a and b and len(a & b) / max(1, min(len(a), len(b))) < 0.3:
            return False
    return True


def _opposing_findings(findings: list[ResearchFinding]) -> bool:
    def opposed(left: ResearchFinding, right: ResearchFinding) -> bool:
        directions = {left.direction, right.direction}
        return directions == {"increase", "decrease"} or (
            "no_change" in directions and bool(directions & {"increase", "decrease"})
        )

    return any(
        opposed(left, right) and _compatible_findings(left, right)
        for index, left in enumerate(findings)
        for right in findings[index + 1:]
        if left.paper_id != right.paper_id
    )


def _fallback_gaps(cards: list[PaperCard], valid_models: list[str]) -> list[ResearchGap]:
    gaps: list[ResearchGap] = []
    for card in cards:
        for limitation in card.limitations[:2]:
            if limitation.strip():
                gaps.append(ResearchGap(
                    id=f"gap-{len(gaps) + 1}", category="validation",
                    statement=limitation.strip(), paper_ids=[card.id],
                    model_names=valid_models[:1], confidence="low",
                    testability_note="Derived conservatively from a source-stated limitation.",
                ))
            if len(gaps) >= 5:
                return gaps
    if not gaps:
        gaps.append(ResearchGap(
            id="gap-1", category="validation",
            statement=INSUFFICIENT_GAP,
            confidence="low", testability_note="Acquire abstracts or full text before treating this as a research opportunity.",
        ))
    return gaps


def build_research_synthesis(
    topic: str, cards: list[PaperCard], source_snapshot: str = "",
    generate: Callable[..., Any] = llm_json,
) -> ResearchSynthesis:
    eligible = [card for card in cards if card.extraction_basis != "title"]
    findings = {finding.id: finding for card in eligible for finding in card.findings}
    valid_papers = {card.id: card for card in cards}
    valid_models = sorted(load_registry())
    warnings: list[str] = []
    if len(eligible) < len(cards):
        warnings.append(
            f"{len(cards) - len(eligible)} title-only paper record(s) were excluded from finding and conflict synthesis."
        )
    if not findings:
        warnings.append("No abstract-grounded findings were available; contradiction detection was skipped.")

    digest = [
        {
            "paper_id": card.id,
            "title": card.title,
            "problem": card.problem,
            "method": card.method,
            "metrics": card.metrics,
            "limitations": card.limitations,
            "study_conditions": card.study_conditions,
            "findings": [finding.model_dump(mode="json") for finding in card.findings],
        }
        for card in eligible
    ]
    try:
        proposal = generate(
            f"Research topic: {topic}\nAvailable registered models: {valid_models}\n\n"
            f"Evidence-bounded paper cards:\n{json.dumps(digest)}\n\n"
            "Identify concrete method, scenario, metric, scope, or validation gaps and cross-paper conflicts. "
            "Every item must cite only supplied paper and finding IDs. Use kind=contradiction only for directly "
            "opposing findings about compatible interventions and outcomes; use kind=tension for differences in "
            "methods, conditions, scope, or apparently inconsistent findings that are not direct opposites. "
            "Use only listed Modelica model names and IDs gap-1..gap-8 / conflict-1..conflict-8.",
            SynthesisProposal,
            system="You are a conservative scientific synthesis agent. Missing evidence must remain missing.",
        )
    except Exception as err:
        warnings.append(f"Synthesis provider unavailable ({err}); source-stated limitations were used as conservative gaps.")
        proposal = SynthesisProposal(gaps=_fallback_gaps(cards, valid_models))

    normalized_gaps: list[ResearchGap] = []
    for proposed in proposal.gaps:
        paper_ids = list(dict.fromkeys(pid for pid in proposed.paper_ids if pid in valid_papers))
        finding_ids = list(dict.fromkeys(fid for fid in proposed.finding_ids if fid in findings))
        paper_ids = list(dict.fromkeys([*paper_ids, *(findings[fid].paper_id for fid in finding_ids)]))
        if not paper_ids and proposed.statement != INSUFFICIENT_GAP:
            warnings.append(f"Dropped unsupported gap proposal: {proposed.statement[:80]}")
            continue
        normalized_gaps.append(proposed.model_copy(update={
            "id": f"gap-{len(normalized_gaps) + 1}",
            "paper_ids": paper_ids,
            "finding_ids": finding_ids,
            "model_names": list(dict.fromkeys(name for name in proposed.model_names if name in valid_models)),
        }))
    if not normalized_gaps:
        normalized_gaps = _fallback_gaps(cards, valid_models)

    normalized_conflicts: list[ResearchConflict] = []
    for proposed in proposal.conflicts:
        finding_ids = list(dict.fromkeys(fid for fid in proposed.finding_ids if fid in findings))
        cited = [findings[fid] for fid in finding_ids]
        paper_ids = list(dict.fromkeys(finding.paper_id for finding in cited))
        if len(cited) < 2 or len(paper_ids) < 2:
            warnings.append(f"Dropped conflict without two independent finding sources: {proposed.statement[:80]}")
            continue
        kind = proposed.kind
        if kind == "contradiction" and not _opposing_findings(cited):
            kind = "tension"
            warnings.append(f"Demoted an unsupported contradiction to a tension: {proposed.statement[:80]}")
        normalized_conflicts.append(proposed.model_copy(update={
            "id": f"conflict-{len(normalized_conflicts) + 1}", "kind": kind,
            "finding_ids": finding_ids, "paper_ids": paper_ids,
        }))

    by_paper: dict[str, int] = defaultdict(int)
    for finding in findings.values():
        by_paper[finding.paper_id] += 1
    return ResearchSynthesis(
        source_snapshot=source_snapshot, papers_total=len(cards),
        papers_with_abstract=len(eligible), papers_with_findings=len(by_paper),
        finding_count=len(findings), gaps=normalized_gaps, conflicts=normalized_conflicts,
        warnings=list(dict.fromkeys(warnings)),
    )
