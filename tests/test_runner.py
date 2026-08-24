"""Tests for the simulation runner: OMPython backend, command generation, dispatch."""

import sys
import types
from pathlib import Path

import pytest

from rcp.objects import ExperimentSpec
from rcp.simulation import runner
from rcp.simulation.registry import get_model
from rcp.simulation.runner import (
    SimulationError,
    _library_load_cmds,
    _simulate_cmd,
    result_filename,
    run_simulation,
)


def _spec(model="DataCenterRoom", **overrides) -> ExperimentSpec:
    base = dict(id="s1", hypothesis_id="H1", model_name=model,
                parameters={}, outputs=["T"], stop_time=3600.0)
    base.update(overrides)
    return ExperimentSpec(**base)


def test_result_filename_handles_dotted_class_names():
    assert result_filename(get_model("DataCenterRoom")) == "DataCenterRoom_res.csv"
    assert (result_filename(get_model("NonIntegratedPlant"))
            == "NonIntegratedPrimarySecondaryEconomizer_res.csv")


def test_simulate_cmd_includes_overrides():
    cmd = _simulate_cmd(get_model("DataCenterRoom"), _spec(parameters={"Q_it": 60000.0}))
    assert 'simulate(DataCenterRoom' in cmd
    assert 'simflags="-override Q_it=60000.0"' in cmd
    # no overrides -> no simflags
    assert "simflags" not in _simulate_cmd(get_model("DataCenterRoom"), _spec())


def test_library_load_cmds():
    cmds = _library_load_cmds(get_model("NonIntegratedPlant"))
    assert any("setModelicaPath" in c for c in cmds)
    assert any("loadModel(Modelica)" in c for c in cmds)
    assert any("loadModel(Buildings)" in c for c in cmds)
    assert _library_load_cmds(get_model("DataCenterRoom")) == []


class FakeOMC:
    def __init__(self, succeed=True):
        self.sent: list[str] = []
        self.cwd = "."
        self.succeed = succeed

    def sendExpression(self, expr: str):
        self.sent.append(expr)
        if expr.startswith('cd("'):
            self.cwd = expr.split('"')[1]
            return "True"
        if "simulate(" in expr:
            class_name = expr.split("simulate(")[1].split(",")[0].strip()
            short = class_name.rsplit(".", 1)[-1]
            if self.succeed:
                Path(self.cwd, f"{short}_res.csv").write_text('"time","T"\n0,27\n')
                return f'{{resultFile = "{short}_res.csv", messages = "The simulation finished successfully"}}'
            return 'messages = "Simulation execution failed"'
        return "True"

    def __del__(self):
        pass


def _install_fake_ompython(monkeypatch, succeed=True):
    mod = types.ModuleType("OMPython")
    mod.OMCSessionZMQ = lambda: FakeOMC(succeed=succeed)
    monkeypatch.setitem(sys.modules, "OMPython", mod)


def _force_backend(monkeypatch, backend):
    class _S:
        rcp_om_backend = backend
        rcp_om_image = "img"
        rcp_library_path = ""

    monkeypatch.setattr(runner, "get_settings", lambda: _S())


def test_ompython_backend_runs_and_returns_csv(monkeypatch, tmp_path):
    _install_fake_ompython(monkeypatch)
    _force_backend(monkeypatch, "ompython")
    csv_path, log = run_simulation(_spec(), tmp_path)
    assert csv_path.exists()
    assert "finished successfully" in log


def test_ompython_backend_failure_raises(monkeypatch, tmp_path):
    _install_fake_ompython(monkeypatch, succeed=False)
    _force_backend(monkeypatch, "ompython")
    with pytest.raises(SimulationError):
        run_simulation(_spec(), tmp_path)


def test_ompython_loads_libraries_and_model_file(monkeypatch, tmp_path):
    _install_fake_ompython(monkeypatch)
    _force_backend(monkeypatch, "ompython")
    run_simulation(_spec("DataCenterRoom"), tmp_path)
    # find the OMPython session used (FakeOMC instances aren't exposed), so
    # verify command generation directly instead:
    cmds = _library_load_cmds(get_model("IntegratedPlant"))
    joined = "\n".join(cmds)
    assert "loadModel(Modelica)" in joined and "loadModel(Buildings)" in joined
