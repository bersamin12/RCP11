"""Result collector: unify simulation outputs into a ResultBundle (PRD M4.4, M5.1)."""

import csv
import hashlib
import json
import math
from pathlib import Path

from rcp.objects import AnalysisProtocol, ExperimentSpec, ResultBundle
from rcp.simulation.registry import get_model
from rcp.simulation.validation import runtime_plausibility_warnings


def file_fingerprint(path: Path) -> tuple[str, int]:
    """Return a streaming SHA-256 and byte count for an immutable raw artifact."""
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def experiment_spec_hash(spec: ExperimentSpec) -> str:
    encoded = json.dumps(spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def load_series(csv_path: Path) -> dict[str, list[float]]:
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        series: dict[str, list[float]] = {name.strip('"'): [] for name in reader.fieldnames or []}
        for row in reader:
            for name, value in row.items():
                series[name.strip('"')].append(float(value))
    return series


def _steady_window(values: list[float], fraction: float = 0.2) -> list[float]:
    n = max(1, int(len(values) * fraction))
    return values[-n:]


def _trapezoid_positive_hours(time: list[float], values: list[float], threshold: float) -> float:
    if len(time) != len(values) or len(time) < 2:
        return 0.0
    total = 0.0
    for t0, t1, v0, v1 in zip(time, time[1:], values, values[1:]):
        exceedance = (max(0.0, v0 - threshold) + max(0.0, v1 - threshold)) / 2
        total += exceedance * max(0.0, t1 - t0)
    return total / 3600


def _bounded_energy_kwh(
    time: list[float], power: list[float], minimum: float, maximum: float
) -> tuple[float | None, int]:
    """Integrate after bridging non-physical event impulses.

    OpenModelica can emit short, enormous mover-power impulses exactly at mode
    transitions in this Buildings example.  The raw upstream integral remains
    available as a diagnostic; the benchmark metric linearly bridges samples
    outside the preregistered physical screen.
    """
    if len(time) != len(power) or len(time) < 2 or any(not math.isfinite(t) for t in time):
        return None, 0
    screened, mask = screen_power_series(time, power, minimum, maximum)
    excluded = int(sum(mask))
    if len(power) - excluded < 2 or any(not math.isfinite(value) for value in screened):
        return None, excluded
    joules = sum(
        max(0.0, t1 - t0) * (p0 + p1) / 2
        for t0, t1, p0, p1 in zip(time, time[1:], screened, screened[1:])
    )
    return joules / 3.6e6, excluded


def screen_power_series(
    time: list[float], power: list[float], minimum: float, maximum: float
) -> tuple[list[float], list[float]]:
    """Return a point-aligned linear bridge and a numeric exclusion mask."""
    if len(time) != len(power):
        return list(power), [0.0] * len(power)
    valid_sample = [
        minimum <= value <= maximum and math.isfinite(value) and math.isfinite(time[index])
        for index, value in enumerate(power)
    ]
    valid_indices = [
        index for index, valid in enumerate(valid_sample) if valid
    ]
    mask = [0.0 if valid else 1.0 for valid in valid_sample]
    if len(valid_indices) < 2:
        return list(power), mask
    screened = list(power)
    for index, valid in enumerate(valid_sample):
        if valid:
            continue
        before = next((candidate for candidate in reversed(valid_indices) if candidate < index), None)
        after = next((candidate for candidate in valid_indices if candidate > index), None)
        if before is None:
            screened[index] = power[after]  # type: ignore[index]
        elif after is None:
            screened[index] = power[before]
        elif time[after] == time[before]:
            screened[index] = power[after]
        else:
            weight = (time[index] - time[before]) / (time[after] - time[before])
            screened[index] = power[before] + weight * (power[after] - power[before])
    return screened, mask


def add_screened_series(
    series: dict[str, list[float]], protocol: AnalysisProtocol | None = None
) -> dict[str, list[float]]:
    protocol = protocol or AnalysisProtocol()
    if "P_HVAC_W" not in series:
        return series
    screened, mask = screen_power_series(
        series.get("time", []), series["P_HVAC_W"],
        protocol.hvac_power_screen_min_W, protocol.hvac_power_screen_max_W,
    )
    return {**series, "P_HVAC_screened_W": screened, "P_HVAC_screen_excluded": mask}


def compute_metrics(
    series: dict[str, list[float]], profile: str = "default",
    protocol: AnalysisProtocol | None = None,
) -> dict[str, float]:
    """Metric engine MVP (PRD M5.1): peak/avg temperature, energy use, stability."""
    metrics: dict[str, float] = {}
    temp = series.get("T")
    if temp:
        tail = _steady_window(temp)
        mean_tail = sum(tail) / len(tail)
        metrics["T_peak_degC"] = max(temp)
        metrics["T_avg_steady_degC"] = round(mean_tail, 3)
        metrics["T_std_steady_degC"] = round(
            math.sqrt(sum((x - mean_tail) ** 2 for x in tail) / len(tail)), 4
        )
    energy = series.get("E_cool")
    if energy:
        metrics["E_cool_kWh"] = round(energy[-1] / 3.6e6, 3)
    power = series.get("P_cool")
    if power:
        metrics["P_cool_avg_W"] = round(sum(power) / len(power), 1)
    if profile == "chiller_benchmark":
        protocol = protocol or AnalysisProtocol()
        temp_k = series.get("T_room_K", [])
        e_hvac = series.get("E_HVAC_J", [])
        e_it = series.get("E_IT_J", [])
        time = series.get("time", [])
        hvac_power = series.get("P_HVAC_W", [])
        if temp_k:
            temp_c = [value - 273.15 for value in temp_k]
            metrics["T_room_peak_degC"] = round(max(temp_c), 3)
            metrics["thermal_exceedance_degree_hours"] = round(
                _trapezoid_positive_hours(
                    time, temp_c, protocol.thermal_threshold_degC
                ), 4
            )
        bounded_hvac, excluded = _bounded_energy_kwh(
            time, hvac_power,
            protocol.hvac_power_screen_min_W, protocol.hvac_power_screen_max_W,
        )
        if bounded_hvac is not None:
            metrics["E_HVAC_kWh"] = round(bounded_hvac, 3)
            metrics["power_screen_excluded_samples"] = float(excluded)
        elif e_hvac:
            metrics["E_HVAC_kWh"] = round(e_hvac[-1] / 3.6e6, 3)
        if e_hvac:
            metrics["E_HVAC_raw_kWh"] = round(e_hvac[-1] / 3.6e6, 3)
        if e_it:
            metrics["E_IT_kWh"] = round(e_it[-1] / 3.6e6, 3)
        if "E_HVAC_kWh" in metrics and e_it and e_it[-1] > 0:
            metrics["PUE"] = round(
                (metrics["E_IT_kWh"] + metrics["E_HVAC_kWh"]) / metrics["E_IT_kWh"], 5
            )
        for source, target in (
            ("free_cooling_s", "free_cooling_hours"),
            ("partial_mechanical_s", "partial_mechanical_hours"),
            ("full_mechanical_s", "full_mechanical_hours"),
        ):
            if series.get(source):
                metrics[target] = round(series[source][-1] / 3600, 4)
        if series.get("mode_switches"):
            metrics["mode_switches"] = float(round(series["mode_switches"][-1]))
    return metrics


def build_result_bundle(
    spec: ExperimentSpec, workdir: Path, result_csv: Path | None, log: str, error: str = "",
    case_id: str = "", analysis_protocol: AnalysisProtocol | None = None,
) -> ResultBundle:
    if result_csv is None:
        model = get_model(spec.model_name)
        return ResultBundle(
            spec_id=spec.id, case_id=case_id or spec.id, model_name=spec.model_name,
            parameters=spec.parameters, status="failed", workdir=str(workdir), log_excerpt=error[-2000:],
            execution_spec_sha256=experiment_spec_hash(spec),
            validation_status=model.validation_status,
            warnings=runtime_plausibility_warnings(spec),
            validation_report_id=model.validation_report_id,
        )
    series = load_series(result_csv)
    result_sha256, result_bytes = file_fingerprint(result_csv)
    model = get_model(spec.model_name)
    protocol = analysis_protocol or AnalysisProtocol()
    metrics = compute_metrics(series, model.metric_profile, protocol)
    return ResultBundle(
        spec_id=spec.id,
        case_id=case_id or spec.id,
        model_name=spec.model_name,
        parameters=spec.parameters,
        status="ok",
        workdir=str(workdir),
        result_file=str(result_csv),
        execution_spec_sha256=experiment_spec_hash(spec),
        result_file_sha256=result_sha256,
        observed_result_file_sha256=result_sha256,
        result_file_bytes=result_bytes,
        result_file_integrity="verified",
        sample_count=len(series.get("time", [])),
        metrics=metrics,
        metric_methods={
            name: protocol.metric_methods.get(name, "Deterministic calculation from the stored result series.")
            for name in metrics
        },
        log_excerpt=log[-1000:],
        validation_status=model.validation_status,
        warnings=runtime_plausibility_warnings(spec, series),
        validation_report_id=model.validation_report_id,
    )
