"""Cross-tool comparison against reference trajectories shipped by Buildings."""

from __future__ import annotations

import ast
import bisect
import csv
import math
import shutil
import subprocess
from pathlib import Path

from rcp.config import get_settings

REFERENCE_FILES = {
    "ChillerCooledIntegrated": (
        "Buildings_Applications_DataCenters_ChillerCooled_Examples_"
        "IntegratedPrimarySecondaryEconomizer.txt"
    ),
    "ChillerCooledNonIntegrated": (
        "Buildings_Applications_DataCenters_ChillerCooled_Examples_"
        "NonIntegratedPrimarySecondaryEconomizer.txt"
    ),
}
REFERENCE_ROOT = "/opt/modelica/Buildings/Resources/ReferenceResults/Dymola"


def parse_reference(text: str) -> dict[str, list[float]]:
    values: dict[str, list[float]] = {}
    for line in text.splitlines():
        if "=[" not in line:
            continue
        name, encoded = line.split("=", 1)
        try:
            parsed = ast.literal_eval(encoded)
        except (SyntaxError, ValueError):
            continue
        if isinstance(parsed, list) and all(isinstance(item, (int, float)) for item in parsed):
            values[name] = [float(item) for item in parsed]
    return values


def load_reference(model_name: str, image: str | None = None) -> dict[str, list[float]]:
    filename = REFERENCE_FILES.get(model_name)
    if not filename:
        raise ValueError(f"no upstream reference registered for {model_name}")
    docker = shutil.which("docker")
    if not docker:
        raise RuntimeError("docker is required to read the pinned Buildings reference")
    proc = subprocess.run(
        [docker, "run", "--rm", image or get_settings().rcp_om_image,
         "cat", f"{REFERENCE_ROOT}/{filename}"],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode:
        raise RuntimeError(f"could not load upstream reference: {proc.stderr[-500:]}")
    return parse_reference(proc.stdout)


def _interpolate(time: list[float], values: list[float], query: float) -> float:
    index = bisect.bisect_left(time, query)
    if index <= 0:
        return values[0]
    if index >= len(time):
        return values[-1]
    t0, t1 = time[index - 1], time[index]
    v0, v1 = values[index - 1], values[index]
    if t1 == t0:
        return v1
    return v0 + (v1 - v0) * (query - t0) / (t1 - t0)


def compare_upstream_reference(
    csv_path: Path,
    model_name: str,
    reference: dict[str, list[float]] | None = None,
    tolerance: float = 0.005,
) -> dict:
    """Compare OpenModelica output with evenly sampled pinned Dymola references."""
    with csv_path.open() as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"empty result file: {csv_path}")
    series = {
        name.strip('"'): [float(row[name]) for row in rows]
        for name in (rows[0].keys())
    }
    time = series.get("time", [])
    upstream = reference or load_reference(model_name)
    stop_time = upstream.get("time", [time[0], time[-1]])[-1]
    variables: dict[str, dict] = {}
    for name, expected in upstream.items():
        if name == "time" or len(expected) < 3 or name not in series:
            continue
        query = [index * stop_time / (len(expected) - 1) for index in range(len(expected))]
        observed = [_interpolate(time, series[name], timestamp) for timestamp in query]
        rmse = math.sqrt(sum((a - b) ** 2 for a, b in zip(observed, expected)) / len(expected))
        scale = max(max(expected) - min(expected), max(abs(value) for value in expected), 1.0)
        normalized_rmse = rmse / scale
        variables[name] = {
            "samples": len(expected),
            "rmse": rmse,
            "normalized_rmse": normalized_rmse,
            "passed": normalized_rmse <= tolerance,
        }
    worst = max((item["normalized_rmse"] for item in variables.values()), default=math.inf)
    return {
        "model_name": model_name,
        "reference": "Buildings 13.0.0 Dymola reference trajectory",
        "tolerance_normalized_rmse": tolerance,
        "worst_normalized_rmse": worst,
        "status": "passed" if variables and all(item["passed"] for item in variables.values()) else "failed",
        "variables": variables,
    }
