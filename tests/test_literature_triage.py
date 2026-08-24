import hashlib
import json

import pytest

from rcp.literature.triage import apply_triage, auto_triage, build_triage, snapshot_cards_sha256
from rcp.memory.store import MemoryStore
from rcp.objects import PaperCard, ResearchFinding


def cards() -> list[PaperCard]:
    return [
        PaperCard(
            id="p1", title="Setpoint study", year=2021, abstract="a", problem="cooling energy",
            method="CFD", metrics=["E"], limitations=["single site"], tags=["cooling"],
            extraction_basis="abstract", selection_score=71.5,
            ranking_factors={"relevance": 0.9, "credibility": 1.0},
            findings=[ResearchFinding(id="p1:finding:1", paper_id="p1", statement="Energy fell.",
                                      direction="decrease")],
        ),
        PaperCard(
            id="p2", title="Astrophysics of quasars", year=2019, abstract="b", problem="quasars",
            method="spectroscopy", extraction_basis="abstract", selection_score=44.25,
            ranking_factors={"relevance": 0.2, "credibility": 1.0},
            findings=[ResearchFinding(id="p2:finding:1", paper_id="p2", statement="Redshift rose.",
                                      direction="increase")],
        ),
    ]


def snapshot(tmp_path):
    store = MemoryStore(tmp_path / "memory")
    return store.save_snapshot("cooling", [{"id": "p1"}, {"id": "p2"}], cards(), {"cooling": ["Setpoint study"]})


def digest_of_tree(root) -> str:
    """One hash over every file in the snapshot, plus the directory listing."""
    combined = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        combined.update(str(path.relative_to(root)).encode())
        if path.is_file():
            combined.update(path.read_bytes())
    return combined.hexdigest()


# ---------- the guarantee the whole design exists to protect ----------

def test_triage_never_mutates_the_frozen_snapshot(tmp_path):
    snap = snapshot(tmp_path)
    before = digest_of_tree(snap)

    triage = build_triage(
        "run-1", str(snap), cards(),
        included_paper_ids=["p1"],
        exclusions=[{"paper_id": "p2", "reason": "off-topic: astrophysics"}],
        corrections=[{"paper_id": "p1", "field": "method", "new_value": "CFD with k-epsilon closure",
                      "rationale": "abstract garbled the closure model"}],
        reviewer="gsw",
    )
    effective = apply_triage(cards(), triage)

    assert digest_of_tree(snap) == before, "a triage decision must not touch the frozen snapshot"
    assert [card.id for card in effective] == ["p1"]
    # And the snapshot on disk still holds the original, uncorrected text.
    stored = json.loads((snap / "paper_cards.json").read_text())
    assert stored[0]["method"] == "CFD"


def test_the_overlay_names_the_exact_card_set_it_judged(tmp_path):
    snap = snapshot(tmp_path)
    triage = build_triage("run-1", str(snap), cards())
    assert triage.memory_snapshot_cards_sha256 == snapshot_cards_sha256(snap)
    assert triage.memory_snapshot_cards_sha256


def test_two_runs_may_judge_one_snapshot_differently(tmp_path):
    snap = snapshot(tmp_path)
    keep_p1 = build_triage("run-a", str(snap), cards(), included_paper_ids=["p1"],
                           exclusions=[{"paper_id": "p2", "reason": "off-topic"}])
    keep_p2 = build_triage("run-b", str(snap), cards(), included_paper_ids=["p2"],
                           exclusions=[{"paper_id": "p1", "reason": "superseded"}])
    assert [c.id for c in apply_triage(cards(), keep_p1)] == ["p1"]
    assert [c.id for c in apply_triage(cards(), keep_p2)] == ["p2"]
    # Both judged the identical frozen card set.
    assert keep_p1.memory_snapshot_cards_sha256 == keep_p2.memory_snapshot_cards_sha256


# ---------- scores are recorded, never recomputed ----------

def test_excluding_a_paper_does_not_re_score_the_survivors(tmp_path):
    """rank_papers is set-relative, so re-ranking would move scores a human never touched."""
    original = {card.id: (card.selection_score, dict(card.ranking_factors)) for card in cards()}
    triage = build_triage("run-1", str(snapshot(tmp_path)), cards(), included_paper_ids=["p1"],
                          exclusions=[{"paper_id": "p2", "reason": "off-topic"}])
    kept = apply_triage(cards(), triage)[0]
    assert kept.selection_score == original["p1"][0]
    assert kept.ranking_factors == original["p1"][1]


# ---------- refusals ----------

