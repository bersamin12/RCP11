"""Model registry: available Modelica models, parameters, I/O (PRD M4.1, M3.2 support)."""

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

from rcp.objects import ExperimentSpec

MODELS_DIR = Path(__file__).parent.parent / "models_library"
REPO_ROOT = MODELS_DIR.parent.parent.parent  # models_library -> rcp -> src -> repo root
VENDOR_DIR = REPO_ROOT / "vendor"


class ParamSpec(BaseModel):
    default: float
    min: float
    max: float
    unit: str = ""
    description: str = ""


class ModelInfo(BaseModel):
    name: str
    file: str
    class_name: str
    description: str = ""
    default_stop_time: float = 86400
    outputs: list[str] = Field(default_factory=list)
    parameters: dict[str, ParamSpec] = Field(default_factory=dict)
    validation_status: str = "unvalidated"
    model_version: str = "0.0.0"
    validation_report_id: str | None = None
    limitations: list[str] = Field(default_factory=list)
    operating_range: dict[str, dict[str, float | str]] = Field(default_factory=dict)
    libraries: dict[str, str] = Field(default_factory=dict)
    metric_profile: str = "default"
    source: str = "bundled"

    @property
    def path(self) -> Path:
        return MODELS_DIR / self.file


def load_registry() -> dict[str, ModelInfo]:
    raw = json.loads((MODELS_DIR / "registry.json").read_text())
    return {name: ModelInfo(name=name, **info) for name, info in raw.items()}


def get_model(name: str) -> ModelInfo:
    registry = load_registry()
    if name not in registry:
        raise KeyError(f"unknown model '{name}' — available: {list(registry)}")
    return registry[name]


def library_paths() -> list[str]:
    """Directories each holding a Modelica package directory (e.g. vendor/Modelica
    holds Modelica/ and ModelicaServices/).

    Only the local and ompython backends need this. The pinned Docker image bakes
    its libraries into OPENMODELICALIBRARY, so it ignores the setting entirely.
    """
    from rcp.config import get_settings

    raw = get_settings().rcp_library_path
    if raw:
        return [p for p in raw.split(os.pathsep) if p]
    return [str(VENDOR_DIR / "Modelica"), str(VENDOR_DIR / "Buildings")]


def validate_spec(spec: ExperimentSpec) -> list[str]:
    """Constraint checker (PRD M3.2): unknown params, out-of-range values, bad outputs."""
    violations: list[str] = []
    try:
        model = get_model(spec.model_name)
    except KeyError as err:
        return [str(err)]
    for pname, value in spec.parameters.items():
        if pname not in model.parameters:
            violations.append(f"unknown parameter '{pname}' for {model.name}")
            continue
        p = model.parameters[pname]
        if not (p.min <= value <= p.max):
            violations.append(
                f"{pname}={value} out of range [{p.min}, {p.max}] {p.unit}"
            )
    for out in spec.outputs:
        if out not in model.outputs:
            violations.append(f"unknown output '{out}' — available: {model.outputs}")
    if spec.stop_time <= 0:
        violations.append(f"stop_time must be positive, got {spec.stop_time}")
    return violations
