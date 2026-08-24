"""Tests for the simulation runner: command generation, backend dispatch, OMPython.

The runner always passes fileNamePrefix="result", so every backend produces
result_res.csv regardless of the model's class name. That is deliberate: the
collector and the reproducibility bundle address the raw artifact by a fixed
name rather than one derived from Modelica's class naming.
"""

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
    run_simulation,
)


def _spec(model="DataCenterRoom", **overrides) -> ExperimentSpec:
    base = dict(id="s1", hypothesis_id="H1", model_name=model,
                parameters={}, outputs=["T"], stop_time=3600.0)
    base.update(overrides)
    return ExperimentSpec(**base)


def test_simulate_cmd_includes_overrides():
    cmd = _simulate_cmd(get_model("DataCenterRoom"), _spec(parameters={"Q_it": 60000.0}))
    assert "simulate(DataCenterRoom" in cmd
    assert 'simflags="-override Q_it=60000.0"' in cmd
    assert 'fileNamePrefix="result"' in cmd


def test_simulate_cmd_omits_simflags_without_overrides():
    assert "simflags" not in _simulate_cmd(get_model("DataCenterRoom"), _spec())


def test_library_load_cmds_are_version_pinned():
    cmds = _library_load_cmds(get_model("ChillerCooledIntegrated"))
    joined = "\n".join(cmds)
    assert 'loadModel(Modelica, {"4.1.0"})' in joined
    assert 'loadModel(Buildings, {"13.0.0"})' in joined


def test_library_load_cmds_empty_for_bundled_model():
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
            if self.succeed:
                Path(self.cwd, "result_res.csv").write_text('"time","T"\n0,27\n')
                return ('{resultFile = "result_res.csv", '
                        'messages = "The simulation finished successfully"}')
            return 'messages = "Simulation execution failed"'
        return "True"

    def __del__(self):
        pass


def _install_fake_ompython(monkeypatch, succeed=True):
    sessions: list[FakeOMC] = []
    mod = types.ModuleType("OMPython")

    def _factory():
        session = FakeOMC(succeed=succeed)
        sessions.append(session)
        return session

    mod.OMCSessionZMQ = _factory
    monkeypatch.setitem(sys.modules, "OMPython", mod)
    return sessions


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
    assert csv_path == tmp_path / "result_res.csv"
    assert csv_path.exists()
    assert "finished successfully" in log


def test_ompython_backend_failure_raises(monkeypatch, tmp_path):
    _install_fake_ompython(monkeypatch, succeed=False)
    _force_backend(monkeypatch, "ompython")
    with pytest.raises(SimulationError):
        run_simulation(_spec(), tmp_path)


def test_ompython_loads_pinned_libraries_then_model_file(monkeypatch, tmp_path):
    sessions = _install_fake_ompython(monkeypatch)
    _force_backend(monkeypatch, "ompython")
    run_simulation(_spec("ChillerCooledIntegrated",
                         parameters={"Q_room": 500000.0},
                         outputs=["T_room_K"]), tmp_path)
    sent = sessions[0].sent
    assert any('loadModel(Modelica, {"4.1.0"})' in c for c in sent)
    assert any('loadModel(Buildings, {"13.0.0"})' in c for c in sent)
    load_file = next(i for i, c in enumerate(sent) if "loadFile(" in c)
    last_lib = max(i for i, c in enumerate(sent) if "loadModel(" in c)
    assert last_lib < load_file  # libraries must be resolvable before the model file


def test_auto_backend_never_picks_ompython(monkeypatch):
    # ompython resolves libraries from the host, so it is opt-in only; "auto"
    # must keep library models on the pinned image.
    _force_backend(monkeypatch, "auto")
    assert runner._pick_backend("ChillerCooledIntegrated") == "docker"
