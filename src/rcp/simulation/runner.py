"""Simulation runner: executes ExperimentSpecs via OpenModelica (PRD M4.2 MVP).

MVP uses omc scripting (.mos) through either a local omc install or the official
Docker image. The OMPython/OMCSessionZMQ interactive backend is a planned upgrade
once OpenModelica is available natively (tracked for Phase 2 hardening).
"""

import os
import shutil
import subprocess
from pathlib import Path

from rcp.config import get_settings
from rcp.objects import ExperimentSpec
from rcp.simulation.registry import get_model, validate_spec


class SimulationError(Exception):
    pass


def _diagnose(log: str) -> str:
    """Failure handler (PRD M4.5): map omc output to an actionable message."""
    checks = {
        "Translation Error": "model failed to compile — check model file and parameter names",
        "division by zero": "numerical failure (division by zero) — check parameter values",
        "solver": "solver failure — possible non-convergence; try smaller stop_time or different parameters",
        "Failed to load": "model file could not be loaded",
    }
    for needle, message in checks.items():
        if needle.lower() in log.lower():
            return message
    return "simulation failed — see log excerpt"


def _write_mos(spec: ExperimentSpec, workdir: Path) -> Path:
    model = get_model(spec.model_name)
    overrides = ",".join(f"{k}={v}" for k, v in spec.parameters.items())
    simflags = f', simflags="-override {overrides}"' if overrides else ""
    mos = (
        f'loadFile("{model.file}"); getErrorString();\n'
        f"simulate({model.class_name}, stopTime={spec.stop_time}, "
        f'numberOfIntervals={spec.intervals}, outputFormat="csv"{simflags}); '
        "getErrorString();\n"
    )
    path = workdir / "run.mos"
    path.write_text(mos)
    return path


def _pick_backend() -> str:
    backend = get_settings().rcp_om_backend
    if backend != "auto":
        return backend
    if shutil.which("omc"):
        return "local"
    return "docker"


def run_simulation(spec: ExperimentSpec, workdir: Path) -> tuple[Path, str]:
    """Run one spec; returns (result_csv_path, log). Raises SimulationError on failure."""
    violations = validate_spec(spec)
    if violations:
        raise SimulationError("constraint check failed: " + "; ".join(violations))

    model = get_model(spec.model_name)
    workdir.mkdir(parents=True, exist_ok=True)
    shutil.copy(model.path, workdir / model.file)
    _write_mos(spec, workdir)

    backend = _pick_backend()
    if backend == "local":
        cmd = ["omc", "run.mos"]
    else:
        cmd = [
            "docker", "run", "--rm",
            "-u", f"{os.getuid()}:{os.getgid()}",
            "-e", "HOME=/tmp",
            "-v", f"{workdir.resolve()}:/work", "-w", "/work",
            get_settings().rcp_om_image,
            "omc", "run.mos",
        ]
    proc = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, timeout=600)
    log = proc.stdout + proc.stderr

    result_csv = workdir / f"{model.class_name}_res.csv"
    ok = "The simulation finished successfully" in log and result_csv.exists()
    if proc.returncode != 0 or not ok:
        raise SimulationError(f"{_diagnose(log)}\n--- log tail ---\n{log[-2000:]}")
    return result_csv, log
