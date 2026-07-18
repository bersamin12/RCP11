import pytest

from rcp.objects import ExperimentSpec
from rcp.simulation.registry import get_model, load_registry, validate_spec


def _spec(**overrides) -> ExperimentSpec:
    base = dict(
        id="t1", hypothesis_id="H1", model_name="DataCenterRoom",
        parameters={"Q_it": 60000.0}, outputs=["T"], stop_time=3600.0,
    )
    base.update(overrides)
    return ExperimentSpec(**base)


def test_registry_loads_bundled_model():
    registry = load_registry()
    assert "DataCenterRoom" in registry
    assert get_model("DataCenterRoom").path.exists()


def test_valid_spec_passes():
    assert validate_spec(_spec()) == []


def test_unknown_model_and_param_and_range():
    assert validate_spec(_spec(model_name="Nope"))
    assert any("unknown parameter" in v for v in validate_spec(_spec(parameters={"bogus": 1.0})))
    assert any("out of range" in v for v in validate_spec(_spec(parameters={"Q_it": 10.0})))
    assert any("unknown output" in v for v in validate_spec(_spec(outputs=["nope"])))
    assert any("stop_time" in v for v in validate_spec(_spec(stop_time=-1.0)))


def test_unknown_model_raises():
    with pytest.raises(KeyError):
        get_model("DoesNotExist")
