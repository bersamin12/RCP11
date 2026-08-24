from pathlib import Path

from rcp.objects import (
    Claim,
    ClaimBundle,
    ExperimentResultSet,
    MetricComparison,
    PaperCard,
    ResultBundle,
    StudyQualityCheck,
    StudyQualityReport,
)
from rcp.evidence import review_claims
from rcp.simulation.batch import (
    analysis_protocol_hash, assess_study_quality, benchmark_plan, benchmark_smoke_plan,
    compare_results, list_analysis_revisions, load_analysis_revision, run_plan, validate_plan,
)
from rcp.simulation.collector import compute_metrics, screen_power_series
from rcp.simulation.reference import compare_upstream_reference, parse_reference


def test_benchmark_plan_is_preregistered_and_valid():
    plan = benchmark_plan("H1", "run")
    assert len(plan.cases) == 18
    assert len(plan.comparison_pairs) == 9
    assert validate_plan(plan) == []
    assert {case.parameters["Q_room"] for case in plan.cases} == {400000.0, 500000.0, 600000.0}
    assert {case.parameters["T_chw_set"] for case in plan.cases} == {279.15, 281.15, 283.15}


def test_benchmark_metrics_and_comparison_math():
    series = {
        "time": [0.0, 3600.0],
        "T_room_K": [299.15, 301.15],
        "E_HVAC_J": [0.0, 3.6e6],
        "E_IT_J": [0.0, 7.2e6],
        "free_cooling_s": [0.0, 1800.0],
        "partial_mechanical_s": [0.0, 900.0],
        "full_mechanical_s": [0.0, 900.0],
        "mode_switches": [0.0, 2.0],
    }
    metrics = compute_metrics(series, "chiller_benchmark")
    assert metrics["E_HVAC_kWh"] == 1.0
    assert metrics["PUE"] == 1.5
    assert metrics["T_room_peak_degC"] == 28.0
    assert metrics["thermal_exceedance_degree_hours"] == 0.5

    screened = compute_metrics({
        **series,
        "time": [0.0, 1800.0, 3600.0],
        "P_HVAC_W": [1000.0, 1e12, 1000.0],
        "E_HVAC_J": [0.0, 1e12, 3.6e12],
        "E_IT_J": [0.0, 3.6e6, 7.2e6],
        "T_room_K": [299.15, 300.15, 301.15],
    }, "chiller_benchmark")
    assert screened["E_HVAC_kWh"] == 1.0
    assert screened["E_HVAC_raw_kWh"] == 1_000_000.0
    assert screened["power_screen_excluded_samples"] == 1.0

    plan = benchmark_smoke_plan("H1", "run")
    baseline = ResultBundle(spec_id="b", case_id="baseline-q500-t8", status="ok", metrics={"E_HVAC_kWh": 10.0})
    candidate = ResultBundle(spec_id="c", case_id="candidate-q500-t8", status="ok", metrics={"E_HVAC_kWh": 8.0})
    comparison = compare_results(plan, [baseline, candidate])[0]
    assert comparison.absolute_delta == -2.0
    assert comparison.percent_delta == -20.0
    assert comparison.candidate_better is True

    candidate.metrics["E_HVAC_kWh"] = baseline.metrics["E_HVAC_kWh"]
    tie = compare_results(plan, [baseline, candidate])[0]
    assert tie.percent_delta == 0.0
    assert tie.candidate_better is None


