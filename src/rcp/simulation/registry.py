"""Model registry: available Modelica models, parameters, I/O (PRD M4.1, M3.2 support)."""

import json
from pathlib import Path

from pydantic import BaseModel, Field

from rcp.objects import ExperimentSpec

MODELS_DIR = Path(__file__).parent.parent / "models_library"


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
