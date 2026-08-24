"""Human literature triage as a run-scoped overlay on a frozen snapshot.

Nothing here ever writes into ``data/memory/``. A memory snapshot is the record of
what the providers returned; a triage decision is the record of what one person
made of it. Keeping them apart is what lets two runs judge the same snapshot
differently and both stay reproducible, and it is why a snapshot reused by a later
run cannot silently inherit or silently lose an earlier reviewer's judgement.

The effective paper set is therefore a pure function:

    effective = apply_triage(snapshot_cards, triage)
"""

import hashlib
import json
from pathlib import Path

from rcp.config import data_dir
from rcp.objects import FieldCorrection, LiteratureTriage, PaperCard, TriageDecision, utc_now

# Fields a reviewer may correct. Deliberately excludes provenance, extraction_basis,
# peer_review_confidence, and credibility_explanation: those record where the record
# came from and how well corroborated it is, and a human editing them in place would
# destroy what "verified" means.
CORRECTABLE_FIELDS = {
    "title", "problem", "method", "metrics", "limitations", "study_conditions", "tags", "abstract",
}
LIST_FIELDS = {"metrics", "limitations", "study_conditions", "tags"}


def snapshot_cards_sha256(snapshot: Path | str) -> str:
    """Hash of the frozen card set, so a triage decision names what it judged."""
    path = Path(snapshot) / "paper_cards.json"
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def triage_path(run_id: str) -> Path:
    return data_dir() / "runs" / run_id / "literature" / "triage.json"


def write_triage(run_id: str, triage: LiteratureTriage) -> Path:
    destination = triage_path(run_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(triage.model_dump_json(indent=2))
    temporary.replace(destination)
    return destination


def load_triage(run_id: str) -> LiteratureTriage | None:
    path = triage_path(run_id)
    if not path.is_file():
        return None
    try:
        return LiteratureTriage.model_validate_json(path.read_text())
    except ValueError:
        return None


def decode_correction(field: str, encoded: str) -> str | list[str]:
    """Decode a JSON-encoded correction and type-check it against the field."""
    try:
        value = json.loads(encoded)
    except ValueError:
        value = encoded
    if field in LIST_FIELDS:
        if isinstance(value, str):
            value = [part.strip() for part in value.split(";") if part.strip()]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"correction to {field} must be a list of strings")
        return value
    if not isinstance(value, str):
        raise ValueError(f"correction to {field} must be a string")
    return value


