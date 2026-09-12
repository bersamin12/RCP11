"""Simulation runner: executes ExperimentSpecs via OpenModelica (PRD M4.2 MVP).

Three backends: omc scripting (.mos) through the pinned Docker image (default for
library models, which need the baked-in OPENMODELICALIBRARY), the same script
through a local omc install, and an OMPython/OMCSessionZMQ interactive session.
OMPython is opt-in via RCP_OM_BACKEND=ompython -- "auto" never selects it, so the
reproducible Docker path stays the default for anything the benchmark depends on.
"""

import os
import json
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
    }
    for needle, message in checks.items():
        if needle.lower() in log.lower():
            return message
    return "simulation failed — see log excerpt"


def _library_load_cmds(model: ModelInfo) -> list[str]:
    """Version-pinned loadModel calls for the libraries a model depends on.

    The version is part of the command, not a hint: an unpinned loadModel would
    silently accept whatever the environment happens to hold.
    """
    return [
        f'loadModel({name}, {{"{version}"}}); getErrorString();'
        for name, version in model.libraries.items()
    ]


def _simulate_cmd(model: ModelInfo, spec: ExperimentSpec) -> str:
    overrides = ",".join(f"{k}={v}" for k, v in spec.parameters.items())
    simflags = f', simflags="-override {overrides}"' if overrides else ""
    return (
        f"simulate({model.class_name}, startTime={spec.start_time}, "
        f"stopTime={spec.stop_time}, "
        f'numberOfIntervals={spec.intervals}, outputFormat="csv", '
        f'fileNamePrefix="result"{simflags})'
    )


def _write_mos(spec: ExperimentSpec, workdir: Path) -> Path:
    model = get_model(spec.model_name)
    overrides = ",".join(f"{k}={v}" for k, v in spec.parameters.items())
    simflags = f', simflags="-override {overrides}"' if overrides else ""
    library_loads = "".join(cmd + "\n" for cmd in _library_load_cmds(model))
    mos = (
        library_loads
        + f'loadFile("{model.file}"); getErrorString();\n'
        f"simulate({model.class_name}, startTime={spec.start_time}, "
        f"stopTime={spec.stop_time}, "
        f'numberOfIntervals={spec.intervals}, outputFormat="csv", fileNamePrefix="result"{simflags}); '
        "getErrorString();\n"
    )
    path = workdir / "run.mos"
    path.write_text(mos)
    return path


def _local_env() -> dict[str, str]:
    """OPENMODELICALIBRARY for the backends that run outside the pinned image.

    Docker needs none of this: its libraries are baked into /opt/modelica.
    """
    env = dict(os.environ)
    paths = library_paths()
    if paths:
        env["OPENMODELICALIBRARY"] = os.pathsep.join(paths)
    return env


def _pick_backend(model_name: str = "") -> str:
    backend = get_settings().rcp_om_backend
    if backend != "auto":
        return backend
    if model_name and get_model(model_name).libraries:
        return "docker"
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

    backend = _pick_backend(spec.model_name)
    if backend == "ompython":
        return _run_ompython(spec, model, workdir)
    env = None
    if backend == "local":
        cmd = ["omc", "run.mos"]
        env = _local_env()
    else:
        cmd = [
            "docker", "run", "--rm",
            "-u", f"{os.getuid()}:{os.getgid()}",
            "-e", "HOME=/tmp",
            "-e", "OPENMODELICALIBRARY=/opt/modelica",
            "-v", f"{workdir.resolve()}:/work", "-w", "/work",
            get_settings().rcp_om_image,
            "omc", "run.mos",
        ]
    try:
        proc = subprocess.run(
            cmd, cwd=workdir, capture_output=True, text=True, timeout=1200, env=env
        )
    except FileNotFoundError as err:
        raise SimulationError(f"simulation backend is unavailable: {err}") from err
    except subprocess.TimeoutExpired as err:
        raise SimulationError("simulation timed out after 1200 seconds") from err
    log = proc.stdout + proc.stderr

    result_csv = workdir / "result_res.csv"
    ok = "The simulation finished successfully" in log and result_csv.exists()
    if proc.returncode != 0 or not ok:
        raise SimulationError(f"{_diagnose(log)}\n--- log tail ---\n{log[-2000:]}")
    return result_csv, log


