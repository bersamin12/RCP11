import pytest

from rcp.annotations import (
    annotations_path,
    append_annotation,
    known_evidence_ids,
    load_annotations,
    load_raw_annotations,
    new_annotation_id,
    open_blockers,
    resolve_annotation,
)
from rcp.evidence import review_claims
from rcp.objects import Annotation, Claim, ClaimBundle


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("RCP_DATA_DIR", str(tmp_path / "data"))
    from rcp.config import get_settings

    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def make(run_id="run-1", **overrides) -> Annotation:
    return Annotation(**{
        "id": new_annotation_id(), "run_id": run_id, "evidence_id": "claim:1",
        "kind": "comment", "severity": "info", "body": "Worth checking Table 3.",
        "author": "gsw", **overrides,
    })


# ---------- append-only ----------

def test_a_second_append_leaves_the_first_record_byte_identical(store):
    append_annotation("run-1", make(body="First remark."))
    first_line = annotations_path("run-1").read_text().splitlines()[0]

    append_annotation("run-1", make(body="Second remark."))
    lines = annotations_path("run-1").read_text().splitlines()

    assert len(lines) == 2
    assert lines[0] == first_line


def test_resolving_appends_a_superseding_record_rather_than_editing(store):
    original = append_annotation("run-1", make(kind="flag", severity="blocker",
                                               body="This claim overstates the effect."))
    before = annotations_path("run-1").read_text()

    resolution = resolve_annotation("run-1", original.id, "Rewritten in section 4.", "supervisor")

    assert annotations_path("run-1").read_text().startswith(before)
    assert resolution.supersedes == original.id
    assert resolution.resolved is True
    # The original survives in the raw log; only the folded view moves on.
    assert original.id in {record.id for record in load_raw_annotations("run-1")}
    assert original.id not in {record.id for record in load_annotations("run-1")}
    assert [record.id for record in load_annotations("run-1")] == [resolution.id]


def test_an_annotation_must_name_its_author_and_say_something(store):
    with pytest.raises(ValueError, match="author"):
        append_annotation("run-1", make(author="  "))
    with pytest.raises(ValueError, match="body"):
        append_annotation("run-1", make(body="   "))


# ---------- advisory, never decisive ----------

def bundle() -> ClaimBundle:
    return ClaimBundle(hypothesis_id="H1", claims=[
        Claim(statement="Energy fell.", evidence="e", evidence_ids=["metric:E"]),
    ])


def test_a_dispute_is_a_warning_and_never_flips_validity(store):
    """A human assertion must not manufacture a pass, nor erase a failure."""
    clean = review_claims(bundle(), None, None, [])
    disputed = review_claims(bundle(), None, None, [], annotations=[
        make(kind="flag", evidence_id="claim:1", body="The screen swallows the effect."),
    ])

    assert clean.valid == disputed.valid
    issue = next(item for item in disputed.issues if item.code.startswith("human-dispute:"))
    assert issue.severity == "warning"
    assert "gsw disputed claim:1" in issue.message
    # No new error was introduced, so routing is untouched.
    assert [i.code for i in clean.issues if i.severity == "error"] == \
           [i.code for i in disputed.issues if i.severity == "error"]


def test_a_resolved_dispute_stops_being_reported(store):
    disputed = review_claims(bundle(), None, None, [], annotations=[
        make(kind="flag", resolved=True, body="Already addressed."),
    ])
    assert not any(item.code.startswith("human-dispute:") for item in disputed.issues)


def test_a_comment_is_not_a_dispute(store):
    reviewed = review_claims(bundle(), None, None, [], annotations=[make(kind="comment")])
    assert not any(item.code.startswith("human-dispute:") for item in reviewed.issues)


def test_a_correction_is_only_ever_a_proposal(store):
    annotation = append_annotation("run-1", make(
        kind="correction", body="The method is CFD, not FEM.", proposed_value="CFD",
    ))
    assert annotation.applied is False
    assert annotation.proposed_value == "CFD"


def test_open_blockers_are_reported_until_resolved(store):
    blocker = append_annotation("run-1", make(kind="flag", severity="blocker", body="Wrong sign."))
    append_annotation("run-1", make(kind="flag", severity="concern", body="Minor."))
    assert [item.id for item in open_blockers("run-1")] == [blocker.id]

    resolve_annotation("run-1", blocker.id, "Corrected.", "supervisor")
    assert open_blockers("run-1") == []


# ---------- targets must exist ----------

def test_the_known_id_universe_covers_every_evidence_family(store):
    state = {
        "paper_cards": [{"id": "https://openalex.org/W1", "findings": [{"id": "W1:finding:1"}]}],
        "research_synthesis": {"gaps": [{"id": "gap-1"}], "conflicts": [{"id": "conflict-1"}]},
        "hypotheses": [{"id": "H1"}],
        "experiment_plan": {"id": "plan-1", "analysis_protocol": {"id": "proto-1"},
                            "cases": [{"id": "case-a"}]},
        "experiment_results": {
            "cases": [{"case_id": "case-a"}],
            "comparisons": [{"id": "cmp-1", "metric": "E_HVAC_kWh"}],
            "quality_report": {"checks": [{"id": "pue-range"}]},
        },
        "claim_bundle": {"claims": [{"statement": "a"}, {"statement": "b"}]},
        "result_bundle": {"metrics": {"T_peak_degC": 27.0}},
    }
    known = known_evidence_ids("run-1", state)
    for expected in [
        "https://openalex.org/W1", "paper:https://openalex.org/W1", "W1:finding:1",
        "gap-1", "conflict-1", "hypothesis:H1", "plan:plan-1", "protocol:proto-1",
        "case:case-a", "raw-series:case-a", "cmp-1", "metric:E_HVAC_kWh",
        "quality:pue-range", "claim:1", "claim:2", "metric:T_peak_degC",
    ]:
        assert expected in known, expected
    assert "claim:3" not in known