def test_run_plan_checkpoints_and_resumes(tmp_path: Path):
    plan = benchmark_smoke_plan("H1", "run")
    calls: list[str] = []

    def fake_runner(spec, workdir):
        calls.append(spec.id)
        workdir.mkdir(parents=True, exist_ok=True)
        result = workdir / "result_res.csv"
        result.write_text(
            '"time","T_room_K","P_HVAC_W","P_IT_W","E_HVAC_J","E_IT_J",'
            '"free_cooling_s","partial_mechanical_s","full_mechanical_s","mode_switches"\n'
            "0,298.15,100,500,0,0,0,0,0,0\n"
            "86400,299.15,100,500,8640000,43200000,43200,0,43200,2\n"
        )
        return result, "The simulation finished successfully"

    first = run_plan(plan, tmp_path, runner=fake_runner)
    second = run_plan(plan, tmp_path, runner=fake_runner)
    assert first.status == second.status == "ok"
    assert len(first.comparisons) > 0
    assert all(case.result_file_integrity == "verified" for case in first.cases)
    assert all(len(case.result_file_sha256) == 64 for case in first.cases)
    assert len(first.experiment_plan_sha256) == 64
    assert len(first.raw_dataset_sha256) == 64
    assert calls == ["baseline-q500-t8", "candidate-q500-t8"]
    revisions = list_analysis_revisions(tmp_path)
    assert len(revisions) == 1 and revisions[0].current is True
    assert load_analysis_revision(tmp_path, revisions[0].id).analysis_revision_id == first.analysis_revision_id

    revised = plan.model_copy(deep=True)
    revised.analysis_protocol = revised.analysis_protocol.model_copy(
        update={"thermal_threshold_degC": 26.5}
    )
    reanalysed = run_plan(revised, tmp_path, runner=fake_runner)
    assert calls == ["baseline-q500-t8", "candidate-q500-t8"]
    assert reanalysed.analysis_protocol_sha256 != first.analysis_protocol_sha256
    assert reanalysed.raw_dataset_sha256 == first.raw_dataset_sha256
    assert any("recomputed from stored raw series" in warning for warning in reanalysed.warnings)
    assert len(list_analysis_revisions(tmp_path)) == 2

    changed = revised.model_copy(deep=True)
    changed.cases[0].parameters["Q_room"] += 1000.0
    rerun = run_plan(changed, tmp_path, runner=fake_runner)
    assert calls == ["baseline-q500-t8", "candidate-q500-t8", "baseline-q500-t8"]
    assert rerun.raw_dataset_sha256 != reanalysed.raw_dataset_sha256
    assert any("Changed execution specifications were rerun" in warning for warning in rerun.warnings)
    assert len(list_analysis_revisions(tmp_path)) == 3


def test_run_plan_detects_raw_series_tampering(tmp_path: Path):
    plan = benchmark_smoke_plan("H1", "tamper")
    calls: list[str] = []

    def fake_runner(spec, workdir):
        calls.append(spec.id)
        workdir.mkdir(parents=True, exist_ok=True)
        result = workdir / "result_res.csv"
        result.write_text(
            '"time","T_room_K","P_HVAC_W","E_HVAC_J","E_IT_J",'
            '"free_cooling_s","partial_mechanical_s","full_mechanical_s","mode_switches"\n'
            "0,298.15,100,0,0,0,0,0,0\n"
            "86400,299.15,100,8640000,43200000,43200,0,43200,2\n"
        )
        return result, "The simulation finished successfully"

    first = run_plan(plan, tmp_path, runner=fake_runner)
    raw_path = Path(first.cases[0].result_file or "")
    raw_path.write_text(raw_path.read_text() + "\n")
    detected = run_plan(plan, tmp_path, runner=fake_runner)
    assert len(calls) == 2
    assert detected.quality_report and detected.quality_report.valid is False
    assert detected.cases[0].result_file_integrity == "mismatch"
    assert detected.cases[0].observed_result_file_sha256 != detected.cases[0].result_file_sha256
    assert any(
        check.id == "raw-series-integrity" and check.status == "failed"
        for check in detected.quality_report.checks
    )


