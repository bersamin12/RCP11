import importlib.util

import pytest

from rcp.objects import (
    Claim, ClaimBundle, ExperimentResultSet, MetricComparison, PaperCard, ResultBundle,
)
from rcp.reports import (
    ReportConflict,
    export_report,
    list_revisions,
    load_report_document,
    regenerate_section,
    reorder_sections,
    restore_revision,
    seed_report_document,
    update_section,
    validate_report,
)


@pytest.fixture()
def report_env(tmp_path, monkeypatch):
    monkeypatch.setenv("RCP_DATA_DIR", str(tmp_path / "data"))
    from rcp.config import get_settings

    get_settings.cache_clear()
    bundle = ResultBundle(
        spec_id="s1", status="ok", metrics={"T_peak_degC": 27.0},
        validation_status="conceptual", warnings=["Exploratory model disclosure."],
    )
    document = seed_report_document(
        "run-1", "Cooling study",
        {"introduction": "Prior work [1].", "method": "Method.", "results_discussion": "Results.", "conclusion": "Conclusion."},
        [PaperCard(id="p1", title="Paper One", year=2024, doi="10.1/x")],
        ClaimBundle(hypothesis_id="h1", claims=[Claim(statement="Temperature remained bounded.", evidence="T_peak_degC=27")]),
        bundle,
    )
    return tmp_path, document


def test_report_edit_conflict_reorder_lock_regenerate_and_revision(report_env):
    _tmp, document = report_env
    edited = update_section("run-1", "introduction", {"content": "Manual edit [1]."}, document.version)
    assert edited.version == document.version + 1
    with pytest.raises(ReportConflict):
        update_section("run-1", "introduction", {"content": "stale edit"}, document.version)

    locked = update_section("run-1", "introduction", {"locked": True}, edited.version)
    with pytest.raises(ReportConflict):
        update_section("run-1", "introduction", {"content": "locked edit"}, locked.version)
    with pytest.raises(ReportConflict):
        regenerate_section("run-1", "introduction", locked.version, force=True)
    unlocked = update_section("run-1", "introduction", {"locked": False}, locked.version)
    with pytest.raises(ReportConflict):
        regenerate_section("run-1", "introduction", unlocked.version)
    regenerated = regenerate_section("run-1", "introduction", unlocked.version, force=True)
    assert regenerated.sections[0].content == regenerated.sections[0].generated_content

    reversed_ids = [section.id for section in reversed(regenerated.sections)]
    reordered = reorder_sections("run-1", reversed_ids, regenerated.version)
    assert [section.id for section in reordered.sections] == reversed_ids
    revisions = list_revisions("run-1")
    assert len(revisions) >= 5
    restored = restore_revision("run-1", revisions[-1].id, reordered.version)
    assert restored.version == reordered.version + 1


def test_report_validation_and_exports(report_env):
    _tmp, document = report_env
    result = validate_report(document)
    assert result["valid"] is True
    md, mime, filename = export_report(document, "md")
    assert md.startswith(b"# Cooling study") and mime.startswith("text/markdown") and filename.endswith(".md")
    if importlib.util.find_spec("docx"):
        docx, mime, filename = export_report(document, "docx")
        assert docx.startswith(b"PK") and "wordprocessingml" in mime and filename.endswith(".docx")
    if importlib.util.find_spec("reportlab"):
        pdf, mime, filename = export_report(document, "pdf")
        assert pdf.startswith(b"%PDF") and mime == "application/pdf" and filename.endswith(".pdf")


def test_legacy_markdown_migrates_only_on_first_edit_and_retains_original(tmp_path, monkeypatch):
    monkeypatch.setenv("RCP_DATA_DIR", str(tmp_path / "data"))
    from rcp.config import data_dir, get_settings

    get_settings.cache_clear()
    run_dir = data_dir() / "runs" / "legacy"
    run_dir.mkdir(parents=True)
    original = "# Legacy title\n\n## Introduction\n\nOriginal prose.\n"
    (run_dir / "report.md").write_text(original)
    transient = load_report_document("legacy")
    assert transient.migrated_from_legacy and not (run_dir / "report_document.json").exists()
    update_section("legacy", "introduction", {"content": "Edited."}, transient.version)
    assert (run_dir / "report_document.json").exists()
    assert (run_dir / "report.legacy.md").read_text() == original


def test_comparison_report_generates_evidence_linked_heatmap(tmp_path, monkeypatch):
    monkeypatch.setenv("RCP_DATA_DIR", str(tmp_path / "data"))
    from rcp.config import get_settings
    get_settings.cache_clear()
    comparison = MetricComparison(
        id="comparison:pair-1:PUE", pair_id="pair-1", metric="PUE",
        baseline_case_id="baseline", candidate_case_id="candidate",
        baseline_value=1.3, candidate_value=1.2, absolute_delta=-0.1,
        percent_delta=-7.69, direction="lower_is_better", candidate_better=True,
    )
    document = seed_report_document(
        "heatmap", "Comparison", {"results_discussion": "Result."}, [],
        ClaimBundle(hypothesis_id="h1"), ResultBundle(spec_id="s1", status="ok"),
        experiment_results=ExperimentResultSet(
            plan_id="p1", status="ok", comparisons=[comparison], cases=[ResultBundle(
                spec_id="s1", case_id="candidate", status="ok", result_file="raw.csv",
                result_file_sha256="a" * 64, result_file_integrity="verified",
            )],
        ),
    )
    assert document.figures[0].evidence_ids == [comparison.id]
    assert any(link.kind == "raw-series" for link in document.evidence_links)
    assert (tmp_path / "data" / "runs" / "heatmap" / document.figures[0].path).is_file()
    assert validate_report(document)["valid"] is True