def run_compiled_simulation(
    spec: ExperimentSpec, template_workdir: Path, workdir: Path
) -> tuple[Path, str]:
    """Run a new parameter case from an already compiled model executable."""
    violations = validate_spec(spec)
    if violations:
        raise SimulationError("constraint check failed: " + "; ".join(violations))
    executable = template_workdir / "result"
    init_xml = template_workdir / "result_init.xml"
    if not executable.exists() or not init_xml.exists():
        raise SimulationError("compiled simulation template is incomplete")
    workdir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(executable, workdir / executable.name)
    shutil.copy2(init_xml, workdir / init_xml.name)
    for source in template_workdir.glob("result_*.bin"):
        shutil.copy2(source, workdir / source.name)
    (workdir / "compiled_run.json").write_text(json.dumps({
        "template_workdir": str(template_workdir),
        "model_name": spec.model_name,
        "parameters": spec.parameters,
        "stop_time": spec.stop_time,
        "intervals": spec.intervals,
    }, indent=2))

    overrides = ",".join(f"{key}={value}" for key, value in spec.parameters.items())
    arguments = ["./result", "-r=result_res.csv"]
    if overrides:
        arguments.append(f"-override={overrides}")
    backend = _pick_backend(spec.model_name)
    if backend == "local":
        cmd = arguments
    else:
        cmd = [
            "docker", "run", "--rm",
            "-u", f"{os.getuid()}:{os.getgid()}",
            "-e", "HOME=/tmp",
            "-e", "OPENMODELICALIBRARY=/opt/modelica",
            "-v", f"{workdir.resolve()}:/work", "-w", "/work",
            get_settings().rcp_om_image,
            *arguments,
        ]
    try:
        proc = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, timeout=1200)
    except FileNotFoundError as err:
        raise SimulationError(f"simulation backend is unavailable: {err}") from err
    except subprocess.TimeoutExpired as err:
        raise SimulationError("simulation timed out after 1200 seconds") from err
    log = proc.stdout + proc.stderr
    result_csv = workdir / "result_res.csv"
    if proc.returncode != 0 or "The simulation finished successfully" not in log or not result_csv.exists():
        raise SimulationError(f"{_diagnose(log)}\n--- log tail ---\n{log[-2000:]}")
    return result_csv, log


def _run_ompython(spec: ExperimentSpec, model: ModelInfo, workdir: Path) -> tuple[Path, str]:
    """Interactive OMCSessionZMQ backend, for hosts with OpenModelica installed natively.

    Opt-in only (RCP_OM_BACKEND=ompython). It resolves libraries from the host's
    OPENMODELICALIBRARY rather than the pinned image, so a run made this way is not
    interchangeable with a Docker run for reproducibility purposes.
    """
    try:
        from OMPython import OMCSessionZMQ
    except ImportError as err:  # pragma: no cover - depends on environment
        raise SimulationError(
            "OMPython is not installed — `pip install OMPython`, or use RCP_OM_BACKEND=docker"
        ) from err

    os.environ.update(_local_env())
    model_file = str((workdir / model.file).resolve()) if model.file else None

    omc = OMCSessionZMQ()
    try:
        omc.sendExpression(f'cd("{workdir.resolve()}")')
        for cmd in _library_load_cmds(model):
            omc.sendExpression(cmd)
        if model_file:
            omc.sendExpression(f'loadFile("{model_file}"); getErrorString();')
        log = str(omc.sendExpression(_simulate_cmd(model, spec)))
    except Exception as err:  # OMCSessionException and friends
        log = str(err)
    finally:
        del omc  # OMCSessionZMQ.__del__ terminates the omc process

    result_csv = workdir / "result_res.csv"
    if "The simulation finished successfully" not in log or not result_csv.exists():
        raise SimulationError(f"{_diagnose(log)}\n--- log tail ---\n{log[-2000:]}")
    return result_csv, log