def test_an_exclusion_without_a_reason_is_refused(tmp_path):
    with pytest.raises(ValueError, match="requires a stated reason"):
        build_triage("run-1", str(snapshot(tmp_path)), cards(),
                     exclusions=[{"paper_id": "p2", "reason": "  "}])


def test_dropping_a_paper_silently_is_refused(tmp_path):
    # Omitting p2 from the inclusion list without an exclusion reason is the same
    # act as an unexplained exclusion, and is refused the same way.
    with pytest.raises(ValueError, match="requires a stated reason"):
        build_triage("run-1", str(snapshot(tmp_path)), cards(), included_paper_ids=["p1"])


def test_unknown_paper_ids_are_refused(tmp_path):
    snap = str(snapshot(tmp_path))
    with pytest.raises(ValueError, match="unknown paper ID"):
        build_triage("run-1", snap, cards(), exclusions=[{"paper_id": "nope", "reason": "x"}])
    with pytest.raises(ValueError, match="unknown paper ID"):
        build_triage("run-1", snap, cards(), included_paper_ids=["ghost"])


def test_an_empty_literature_set_is_refused(tmp_path):
    with pytest.raises(ValueError, match="at least one paper"):
        build_triage("run-1", str(snapshot(tmp_path)), cards(), included_paper_ids=[],
                     exclusions=[{"paper_id": "p1", "reason": "x"}, {"paper_id": "p2", "reason": "y"}])


@pytest.mark.parametrize("field", ["provenance", "extraction_basis", "peer_review_confidence",
                                   "credibility_explanation", "selection_score"])
def test_corroboration_fields_cannot_be_hand_edited(tmp_path, field):
    """These record where a record came from and how well corroborated it is."""
    with pytest.raises(ValueError, match="cannot be corrected"):
        build_triage("run-1", str(snapshot(tmp_path)), cards(),
                     corrections=[{"paper_id": "p1", "field": field, "new_value": '"forged"'}])


# ---------- corrections are attributed, and reversible ----------

def test_a_correction_is_attributed_and_never_laundered_into_provider_provenance(tmp_path):
    triage = build_triage(
        "run-1", str(snapshot(tmp_path)), cards(), reviewer="gsw",
        corrections=[{"paper_id": "p1", "field": "method", "new_value": "CFD with k-epsilon closure"}],
    )
    card = apply_triage(cards(), triage)[0]
    assert card.method == "CFD with k-epsilon closure"
    assert card.field_provenance["method"][0] == "human:gsw"
    assert "method" in card.human_corrected_fields
    # The provider list and the corroboration verdict are untouched.
    assert card.provenance == []
    assert card.extraction_basis == "abstract"
    assert card.peer_review_confidence == "uncertain"


def test_a_correction_records_the_previous_value_byte_exactly(tmp_path):
    triage = build_triage(
        "run-1", str(snapshot(tmp_path)), cards(),
        corrections=[{"paper_id": "p1", "field": "limitations", "new_value": '["single site", "no calibration"]'}],
    )
    correction = triage.corrections[0]
    assert json.loads(correction.previous_value) == ["single site"]
    assert json.loads(correction.new_value) == ["single site", "no calibration"]


def test_a_list_field_correction_must_stay_a_list(tmp_path):
    # A bare string is accepted and split; a number is not a list of strings.
    ok = build_triage("run-1", str(snapshot(tmp_path)), cards(),
                      corrections=[{"paper_id": "p1", "field": "tags", "new_value": "cooling; setpoint"}])
    assert json.loads(ok.corrections[0].new_value) == ["cooling", "setpoint"]
    with pytest.raises(ValueError, match="must be a list of strings"):
        build_triage("run-1", str(snapshot(tmp_path)), cards(),
                     corrections=[{"paper_id": "p1", "field": "tags", "new_value": "[1, 2]"}])


# ---------- automatic mode says so ----------

def test_auto_mode_includes_everything_and_discloses_that_no_human_looked(tmp_path):
    triage = auto_triage("run-1", str(snapshot(tmp_path)), cards())
    assert triage.mode == "auto"
    assert sorted(triage.included_paper_ids) == ["p1", "p2"]
    assert triage.excluded_paper_ids == []
    assert any("No human literature triage" in warning for warning in triage.warnings)
    assert all(not card.human_reviewed for card in apply_triage(cards(), triage))


def test_no_triage_at_all_is_distinguishable_from_skipped_triage():
    """None means the gate never ran; mode="auto" means it ran and was skipped."""
    assert apply_triage(cards(), None) == cards()