def test_evidence_review_fails_closed_and_accepts_traceable_claim():
    plan = benchmark_smoke_plan("H1", "run")
    comparison = MetricComparison(
        id="comparison:pair-q500-t8:E_HVAC_kWh", pair_id="pair-q500-t8",
        metric="E_HVAC_kWh", baseline_case_id="baseline-q500-t8",
        candidate_case_id="candidate-q500-t8", baseline_value=10, candidate_value=8,
        absolute_delta=-2,
    )
    results = ExperimentResultSet(plan_id=plan.id, status="ok", comparisons=[comparison])
    papers = [PaperCard(id="p1", title="Paper")]
    unsupported = ClaimBundle(hypothesis_id="H1", claims=[Claim(statement="Unsupported")])
    assert review_claims(unsupported, plan, results, papers).valid is False

    supported = ClaimBundle(hypothesis_id="H1", claims=[Claim(
        statement="Supported", evidence_ids=[comparison.id], comparison_ids=[comparison.id],
        case_ids=["baseline-q500-t8", "candidate-q500-t8"], paper_ids=["p1"],
    )])
    assert review_claims(supported, plan, results, papers).valid is True

    results.quality_report = StudyQualityReport(
        valid=False,
        checks=[StudyQualityCheck(
            id="plausibility", status="failed", message="Study plausibility failed."
        )],
    )
    quality_review = review_claims(supported, plan, results, papers)
    assert quality_review.valid is False
    assert any(issue.code == "study-quality:plausibility" for issue in quality_review.issues)


def test_upstream_reference_parser_and_comparison(tmp_path: Path):
    reference = parse_reference("time=[0, 10]\nT=[1, 2, 3]\nmetadata=ignored")
    assert reference == {"time": [0.0, 10.0], "T": [1.0, 2.0, 3.0]}
    result = tmp_path / "result.csv"
    result.write_text('"time","T"\n0,1\n5,2\n10,3\n')
    report = compare_upstream_reference(result, "ChillerCooledIntegrated", reference=reference)
    assert report["status"] == "passed"
    assert report["worst_normalized_rmse"] == 0.0


def test_analysis_protocol_hash_quality_checks_and_screened_series():
    plan = benchmark_smoke_plan("H1", "quality")
    original_hash = analysis_protocol_hash(plan.analysis_protocol)
    changed = plan.analysis_protocol.model_copy(update={"thermal_threshold_degC": 26.5})
    assert analysis_protocol_hash(changed) != original_hash

    invalid = plan.model_copy(deep=True)
    invalid.analysis_protocol.comparison_relative_tolerance = -1.0
    assert "analysis protocol comparison relative tolerance must be non-negative" in validate_plan(invalid)

    screened, mask = screen_power_series(
        [0.0, 1.0, 2.0], [100.0, 1e12, 300.0], 0.0, 2_000_000.0
    )
    assert screened == [100.0, 200.0, 300.0]
    assert mask == [0.0, 1.0, 0.0]
    boundary, boundary_mask = screen_power_series(
        [0.0, 1.0, 2.0], [1e12, 100.0, 300.0], 0.0, 2_000_000.0
    )
    assert boundary == [100.0, 100.0, 300.0]
    assert boundary_mask == [1.0, 0.0, 0.0]

    metrics = {
        "E_HVAC_kWh": 2000.0, "PUE": 1.2, "T_room_peak_degC": 25.0,
        "thermal_exceedance_degree_hours": 0.0, "free_cooling_hours": 20.0,
        "partial_mechanical_hours": 3.0, "full_mechanical_hours": 1.0,
        "mode_switches": 2.0, "power_screen_excluded_samples": 1.0,
    }
    baseline = ResultBundle(
        spec_id="b", case_id="baseline-q500-t8", status="ok", sample_count=1000,
        metrics=metrics,
    )
    candidate = ResultBundle(
        spec_id="c", case_id="candidate-q500-t8", status="ok", sample_count=1000,
        metrics={**metrics, "E_HVAC_kWh": 1900.0, "PUE": 1.19},
    )
    comparisons = compare_results(plan, [baseline, candidate])
    quality = assess_study_quality(plan, [baseline, candidate], comparisons)
    assert quality.valid is True
    assert any(check.id == "power-screen-fraction" and check.status == "warning" for check in quality.checks)

    candidate.metrics["PUE"] = 4.0
    failed = assess_study_quality(plan, [baseline, candidate], compare_results(plan, [baseline, candidate]))
    assert failed.valid is False
    assert any(check.id == "pue-range" and check.status == "failed" for check in failed.checks)
