"""API tests — LLM, paper fetching, and simulation are mocked so these run offline."""

import time

import pytest
from fastapi.testclient import TestClient

from rcp.objects import (
    Claim,
    ClaimBundle,
    ExperimentSpec,
    Hypothesis,
    PaperCard,
    ResultBundle,
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("RCP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr("rcp.config.get_settings.cache_clear", lambda: None, raising=False)
    from rcp.config import get_settings

    get_settings.cache_clear()

    from rcp.graph import nodes

    def fake_memory(topic, **kwargs):
        cards = [PaperCard(id="p1", title="Paper One", year=2024, problem="x", method="y")]
        return cards, {"tag": ["Paper One"]}, tmp_path

    def fake_llm_json(prompt, schema, system="", retries=2):
        name = schema.__name__
        if name == "GapList":
            return schema(gaps=["gap one"])
        if name == "HypothesisList":
            return schema(hypotheses=[Hypothesis(id="H1", statement="s1"),
                                      Hypothesis(id="H2", statement="s2")])
        if name == "ExperimentSpec":
            return ExperimentSpec(id="spec-1", hypothesis_id="H1",
                                  model_name="DataCenterRoom",
                                  parameters={"Q_it": 60000.0}, outputs=["T"],
                                  stop_time=3600.0)
        if name == "ClaimBundle":
            return ClaimBundle(hypothesis_id="H1",
                               claims=[Claim(statement="c", evidence="e")], summary="s")
        if name == "ReportBody":
            return schema(introduction="i", method="m", results_discussion="r", conclusion="c")
        raise AssertionError(f"unexpected schema {name}")

    def fake_run_simulation(spec, workdir):
        workdir.mkdir(parents=True, exist_ok=True)
        csv = workdir / f"{spec.model_name}_res.csv"
        csv.write_text('"time","T","P_cool","E_cool"\n0,27,0,0\n3600,24,4000,16200000\n')
        return csv, "The simulation finished successfully"

    monkeypatch.setattr(nodes, "build_research_memory", fake_memory)
    monkeypatch.setattr(nodes, "llm_json", fake_llm_json)
    monkeypatch.setattr(nodes, "run_simulation", fake_run_simulation)
    monkeypatch.setattr(
        "rcp.api.main.run_simulation",
        lambda spec, workdir: fake_run_simulation(spec, workdir),
    )

    # Fresh app instance so the manager uses the tmp data dir.
    import importlib

    import rcp.api.main as api_main

    importlib.reload(api_main)
    monkeypatch.setattr(api_main, "run_simulation", fake_run_simulation)
    return TestClient(api_main.app)


def _wait(client, run_id, statuses=("done", "failed"), timeout=30) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        detail = client.get(f"/api/runs/{run_id}").json()
        if detail["status"] in statuses:
            return detail
        time.sleep(0.1)
    raise TimeoutError(f"run stuck in {detail['status']}")


def test_health_and_models(client):
    assert client.get("/api/health").json()["ok"] is True
    models = client.get("/api/models").json()
    assert "DataCenterRoom" in models
    assert "Q_it" in models["DataCenterRoom"]["parameters"]


def test_auto_run_completes_and_produces_report(client):
    run_id = client.post("/api/runs", json={"topic": "test topic", "auto": True}).json()["run_id"]
    detail = _wait(client, run_id)
    assert detail["status"] == "done"
    nodes_done = [n["node"] for n in detail["node_history"]]
    assert nodes_done[0] == "research_memory_build" and nodes_done[-1] == "draft_report"
    assert detail["state"]["selected_hypothesis"]["id"] == "H1"
    report = client.get(f"/api/runs/{run_id}/report")
    assert report.status_code == 200 and "test topic" in report.text
    series = client.get(f"/api/runs/{run_id}/series").json()
    assert series["T"] == [27.0, 24.0]


def test_manual_gates_flow(client):
    run_id = client.post("/api/runs", json={"topic": "gated run"}).json()["run_id"]
    detail = _wait(client, run_id, statuses=("waiting_gate",))
    assert detail["gate"]["gate"] == "hypothesis_selection"
    assert len(detail["gate"]["options"]) == 2

    client.post(f"/api/runs/{run_id}/gate", json={"answer": "1"})
    detail = _wait(client, run_id, statuses=("waiting_gate",))
    assert detail["gate"]["gate"] == "spec_approval"
    assert detail["state"]["selected_hypothesis"]["id"] == "H2"

    client.post(f"/api/runs/{run_id}/gate", json={"answer": "use a shorter horizon"})
    detail = _wait(client, run_id, statuses=("waiting_gate",))
    assert detail["gate"]["gate"] == "spec_approval"  # revision loop came back
    assert detail["state"]["spec_attempts"] == 2

    client.post(f"/api/runs/{run_id}/gate", json={"answer": "yes"})
    detail = _wait(client, run_id)
    assert detail["status"] == "done"


def test_gate_conflict_and_unknown_run(client):
    assert client.get("/api/runs/nope").status_code == 404
    run_id = client.post("/api/runs", json={"topic": "t", "auto": True}).json()["run_id"]
    _wait(client, run_id)
    assert client.post(f"/api/runs/{run_id}/gate", json={"answer": "yes"}).status_code == 409


def test_quick_simulate(client):
    resp = client.post("/api/simulations", json={"model_name": "DataCenterRoom",
                                                 "parameters": {"Q_it": 50000}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok" and "T_peak_degC" in body["metrics"]
