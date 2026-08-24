"""Deterministic experiment expansion, batch execution, and comparisons."""

from __future__ import annotations

import json
import hashlib
import math
import re
from collections.abc import Callable
from pathlib import Path

from rcp.objects import (
    AnalysisRevision,
    AnalysisProtocol,
    ComparisonPair,
    ExperimentCase,
    ExperimentPlan,
    ExperimentResultSet,
    ExperimentSpec,
    MetricComparison,
    ResultBundle,
    StudyQualityCheck,
    StudyQualityReport,
)
from rcp.config import get_settings
from rcp.simulation.collector import build_result_bundle, experiment_spec_hash, file_fingerprint
from rcp.simulation.registry import get_model, validate_spec
from rcp.simulation.runner import SimulationError, run_compiled_simulation, run_simulation

BENCHMARK_METRICS = [
    "E_HVAC_kWh", "PUE", "T_room_peak_degC", "thermal_exceedance_degree_hours",
    "free_cooling_hours", "partial_mechanical_hours", "full_mechanical_hours",
    "mode_switches",
]

METRIC_DIRECTIONS = {
    "E_HVAC_kWh": "lower_is_better",
    "PUE": "lower_is_better",
    "T_room_peak_degC": "lower_is_better",
    "thermal_exceedance_degree_hours": "lower_is_better",
    "mode_switches": "lower_is_better",
    "free_cooling_hours": "higher_is_better",
    "partial_mechanical_hours": "neutral",
    "full_mechanical_hours": "lower_is_better",
}

METRIC_UNITS = {
    "E_HVAC_kWh": "kWh",
    "PUE": "1",
    "T_room_peak_degC": "degC",
    "thermal_exceedance_degree_hours": "K h",
    "free_cooling_hours": "h",
    "partial_mechanical_hours": "h",
    "full_mechanical_hours": "h",
    "mode_switches": "count",
}

METRIC_METHODS = {
    "E_HVAC_kWh": "Trapezoidal integration of P_HVAC_W after linear interpolation of internal screened samples and nearest-valid carry at a boundary.",
    "PUE": "(E_IT_kWh + screened E_HVAC_kWh) / E_IT_kWh.",
    "T_room_peak_degC": "Maximum T_room_K converted to degrees Celsius over the full horizon.",
    "thermal_exceedance_degree_hours": "Trapezoidal integral of room temperature above the approved threshold.",
    "free_cooling_hours": "Final upstream free-cooling duration divided by 3600.",
    "partial_mechanical_hours": "Final upstream partial-mechanical duration divided by 3600.",
    "full_mechanical_hours": "Final upstream full-mechanical duration divided by 3600.",
    "mode_switches": "Final upstream cooling-mode switch counter.",
    "E_HVAC_raw_kWh": "Final upstream cumulative HVAC energy, retained unchanged as a diagnostic.",
    "E_IT_kWh": "Final upstream cumulative IT energy divided by 3.6e6.",
    "power_screen_excluded_samples": "Count of HVAC-power samples outside the approved physical screen.",
}


def benchmark_analysis_protocol() -> AnalysisProtocol:
    return AnalysisProtocol(
        id="chiller-benchmark-analysis-v2", version="2.0",
        thermal_threshold_degC=27.0,
        hvac_power_screen_min_W=0.0, hvac_power_screen_max_W=2_000_000.0,
        power_screen_method="linear_bridge", max_power_screen_fraction=0.01,
        pue_min=1.0, pue_max=3.0, mode_hours_tolerance=0.05,
        metric_directions=METRIC_DIRECTIONS,
        metric_units=METRIC_UNITS,
        metric_methods=METRIC_METHODS,
    )