def build_triage(
    run_id: str,
    snapshot: str,
    cards: list[PaperCard],
    *,
    included_paper_ids: list[str] | None = None,
    exclusions: list[dict] | None = None,
    notes: list[dict] | None = None,
    corrections: list[dict] | None = None,
    reviewer: str = "",
    mode: str = "human",
) -> LiteratureTriage:
    """Validate a reviewer's answer into a triage overlay, refusing bad input."""
    known = {card.id for card in cards}
    excluded: dict[str, str] = {}
    for item in exclusions or []:
        paper_id = str(item.get("paper_id") or "")
        if paper_id not in known:
            raise ValueError(f"unknown paper ID: {paper_id}")
        reason = str(item.get("reason") or "").strip()
        if not reason:
            # An unexplained exclusion is indistinguishable from discarding an
            # inconvenient result, which is exactly what this gate must not enable.
            raise ValueError(f"an exclusion requires a stated reason: {paper_id}")
        excluded[paper_id] = reason

    if included_paper_ids is None:
        included = [card.id for card in cards if card.id not in excluded]
    else:
        for paper_id in included_paper_ids:
            if paper_id not in known:
                raise ValueError(f"unknown paper ID: {paper_id}")
        included = [card.id for card in cards if card.id in set(included_paper_ids)]
        for card in cards:
            if card.id not in included and card.id not in excluded:
                raise ValueError(f"an exclusion requires a stated reason: {card.id}")

    if not included:
        raise ValueError("literature triage must retain at least one paper")

    notes_by_paper: dict[str, list[str]] = {}
    for item in notes or []:
        paper_id = str(item.get("paper_id") or "")
        if paper_id not in known:
            raise ValueError(f"unknown paper ID: {paper_id}")
        text = str(item.get("note") or "").strip()
        if text:
            notes_by_paper.setdefault(paper_id, []).append(text)

    by_id = {card.id: card for card in cards}
    records: list[FieldCorrection] = []
    for index, item in enumerate(corrections or [], 1):
        paper_id = str(item.get("paper_id") or "")
        if paper_id not in known:
            raise ValueError(f"unknown paper ID: {paper_id}")
        field = str(item.get("field") or "")
        if field not in CORRECTABLE_FIELDS:
            raise ValueError(f"field cannot be corrected by hand: {field}")
        value = decode_correction(field, str(item.get("new_value") or ""))
        records.append(FieldCorrection(
            id=f"correction:{paper_id}:{field}:{index}",
            paper_id=paper_id,
            field=field,
            previous_value=json.dumps(getattr(by_id[paper_id], field)),
            new_value=json.dumps(value),
            rationale=str(item.get("rationale") or ""),
            author=reviewer or "human",
        ))

    decisions = [
        TriageDecision(
            paper_id=card.id,
            action="include" if card.id in set(included) else "exclude",
            reason=excluded.get(card.id, ""),
            notes=notes_by_paper.get(card.id, []),
            decided_by=reviewer or ("auto" if mode == "auto" else "human"),
        )
        for card in cards
    ]

    return LiteratureTriage(
        run_id=run_id,
        memory_snapshot=snapshot,
        memory_snapshot_cards_sha256=snapshot_cards_sha256(snapshot) if snapshot else "",
        mode="auto" if mode == "auto" else "human",
        reviewer=reviewer,
        decisions=decisions,
        corrections=records,
        included_paper_ids=list(included),
        excluded_paper_ids=sorted(excluded),
        created_at=utc_now(),
    )


def auto_triage(run_id: str, snapshot: str, cards: list[PaperCard]) -> LiteratureTriage:
    """Include everything, and record plainly that no human looked.

    The warning travels into the report disclosures: an automatic run must never
    read as though a person curated the literature.
    """
    triage = build_triage(run_id, snapshot, cards, mode="auto")
    triage.warnings = [
        "No human literature triage was performed; every screened record was included "
        "automatically and no extraction was verified.",
    ]
    return triage


def apply_triage(cards: list[PaperCard], triage: LiteratureTriage | None) -> list[PaperCard]:
    """The effective paper set: included cards, with human corrections applied.

    Excluded papers are dropped entirely rather than flagged, so nothing downstream
    has to remember to filter them. A correction is attributed in field_provenance
    and never laundered into the provider provenance list.
    """
    if triage is None:
        return list(cards)

    included = set(triage.included_paper_ids)
    corrections_by_paper: dict[str, list[FieldCorrection]] = {}
    for correction in triage.corrections:
        if not correction.reverted:
            corrections_by_paper.setdefault(correction.paper_id, []).append(correction)

    notes_by_paper = {
        decision.paper_id: decision.notes for decision in triage.decisions if decision.notes
    }

    effective: list[PaperCard] = []
    for card in cards:
        if card.id not in included:
            continue
        updated = card.model_copy(deep=True)
        updated.triage_status = "included"
        updated.human_reviewed = triage.mode == "human"
        updated.reviewer_notes = notes_by_paper.get(card.id, [])
        for correction in corrections_by_paper.get(card.id, []):
            value = json.loads(correction.new_value)
            setattr(updated, correction.field, value)
            provenance = dict(updated.field_provenance)
            provenance[correction.field] = [f"human:{correction.author}", correction.id]
            updated.field_provenance = provenance
            if correction.field not in updated.human_corrected_fields:
                updated.human_corrected_fields = [*updated.human_corrected_fields, correction.field]
            updated.insufficient_evidence = [
                name for name in updated.insufficient_evidence if name != correction.field
            ]
        effective.append(updated)
    return effective
