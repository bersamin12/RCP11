"""Result collector: unify simulation outputs into a ResultBundle (PRD M4.4, M5.1)."""

import csv
import math
from pathlib import Path

from rcp.evidence import sha256_file, spec_digest
from rcp.objects import ExperimentSpec, ResultBundle


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


def compute_metrics(series: dict[str, list[float]]) -> dict[str, float]:
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
    return metrics


def build_result_bundle(
    spec: ExperimentSpec, workdir: Path, result_csv: Path | None, log: str, error: str = ""
) -> ResultBundle:
    if result_csv is None:
        return ResultBundle(
            spec_id=spec.id, status="failed", workdir=str(workdir),
            log_excerpt=error[-2000:], spec_hash=spec_digest(spec),
        )
    series = load_series(result_csv)
    return ResultBundle(
        spec_id=spec.id,
        status="ok",
        workdir=str(workdir),
        result_file=str(result_csv),
        metrics=compute_metrics(series),
        log_excerpt=log[-1000:],
        spec_hash=spec_digest(spec),
        result_file_hash=sha256_file(result_csv),
    )


def compare_bundles(baseline: ResultBundle, candidate: ResultBundle) -> dict[str, dict]:
    """Comparator (PRD M5.2): side-by-side metric deltas, baseline -> candidate."""
    keys = sorted(set(baseline.metrics) | set(candidate.metrics))
    rows: dict[str, dict] = {}
    for k in keys:
        b = baseline.metrics.get(k)
        c = candidate.metrics.get(k)
        if b is None or c is None:
            rows[k] = {"baseline": b, "candidate": c, "delta": None, "delta_pct": None}
            continue
        delta = c - b
        pct = (delta / b * 100) if b else None
        rows[k] = {
            "baseline": b,
            "candidate": c,
            "delta": round(delta, 4),
            "delta_pct": round(pct, 2) if pct is not None else None,
        }
    return rows
