"""Simulation runner: executes ExperimentSpecs via OpenModelica (PRD M4.2).

Backends (RCP_OM_BACKEND): ompython (OMCSessionZMQ, the PRD-required mechanism),
local (omc via a .mos script), docker (.mos script in the official image),
auto (local omc, else docker). The .mos backends remain the fallback for
environments without a native OpenModelica install.
"""

import os
import shutil
import subprocess
from pathlib import Path

from rcp.config import get_settings
from rcp.objects import ExperimentSpec
from rcp.simulation.registry import ModelInfo, get_model, library_paths, validate_spec


class SimulationError(Exception):
    pass


def _diagnose(log: str) -> str:
    """Failure handler (PRD M4.5): map omc output to an actionable message."""
    checks = {
        "Translation Error": "model failed to compile — check model file and parameter names",
        "division by zero": "numerical failure (division by zero) — check parameter values",
        "solver": "solver failure — possible non-convergence; try smaller stop_time or different parameters",
        "Failed to load": "model file could not be loaded",
        "not found in scope": "model or library could not be loaded — check class name and RCP_LIBRARY_PATH",
        "not possible to open file": "a resource (e.g. weather file) could not be resolved — see RCP_LIBRARY_PATH",
    }
    for needle, message in checks.items():
        if needle.lower() in log.lower():
            return message
    return "simulation failed — see log excerpt"


def _overrides(spec: ExperimentSpec) -> str:
    return ",".join(f"{k}={v}" for k, v in spec.parameters.items())


def _simflags(spec: ExperimentSpec) -> str:
    overrides = _overrides(spec)
    return f', simflags="-override {overrides}"' if overrides else ""


def _simulate_cmd(model: ModelInfo, spec: ExperimentSpec) -> str:
    return (
        f"simulate({model.class_name}, stopTime={spec.stop_time}, "
        f"numberOfIntervals={spec.intervals}, outputFormat=\"csv\"{_simflags(spec)})"
    )


def _library_load_cmds(model: ModelInfo) -> list[str]:
    """Commands to load the Modelica libraries a library model depends on."""
    if not model.libraries:
        return []
    path = os.pathsep.join(library_paths())
    cmds = [f'setModelicaPath("{path}");']
    for lib in model.libraries:
        cmds.append(f"loadModel({lib}); getErrorString();")
    return cmds


def result_filename(model: ModelInfo) -> str:
    return f"{model.class_name.rsplit('.', 1)[-1]}_res.csv"


def _pick_backend() -> str:
    backend = get_settings().rcp_om_backend
    if backend != "auto":
        return backend
    if shutil.which("omc"):
        return "local"
    return "docker"


def _write_mos(spec: ExperimentSpec, model: ModelInfo, workdir: Path) -> Path:
    lines = list(_library_load_cmds(model))
    if model.file:
        lines.append(f'loadFile("{model.file}"); getErrorString();')
    lines.append(_simulate_cmd(model, spec) + "; getErrorString();")
    path = workdir / "run.mos"
    path.write_text("\n".join(lines))
    return path


def _run_mos(spec: ExperimentSpec, model: ModelInfo, workdir: Path, backend: str) -> tuple[Path, str]:
    _write_mos(spec, model, workdir)
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
    result_csv = workdir / result_filename(model)
    ok = "The simulation finished successfully" in log and result_csv.exists()
    if proc.returncode != 0 or not ok:
        raise SimulationError(f"{_diagnose(log)}\n--- log tail ---\n{log[-2000:]}")
    return result_csv, log


def _run_ompython(spec: ExperimentSpec, model: ModelInfo, workdir: Path) -> tuple[Path, str]:
    try:
        from OMPython import OMCSessionZMQ
    except ImportError as err:  # pragma: no cover - depends on environment
        raise SimulationError(
            "OMPython is not installed — `pip install OMPython`, or use RCP_OM_BACKEND=local"
        ) from err

    model_file: str | None = None
    if model.file:
        shutil.copy(model.path, workdir / model.file)
        model_file = str((workdir / model.file).resolve())

    omc = OMCSessionZMQ()
    try:
        omc.sendExpression(f'cd("{workdir.resolve()}")')
        for cmd in _library_load_cmds(model):
            omc.sendExpression(cmd)
        if model_file:
            omc.sendExpression(f'loadFile("{model_file}"); getErrorString();')
        result = omc.sendExpression(_simulate_cmd(model, spec))
        log = str(result)
    except Exception as err:  # OMCSessionException etc.
        log = str(err)
    finally:
        del omc  # triggers OMCSessionZMQ.__del__ to terminate the omc process

    result_csv = workdir / result_filename(model)
    ok = "The simulation finished successfully" in log and result_csv.exists()
    if not ok:
        raise SimulationError(f"{_diagnose(log)}\n--- log tail ---\n{log[-2000:]}")
    return result_csv, log


def run_simulation(spec: ExperimentSpec, workdir: Path) -> tuple[Path, str]:
    """Run one spec; returns (result_csv_path, log). Raises SimulationError on failure."""
    violations = validate_spec(spec)
    if violations:
        raise SimulationError("constraint check failed: " + "; ".join(violations))

    model = get_model(spec.model_name)
    workdir.mkdir(parents=True, exist_ok=True)

    backend = _pick_backend()
    if backend == "ompython":
        return _run_ompython(spec, model, workdir)
    if model.file:
        shutil.copy(model.path, workdir / model.file)
    return _run_mos(spec, model, workdir, backend)
