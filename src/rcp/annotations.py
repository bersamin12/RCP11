"""Append-only reviewer annotations on any evidence object.

These are deliberately *outside* graph state, for three reasons: a reviewer must be
able to annotate a finished, immutable run without pausing it; anything held in
RCPState is visible to the generation prompts, and a comment that silently steered
hypothesis generation would be an unrecorded, unreproducible input; and keeping
them out avoids growing the checkpoint allowlist.

They are advisory. A dispute is recorded, surfaced, and can block a supervisor's
acceptance -- but it never changes graph routing. ``evidence.review_claims`` stays
the only thing that can fail a claim closed, because a human assertion must not be
able to manufacture a passing study, nor to erase a failing one.

The log is append-only: an edit or a resolution is a new record naming what it
supersedes. Nothing is ever rewritten in place.
"""

import json
import threading
import uuid
from pathlib import Path

from rcp.config import data_dir
from rcp.objects import Annotation, utc_now

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(run_id: str) -> threading.RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(run_id, threading.RLock())


def annotations_path(run_id: str) -> Path:
    return data_dir() / "runs" / run_id / "annotations.jsonl"


def new_annotation_id() -> str:
    return f"ann-{uuid.uuid4().hex[:12]}"


def append_annotation(run_id: str, annotation: Annotation) -> Annotation:
    """Append one record. A single O_APPEND write of a short line is atomic."""
    if not annotation.author.strip():
        raise ValueError("an annotation must name its author")
    if not annotation.body.strip():
        raise ValueError("an annotation must have a body")
    path = annotations_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock_for(run_id):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(annotation.model_dump_json() + "\n")
    return annotation


def load_raw_annotations(run_id: str) -> list[Annotation]:
    """Every record ever written, in order, including superseded ones."""
    path = annotations_path(run_id)
    if not path.is_file():
        return []
    records: list[Annotation] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(Annotation.model_validate_json(line))
        except ValueError:
            continue
    return records


def load_annotations(run_id: str) -> list[Annotation]:
    """The current view: superseded records folded away, originals left on disk."""
    records = load_raw_annotations(run_id)
    superseded = {record.supersedes for record in records if record.supersedes}
    return [record for record in records if record.id not in superseded]


def resolve_annotation(run_id: str, annotation_id: str, note: str, author: str) -> Annotation:
    """Resolve by appending a superseding record, never by editing the original."""
    current = {record.id: record for record in load_annotations(run_id)}
    original = current.get(annotation_id)
    if original is None:
        raise KeyError(annotation_id)
    resolution = original.model_copy(update={
        "id": new_annotation_id(),
        "resolved": True,
        "resolution_note": note,
        "author": author or original.author,
        "created_at": utc_now(),
        "supersedes": original.id,
    })
    return append_annotation(run_id, resolution)


def open_blockers(run_id: str) -> list[Annotation]:
    return [
        record for record in load_annotations(run_id)
        if record.severity == "blocker" and not record.resolved
    ]


def annotation_digest(run_id: str) -> dict[str, str | int]:
    records = load_annotations(run_id)
    return {
        "total": len(records),
        "raw_total": len(load_raw_annotations(run_id)),
        "disputes": sum(1 for record in records if record.kind == "flag"),
        "corrections": sum(1 for record in records if record.kind == "correction"),
        "open_blockers": len(open_blockers(run_id)),
    }


def known_evidence_ids(run_id: str, state: dict) -> set[str]:
    """Every evidence identifier this run can currently resolve.

    An annotation on an unknown id would create a dangling reference, and
    ``validate_report`` already treats those as export-blocking errors.
    """
    known: set[str] = set()

    for card in state.get("paper_cards") or []:
        paper_id = card.get("id") if isinstance(card, dict) else getattr(card, "id", None)
        if paper_id:
            known.add(paper_id)
            known.add(f"paper:{paper_id}")
        findings = card.get("findings") if isinstance(card, dict) else getattr(card, "findings", [])
        for finding in findings or []:
            fid = finding.get("id") if isinstance(finding, dict) else getattr(finding, "id", None)
            if fid:
                known.add(fid)

    synthesis = state.get("research_synthesis") or {}
    if isinstance(synthesis, dict):
        for key in ("gaps", "conflicts"):
            for item in synthesis.get(key) or []:
                if item.get("id"):
                    known.add(item["id"])

    for hypothesis in state.get("hypotheses") or []:
        if isinstance(hypothesis, dict) and hypothesis.get("id"):
            known.add(f"hypothesis:{hypothesis['id']}")

    plan = state.get("experiment_plan") or {}
    if isinstance(plan, dict):
        if plan.get("id"):
            known.add(f"plan:{plan['id']}")
        protocol = plan.get("analysis_protocol") or {}
        if protocol.get("id"):
            known.add(f"protocol:{protocol['id']}")
        for case in plan.get("cases") or []:
            if case.get("id"):
                known.add(f"case:{case['id']}")

    results = state.get("experiment_results") or {}
    if isinstance(results, dict):
        for case in results.get("cases") or []:
            case_id = case.get("case_id") or case.get("spec_id")
            if case_id:
                known.add(f"case:{case_id}")
                known.add(f"raw-series:{case_id}")
        for comparison in results.get("comparisons") or []:
            if comparison.get("id"):
                known.add(comparison["id"])
            if comparison.get("metric"):
                known.add(f"metric:{comparison['metric']}")
        quality = results.get("quality_report") or {}
        for check in quality.get("checks") or []:
            if check.get("id"):
                known.add(f"quality:{check['id']}")

    bundle = state.get("claim_bundle") or {}
    if isinstance(bundle, dict):
        for index in range(1, len(bundle.get("claims") or []) + 1):
            known.add(f"claim:{index}")

    result_bundle = state.get("result_bundle") or {}
    if isinstance(result_bundle, dict):
        for metric in (result_bundle.get("metrics") or {}):
            known.add(f"metric:{metric}")

    return known


def evidence_fingerprint(evidence_id: str, state: dict) -> str:
    """A short hash of what the id points at right now.

    Several identifiers are positional -- ``claim:2`` is an index into the claim
    list -- so an annotation can outlive the object it was written about. Storing
    this lets the UI say the target moved instead of silently pointing elsewhere.
    """
    import hashlib

    target = ""
    if evidence_id.startswith("claim:"):
        try:
            index = int(evidence_id.split(":", 1)[1]) - 1
            claims = (state.get("claim_bundle") or {}).get("claims") or []
            target = json.dumps(claims[index], sort_keys=True) if 0 <= index < len(claims) else ""
        except (ValueError, TypeError):
            target = ""
    return hashlib.sha256((evidence_id + target).encode("utf-8")).hexdigest()[:16] if target else ""