def analysis_protocol_hash(protocol: AnalysisProtocol) -> str:
    encoded = json.dumps(protocol.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def experiment_plan_hash(plan: ExperimentPlan) -> str:
    """Fingerprint the approved scientific plan, excluding derived validation messages."""
    payload = plan.model_dump(mode="json", exclude={"validation_issues"})
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def raw_dataset_hash(results: list[ResultBundle]) -> str:
    payload = {
        result.case_id or result.spec_id: {
            "status": result.status,
            "execution_spec_sha256": result.execution_spec_sha256,
            "result_file_sha256": result.result_file_sha256,
            "result_file_bytes": result.result_file_bytes,
        }
        for result in sorted(results, key=lambda item: item.case_id or item.spec_id)
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def analysis_revision_hash(plan_sha256: str, dataset_sha256: str) -> str:
    return hashlib.sha256(f"{plan_sha256}:{dataset_sha256}".encode()).hexdigest()


def benchmark_plan(hypothesis_id: str, run_id: str) -> ExperimentPlan:
    """The preregistered 3x3 integrated-vs-non-integrated milestone study."""
    cases: list[ExperimentCase] = []
    pairs: list[ComparisonPair] = []
    outputs = get_model("ChillerCooledIntegrated").outputs
    for load_kw in (400, 500, 600):
        for setpoint_c in (6, 8, 10):
            factors = {"Q_room_kW": float(load_kw), "T_chw_set_degC": float(setpoint_c)}
            suffix = f"q{load_kw}-t{setpoint_c}"
            baseline_id = f"baseline-{suffix}"
            candidate_id = f"candidate-{suffix}"
            common = {
                "parameters": {
                    "Q_room": float(load_kw * 1000),
                    "T_chw_set": float(setpoint_c + 273.15),
                },
                "outputs": outputs,
                "stop_time": 86400.0,
                "intervals": 1440,
                "factor_values": factors,
            }
            cases.extend([
                ExperimentCase(
                    id=baseline_id, label=f"Non-integrated · {load_kw} kW · {setpoint_c} °C",
                    role="baseline", model_name="ChillerCooledNonIntegrated", **common,
                ),
                ExperimentCase(
                    id=candidate_id, label=f"Integrated · {load_kw} kW · {setpoint_c} °C",
                    role="candidate", model_name="ChillerCooledIntegrated", **common,
                ),
            ])
            pairs.append(ComparisonPair(
                id=f"pair-{suffix}", baseline_case_id=baseline_id,
                candidate_case_id=candidate_id, label=f"{load_kw} kW · {setpoint_c} °C",
            ))
    return ExperimentPlan(
        id=f"plan-{run_id}-benchmark", hypothesis_id=hypothesis_id, cases=cases,
        comparison_pairs=pairs, primary_metrics=BENCHMARK_METRICS,
        analysis_protocol=benchmark_analysis_protocol(),
        description=(
            "Compare integrated and non-integrated primary-secondary waterside economizers "
            "over room load and chilled-water setpoint."
        ),
    )


def benchmark_smoke_plan(hypothesis_id: str, run_id: str) -> ExperimentPlan:
    full = benchmark_plan(hypothesis_id, run_id)
    keep = {"baseline-q500-t8", "candidate-q500-t8"}
    full.id = f"plan-{run_id}-benchmark-smoke"
    full.cases = [case for case in full.cases if case.id in keep]
    full.comparison_pairs = [
        pair for pair in full.comparison_pairs
        if pair.baseline_case_id in keep and pair.candidate_case_id in keep
    ]
    full.description = "Default-load smoke comparison for the pinned ChillerCooled benchmark."
    return full


def plan_from_spec(spec: ExperimentSpec, run_id: str) -> ExperimentPlan:
    """Backward-compatible one-case plan for models without a comparison template."""
    case = ExperimentCase(
        id=spec.id, label=spec.description or spec.model_name, role="candidate",
        model_name=spec.model_name, parameters=spec.parameters, outputs=spec.outputs,
        stop_time=spec.stop_time, intervals=spec.intervals,
    )
    return ExperimentPlan(
        id=f"plan-{run_id}", hypothesis_id=spec.hypothesis_id, cases=[case],
        primary_metrics=[], description=spec.description,
    )


def validate_plan(plan: ExperimentPlan, max_cases: int = 18) -> list[str]:
    issues: list[str] = []
    ids = [case.id for case in plan.cases]
    if not ids:
        issues.append("experiment plan has no cases")
    if len(ids) != len(set(ids)):
        issues.append("case IDs must be unique")
    if len(ids) > max_cases:
        issues.append(f"experiment plan has {len(ids)} cases; limit is {max_cases}")
    known = set(ids)
    for case in plan.cases:
        spec = case_to_spec(case, plan.hypothesis_id)
        issues.extend(f"{case.id}: {issue}" for issue in validate_spec(spec))
    pair_ids = [pair.id for pair in plan.comparison_pairs]
    if len(pair_ids) != len(set(pair_ids)):
        issues.append("comparison pair IDs must be unique")
    for pair in plan.comparison_pairs:
        if pair.baseline_case_id not in known or pair.candidate_case_id not in known:
            issues.append(f"{pair.id}: comparison references an unknown case")
        if pair.baseline_case_id == pair.candidate_case_id:
            issues.append(f"{pair.id}: baseline and candidate must differ")
    protocol = plan.analysis_protocol
    if protocol.hvac_power_screen_min_W >= protocol.hvac_power_screen_max_W:
        issues.append("analysis protocol HVAC power screen must have min < max")
    if not 0 <= protocol.max_power_screen_fraction <= 1:
        issues.append("analysis protocol max_power_screen_fraction must be between 0 and 1")
    if protocol.pue_min >= protocol.pue_max:
        issues.append("analysis protocol PUE range must have min < max")
    if protocol.mode_hours_tolerance < 0:
        issues.append("analysis protocol mode-hours tolerance must be non-negative")
    if protocol.comparison_absolute_tolerance < 0:
        issues.append("analysis protocol comparison absolute tolerance must be non-negative")
    if protocol.comparison_relative_tolerance < 0:
        issues.append("analysis protocol comparison relative tolerance must be non-negative")
    for metric in plan.primary_metrics:
        if metric not in protocol.metric_directions:
            issues.append(f"analysis protocol has no direction for primary metric {metric}")
        if metric not in protocol.metric_methods:
            issues.append(f"analysis protocol has no method for primary metric {metric}")
    return issues


def case_to_spec(case: ExperimentCase, hypothesis_id: str) -> ExperimentSpec:
    return ExperimentSpec(
        id=case.id, hypothesis_id=hypothesis_id, model_name=case.model_name,
        parameters=case.parameters, outputs=case.outputs, stop_time=case.stop_time,
        intervals=case.intervals, description=case.label,
    )


def compare_results(plan: ExperimentPlan, results: list[ResultBundle]) -> list[MetricComparison]:
    by_case = {result.case_id or result.spec_id: result for result in results if result.status == "ok"}
    comparisons: list[MetricComparison] = []
    for pair in plan.comparison_pairs:
        baseline = by_case.get(pair.baseline_case_id)
        candidate = by_case.get(pair.candidate_case_id)
        if not baseline or not candidate:
            continue
        metrics = plan.primary_metrics or sorted(set(baseline.metrics) & set(candidate.metrics))
        for metric in metrics:
            if metric not in baseline.metrics or metric not in candidate.metrics:
                continue
            base_value = baseline.metrics[metric]
            cand_value = candidate.metrics[metric]
            delta = cand_value - base_value
            pct = None if base_value == 0 else delta / abs(base_value) * 100
            direction = plan.analysis_protocol.metric_directions.get(
                metric, METRIC_DIRECTIONS.get(metric, "neutral")
            )
            better = None
            tied = math.isclose(
                cand_value, base_value,
                rel_tol=plan.analysis_protocol.comparison_relative_tolerance,
                abs_tol=plan.analysis_protocol.comparison_absolute_tolerance,
            )
            if direction == "lower_is_better" and not tied:
                better = cand_value < base_value
            elif direction == "higher_is_better" and not tied:
                better = cand_value > base_value
            comparisons.append(MetricComparison(
                id=f"comparison:{pair.id}:{metric}", pair_id=pair.id, metric=metric,
                baseline_case_id=pair.baseline_case_id, candidate_case_id=pair.candidate_case_id,
                baseline_value=base_value, candidate_value=cand_value,
                absolute_delta=delta, percent_delta=pct, direction=direction,
                candidate_better=better,
                unit=plan.analysis_protocol.metric_units.get(metric, METRIC_UNITS.get(metric, "")),
            ))
    return comparisons


def assess_study_quality(
    plan: ExperimentPlan, results: list[ResultBundle], comparisons: list[MetricComparison]
) -> StudyQualityReport:
    protocol = plan.analysis_protocol
    checks: list[StudyQualityCheck] = []
    successful = [result for result in results if result.status == "ok"]
    successful_ids = {result.case_id or result.spec_id for result in successful}
    failed_ids = [result.case_id or result.spec_id for result in results if result.status != "ok"]
    checks.append(StudyQualityCheck(
        id="case-execution",
        status="failed" if not successful else "warning" if failed_ids else "passed",
        message=("No cases completed successfully." if not successful else
                 f"{len(failed_ids)} declared cases failed." if failed_ids else
                 "All declared cases completed successfully."),
        observed=f"{len(successful)}/{len(plan.cases)} successful",
        expected=f"{len(plan.cases)}/{len(plan.cases)} successful", case_ids=failed_ids,
    ))

    missing_metrics = {
        result.case_id or result.spec_id: [
            metric for metric in plan.primary_metrics if metric not in result.metrics
        ]
        for result in successful
    }
    missing_metrics = {case_id: metrics for case_id, metrics in missing_metrics.items() if metrics}
    checks.append(StudyQualityCheck(
        id="primary-metric-completeness",
        status="failed" if missing_metrics else "passed",
        message=(f"Primary metrics are missing: {missing_metrics}" if missing_metrics else
                 "Every successful case contains all primary metrics."),
        observed=str(missing_metrics or "complete"), expected="all approved primary metrics",
        case_ids=list(missing_metrics),
    ))

    complete_pairs = [
        pair for pair in plan.comparison_pairs
        if pair.baseline_case_id in successful_ids and pair.candidate_case_id in successful_ids
    ]
    expected_comparisons = len(complete_pairs) * len(plan.primary_metrics)
    pair_status = "passed"
    if plan.comparison_pairs and not complete_pairs:
        pair_status = "failed"
    elif len(comparisons) != expected_comparisons:
        pair_status = "failed" if protocol.require_complete_pair_metrics else "warning"
    elif len(complete_pairs) != len(plan.comparison_pairs):
        pair_status = "warning"
    checks.append(StudyQualityCheck(
        id="matched-comparison-completeness", status=pair_status,
        message=(
            f"{len(complete_pairs)} of {len(plan.comparison_pairs)} matched pairs produced "
            f"{len(comparisons)} of {expected_comparisons} expected comparisons."
        ) if plan.comparison_pairs else "This is a single-case plan with no matched comparisons.",
        observed=f"{len(comparisons)} comparisons", expected=f"{expected_comparisons} comparisons",
    ))

    non_finite = [
        result.case_id or result.spec_id for result in successful
        if any(not math.isfinite(value) for value in result.metrics.values())
    ]
    checks.append(StudyQualityCheck(
        id="finite-metrics", status="failed" if non_finite else "passed",
        message="Non-finite metrics were detected." if non_finite else "All computed metrics are finite.",
        observed=str(non_finite or "finite"), expected="finite", case_ids=non_finite,
    ))

    integrity_mismatches = [
        result.case_id or result.spec_id for result in successful
        if result.result_file_integrity == "mismatch"
    ]
    unverified_files = [
        result.case_id or result.spec_id for result in successful
        if result.result_file_integrity == "unverified"
    ]
    checks.append(StudyQualityCheck(
        id="raw-series-integrity",
        status="failed" if integrity_mismatches else "warning" if unverified_files else "passed",
        message=(
            "Stored raw-series content no longer matches its recorded SHA-256 fingerprint."
            if integrity_mismatches else
            "Some raw-series files predate content fingerprinting."
            if unverified_files else
            "Every successful case matched its recorded raw-series SHA-256 fingerprint at analysis."
        ),
        observed=str(integrity_mismatches or unverified_files or "verified"),
        expected="all successful raw-series files verified",
        case_ids=integrity_mismatches or unverified_files,
    ))

    pue_outliers = [
        result.case_id or result.spec_id for result in successful
        if "PUE" in result.metrics and not (protocol.pue_min <= result.metrics["PUE"] <= protocol.pue_max)
    ]
    if any("PUE" in result.metrics for result in successful):
        checks.append(StudyQualityCheck(
            id="pue-range", status="failed" if pue_outliers else "passed",
            message="PUE leaves the approved plausibility range." if pue_outliers else "PUE remains inside the approved plausibility range.",
            observed=str(pue_outliers or "within range"),
            expected=f"{protocol.pue_min} <= PUE <= {protocol.pue_max}", case_ids=pue_outliers,
        ))

    screened = []
    excessive_screening = []
    for result in successful:
        excluded = result.metrics.get("power_screen_excluded_samples", 0.0)
        if excluded > 0:
            case_id = result.case_id or result.spec_id
            fraction = excluded / result.sample_count if result.sample_count else 1.0
            screened.append(f"{case_id}={fraction:.3%}")
            if fraction > protocol.max_power_screen_fraction:
                excessive_screening.append(case_id)
    if any("power_screen_excluded_samples" in result.metrics for result in successful):
        checks.append(StudyQualityCheck(
            id="power-screen-fraction",
            status="failed" if excessive_screening else "warning" if screened else "passed",
            message=("Power screening exceeds the approved fraction." if excessive_screening else
                     "Approved power screening was applied and remains below its maximum fraction." if screened else
                     "No HVAC power samples required screening."),
            observed=", ".join(screened) or "0%", expected=f"<= {protocol.max_power_screen_fraction:.3%}",
            case_ids=excessive_screening,
        ))

    mode_failures = []
    for result in successful:
        keys = ("free_cooling_hours", "partial_mechanical_hours", "full_mechanical_hours")
        if all(key in result.metrics for key in keys):
            case = next((item for item in plan.cases if item.id == (result.case_id or result.spec_id)), None)
            expected_hours = case.stop_time / 3600 if case else 0.0
            observed_hours = sum(result.metrics[key] for key in keys)
            if abs(observed_hours - expected_hours) > protocol.mode_hours_tolerance:
                mode_failures.append(result.case_id or result.spec_id)
    if any("free_cooling_hours" in result.metrics for result in successful):
        checks.append(StudyQualityCheck(
            id="cooling-mode-time-balance", status="failed" if mode_failures else "passed",
            message="Cooling-mode durations do not sum to the case horizon." if mode_failures else "Cooling-mode durations balance to every case horizon.",
            observed=str(mode_failures or "balanced"),
            expected=f"absolute error <= {protocol.mode_hours_tolerance} h", case_ids=mode_failures,
        ))

    monotonic_groups = 0
    monotonic_failures: list[str] = []
    if protocol.require_it_energy_load_monotonicity:
        by_group: dict[tuple[str, float], list[ResultBundle]] = {}
        for result in successful:
            if "E_IT_kWh" not in result.metrics or "Q_room" not in result.parameters:
                continue
            key = (result.model_name, result.parameters.get("T_chw_set", 0.0))
            by_group.setdefault(key, []).append(result)
        for group in by_group.values():
            if len(group) < 2:
                continue
            monotonic_groups += 1
            ordered = sorted(group, key=lambda item: item.parameters["Q_room"])
            for lower, higher in zip(ordered, ordered[1:]):
                if higher.metrics["E_IT_kWh"] + protocol.comparison_absolute_tolerance < lower.metrics["E_IT_kWh"]:
                    monotonic_failures.extend([
                        lower.case_id or lower.spec_id, higher.case_id or higher.spec_id,
                    ])
    if monotonic_groups:
        checks.append(StudyQualityCheck(
            id="it-energy-load-monotonicity",
            status="failed" if monotonic_failures else "passed",
            message=("IT energy decreases as declared room load increases." if monotonic_failures else
                     "IT energy is non-decreasing with room load in every model/setpoint group."),
            observed=f"{monotonic_groups} groups checked",
            expected="E_IT(Q_room higher) >= E_IT(Q_room lower)",
            case_ids=list(dict.fromkeys(monotonic_failures)),
        ))

    valid = not any(check.status == "failed" for check in checks)
    return StudyQualityReport(
        valid=valid, protocol_id=protocol.id,
        protocol_sha256=analysis_protocol_hash(protocol), checks=checks,
    )


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2))
    temporary.replace(path)


def _result_revision_id(results: ExperimentResultSet) -> str:
    if results.analysis_revision_id:
        return results.analysis_revision_id
    if results.experiment_plan_sha256 and results.raw_dataset_sha256:
        return analysis_revision_hash(
            results.experiment_plan_sha256, results.raw_dataset_sha256
        )
    encoded = json.dumps(results.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _archive_result_set(workdir: Path, results: ExperimentResultSet) -> None:
    """Persist one immutable result snapshot per plan/dataset analysis identity."""
    if results.status == "pending":
        return
    revision_id = _result_revision_id(results)
    destination = workdir / "analysis_revisions" / f"{revision_id}.json"
    if destination.exists():
        return
    archived = results.model_copy(update={"analysis_revision_id": revision_id})
    _atomic_write(destination, archived.model_dump(mode="json"))


def _revision_summary(
    results: ExperimentResultSet, revision_id: str, current: bool
) -> AnalysisRevision:
    return AnalysisRevision(
        id=revision_id,
        plan_id=results.plan_id,
        experiment_plan_sha256=results.experiment_plan_sha256,
        protocol_id=results.quality_report.protocol_id if results.quality_report else "",
        protocol_sha256=results.analysis_protocol_sha256,
        raw_dataset_sha256=results.raw_dataset_sha256,
        generated_at=results.generated_at,
        status=results.status,  # type: ignore[arg-type]
        quality_valid=results.quality_report.valid if results.quality_report else None,
        case_count=len(results.cases), comparison_count=len(results.comparisons),
        current=current, warnings=results.warnings,
    )


def list_analysis_revisions(workdir: Path) -> list[AnalysisRevision]:
    current: ExperimentResultSet | None = None
    current_path = workdir / "experiment_results.json"
    if current_path.exists():
        try:
            candidate = ExperimentResultSet.model_validate_json(current_path.read_text())
            if candidate.status != "pending":
                current = candidate
        except ValueError:
            pass
    current_id = _result_revision_id(current) if current else ""
    revisions: dict[str, AnalysisRevision] = {}
    for path in sorted((workdir / "analysis_revisions").glob("*.json")):
        try:
            result = ExperimentResultSet.model_validate_json(path.read_text())
            revisions[path.stem] = _revision_summary(result, path.stem, path.stem == current_id)
        except ValueError:
            continue
    if current:
        revisions[current_id] = _revision_summary(current, current_id, True)
    return sorted(
        revisions.values(), key=lambda item: (item.generated_at, item.id), reverse=True
    )


def load_analysis_revision(workdir: Path, revision_id: str) -> ExperimentResultSet:
    if not re.fullmatch(r"[0-9a-f]{64}", revision_id):
        raise KeyError(revision_id)
    current_path = workdir / "experiment_results.json"
    if current_path.exists():
        current = ExperimentResultSet.model_validate_json(current_path.read_text())
        if current.status != "pending" and _result_revision_id(current) == revision_id:
            return current
    path = workdir / "analysis_revisions" / f"{revision_id}.json"
    if not path.exists():
        raise KeyError(revision_id)
    return ExperimentResultSet.model_validate_json(path.read_text())


def _transient_failure(error: SimulationError) -> bool:
    text = str(error).lower()
    return any(marker in text for marker in (
        "timed out", "temporarily unavailable", "connection reset", "docker daemon",
        "resource temporarily unavailable",
    ))


def _fresh_case_dir(workdir: Path, case_id: str, spec_sha256: str) -> Path:
    """Choose a new execution directory without overwriting a prior attempt."""
    root = workdir / "cases" / case_id
    candidate = root / spec_sha256
    if not candidate.exists():
        return candidate
    attempt = 2
    while (root / f"{spec_sha256}-attempt-{attempt}").exists():
        attempt += 1
    return root / f"{spec_sha256}-attempt-{attempt}"


def run_plan(
    plan: ExperimentPlan,
    workdir: Path,
    runner: Callable[[ExperimentSpec, Path], tuple[Path, str]] = run_simulation,
) -> ExperimentResultSet:
    """Execute pending cases sequentially and checkpoint after every case."""
    issues = validate_plan(plan, max_cases=get_settings().rcp_max_batch_cases)
    if issues:
        raise SimulationError("invalid experiment plan: " + "; ".join(issues))
    result_path = workdir / "experiment_results.json"
    plan_sha256 = experiment_plan_hash(plan)
    protocol_sha256 = analysis_protocol_hash(plan.analysis_protocol)
    existing: dict[str, ResultBundle] = {}
    previous_protocol_sha256 = ""
    previous_plan_sha256 = ""
    if result_path.exists():
        try:
            saved = ExperimentResultSet.model_validate_json(result_path.read_text())
            if saved.plan_id == plan.id:
                _archive_result_set(workdir, saved)
                existing = {result.case_id or result.spec_id: result for result in saved.cases}
                previous_protocol_sha256 = saved.analysis_protocol_sha256
                previous_plan_sha256 = saved.experiment_plan_sha256
        except ValueError:
            existing = {}
    results: list[ResultBundle] = []
    changed_specs: list[str] = []
    compiled_templates: dict[tuple[str, float, int], Path] = {}
    for case in plan.cases:
        spec = case_to_spec(case, plan.hypothesis_id)
        spec_sha256 = experiment_spec_hash(spec)
        template_key = (case.model_name, case.stop_time, case.intervals)
        previous = existing.get(case.id)
        legacy_spec_match = bool(
            previous and not previous.execution_spec_sha256
            and previous.model_name == spec.model_name
            and previous.parameters == spec.parameters
        )
        spec_matches = bool(
            previous and (
                previous.execution_spec_sha256 == spec_sha256 or legacy_spec_match
            )
        )
        previous_file = Path(previous.result_file) if previous and previous.result_file else None
        if (
            previous and previous.status == "ok" and previous_file
            and previous_file.exists() and spec_matches
        ):
            observed_sha256, observed_bytes = file_fingerprint(previous_file)
            if previous.result_file_sha256 and previous.result_file_sha256 != observed_sha256:
                bundle = previous.model_copy(deep=True)
                bundle.observed_result_file_sha256 = observed_sha256
                bundle.result_file_integrity = "mismatch"
                bundle.warnings = list(dict.fromkeys([
                    *bundle.warnings,
                    "Raw result integrity failure: the CSV content differs from its recorded SHA-256 fingerprint.",
                ]))
            elif previous_protocol_sha256 == protocol_sha256 and previous.result_file_sha256:
                bundle = previous.model_copy(deep=True)
                bundle.execution_spec_sha256 = spec_sha256
                bundle.observed_result_file_sha256 = observed_sha256
                bundle.result_file_bytes = observed_bytes
                bundle.result_file_integrity = "verified"
            else:
                bundle = build_result_bundle(
                    spec, Path(previous.workdir), previous_file,
                    "Metrics recomputed from the stored raw series under the current analysis protocol.",
                    case_id=case.id, analysis_protocol=plan.analysis_protocol,
                )
                if not previous.result_file_sha256:
                    bundle.warnings = list(dict.fromkeys([
                        *bundle.warnings,
                        "A SHA-256 fingerprint was established while migrating this legacy raw result.",
                    ]))
            results.append(bundle)
            previous_workdir = Path(previous.workdir)
            if (
                bundle.result_file_integrity == "verified" and runner is run_simulation
                and (previous_workdir / "result").exists()
            ):
                compiled_templates.setdefault(template_key, previous_workdir)
            continue
        if previous and not spec_matches:
            changed_specs.append(case.id)
        case_dir = _fresh_case_dir(workdir, case.id, spec_sha256)
        try:
            active_runner = runner
            template = compiled_templates.get(template_key)
            if runner is run_simulation and template is not None:
                active_runner = lambda pending_spec, pending_dir: run_compiled_simulation(
                    pending_spec, template, pending_dir
                )
            try:
                csv_path, log = active_runner(spec, case_dir)
            except SimulationError as first_error:
                if not _transient_failure(first_error):
                    raise
                csv_path, log = active_runner(spec, case_dir)
            bundle = build_result_bundle(
                spec, case_dir, csv_path, log, case_id=case.id,
                analysis_protocol=plan.analysis_protocol,
            )
            if runner is run_simulation and template is None and (case_dir / "result").exists():
                compiled_templates[template_key] = case_dir
        except SimulationError as err:
            bundle = build_result_bundle(
                spec, case_dir, None, "", error=str(err), case_id=case.id,
                analysis_protocol=plan.analysis_protocol,
            )
        results.append(bundle)
        partial = ExperimentResultSet(
            plan_id=plan.id, status="pending", cases=results,
            experiment_plan_sha256=plan_sha256,
            analysis_protocol_sha256=protocol_sha256,
            analysis_protocol_snapshot=plan.analysis_protocol,
        )
        _atomic_write(result_path, partial.model_dump(mode="json"))
    successful = sum(result.status == "ok" for result in results)
    status = "ok" if successful == len(results) else "partial" if successful else "failed"
    warnings = [f"{len(results) - successful} of {len(results)} cases failed"] if successful != len(results) else []
    comparisons = compare_results(plan, results)
    quality = assess_study_quality(plan, results, comparisons)
    if previous_protocol_sha256 and previous_protocol_sha256 != protocol_sha256:
        warnings.append(
            "Metrics were recomputed from stored raw series because the approved analysis protocol changed."
        )
    if previous_plan_sha256 and previous_plan_sha256 != plan_sha256:
        warnings.append(
            "The approved experiment plan changed; this result has a distinct immutable analysis revision."
        )
    if changed_specs:
        warnings.append(
            "Changed execution specifications were rerun in new immutable case directories: "
            + ", ".join(changed_specs)
        )
    warnings.extend(check.message for check in quality.checks if check.status == "warning")
    dataset_sha256 = raw_dataset_hash(results)
    revision_id = analysis_revision_hash(plan_sha256, dataset_sha256)
    final = ExperimentResultSet(
        plan_id=plan.id, status=status, cases=results,
        comparisons=comparisons,
        experiment_plan_sha256=plan_sha256,
        analysis_protocol_sha256=protocol_sha256,
        analysis_protocol_snapshot=plan.analysis_protocol,
        raw_dataset_sha256=dataset_sha256,
        analysis_revision_id=revision_id,
        quality_report=quality, warnings=list(dict.fromkeys(warnings)),
    )
    _atomic_write(result_path, final.model_dump(mode="json"))
    _archive_result_set(workdir, final)
    return final
