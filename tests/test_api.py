"""API tests — LLM, paper fetching, and simulation are mocked so these run offline."""

import io
import json
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from rcp.objects import (
    Claim,
    ClaimBundle,
    ExperimentSpec,
    Hypothesis,
    PaperCard,
    ResearchGap,
    ResultBundle,
    ThesisIdea,
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("RCP_DATA_DIR", str(tmp_path / "data"))
    # A live open-access fetch in CI would be both flaky and impolite to the
    # providers; nothing in these tests needs a real PDF.
    monkeypatch.setenv("RCP_FETCH_OA_PDFS", "false")
    monkeypatch.setattr("rcp.config.get_settings.cache_clear", lambda: None, raising=False)
    from rcp.config import get_settings

    get_settings.cache_clear()

    from rcp.graph import nodes

    def fake_memory(topic, **kwargs):
        cards = [PaperCard(id="p1", title="Paper One", year=2024, problem="x", method="y")]
        return cards, {"tag": ["Paper One"]}, tmp_path

    def fake_llm_json(prompt, schema, system="", retries=2):
        name = schema.__name__
        if name == "SynthesisProposal":
            return schema(gaps=[ResearchGap(
                id="gap-1", category="validation", statement="gap one",
                paper_ids=["p1"], model_names=["DataCenterRoom"],
            )])
        if name == "HypothesisList":
            return schema(hypotheses=[
                Hypothesis(
                    id="H1", statement="s1", rationale="r1", variables=["Q_it"],
                    expected_effect="temperature changes", metrics=["T"], risks=["conceptual"],
                    model_names=["DataCenterRoom"], supporting_gap_ids=["gap-1"],
                ),
                Hypothesis(
                    id="H2", statement="s2", rationale="r2", variables=["T_set"],
                    expected_effect="energy changes", metrics=["E_cool_kWh"], risks=["conceptual"],
                    model_names=["DataCenterRoom"], supporting_gap_ids=["gap-1"],
                ),
            ])
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
    health = client.get("/api/health").json()
    assert health["ok"] is True
    assert health["checkpoint_store"]["status"] == "ok"
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
    synthesis = client.get(f"/api/runs/{run_id}/synthesis")
    assert synthesis.status_code == 200
    assert synthesis.json()["gaps"][0]["paper_ids"] == ["p1"]
    report = client.get(f"/api/runs/{run_id}/report")
    assert report.status_code == 200 and "test topic" in report.text
    series = client.get(f"/api/runs/{run_id}/series").json()
    assert series["T"] == [27.0, 24.0]


def test_manual_gates_flow(client):
    run_id = client.post("/api/runs", json={"topic": "gated run"}).json()["run_id"]

    # A non-auto run now pauses on the literature before anything is built on it.
    detail = _wait(client, run_id, statuses=("waiting_gate",))
    assert detail["gate"]["gate"] == "literature_triage"
    assert [paper["id"] for paper in detail["gate"]["papers"]] == ["p1"]
    client.post(f"/api/runs/{run_id}/gate", json={"included_paper_ids": ["p1"], "reviewer": "gsw"})

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
    assert body["validation_status"] == "conceptual"
    assert body["warnings"]
    series = client.get(f"/api/simulations/{body['spec_id']}/series")
    assert series.status_code == 200
    assert series.json()["T"] == [27.0, 24.0]


def test_quick_simulation_series_rejects_unknown_and_tampered_results(client):
    assert client.get("/api/simulations/not-a-simulation/series").status_code == 404
    body = client.post(
        "/api/simulations",
        json={"model_name": "DataCenterRoom", "parameters": {"Q_it": 50000}},
    ).json()
    raw_path = Path(body["result_file"])
    raw_path.write_text(raw_path.read_text() + "\n")
    compromised = client.get(f"/api/simulations/{body['spec_id']}/series")
    assert compromised.status_code == 409
    assert "SHA-256 integrity" in compromised.json()["detail"]


def test_model_validation_endpoint(client):
    response = client.get("/api/models/DataCenterRoom/validation")
    assert response.status_code == 200
    report = response.json()
    assert report["status"] == "conceptual" and report["checks_status"] == "passed"
    assert len(report["reference_cases"]) == 7


def test_structured_report_edit_validation_revision_and_markdown_export(client):
    run_id = client.post("/api/runs", json={"topic": "editable report", "auto": True}).json()["run_id"]
    _wait(client, run_id)
    document = client.get(f"/api/runs/{run_id}/report/document").json()
    assert [section["kind"] for section in document["sections"]] == [
        "introduction", "research-synthesis", "method", "results-discussion", "conclusion",
        "claims-evidence", "references"
    ]
    edited = client.patch(
        f"/api/runs/{run_id}/report/sections/introduction",
        json={"content": "Edited introduction [1].", "expected_version": document["version"]},
    )
    assert edited.status_code == 200
    assert edited.json()["version"] == document["version"] + 1
    conflict = client.patch(
        f"/api/runs/{run_id}/report/sections/introduction",
        json={"content": "Stale edit", "expected_version": document["version"]},
    )
    assert conflict.status_code == 409
    validation = client.get(f"/api/runs/{run_id}/report/validation").json()
    assert validation["valid"] is True
    revisions = client.get(f"/api/runs/{run_id}/report/revisions").json()
    assert len(revisions) >= 1
    export = client.get(f"/api/runs/{run_id}/report/export?format=md")
    assert export.status_code == 200 and export.content.startswith(b"# editable report")


def test_api_flow_from_thesis_suggestion_to_editable_report(client, monkeypatch):
    idea = ThesisIdea(
        id="idea-1", rank=1, title="Cooling saturation resilience",
        research_question="When does cooling saturate?", model_names=["DataCenterRoom"],
        rank_score=92, rank_explanation="Direct registry fit.",
    )
    monkeypatch.setattr("rcp.api.main.generate_thesis_ideas", lambda profile: [idea])
    suggestions = client.post("/api/thesis-ideas", json={"domain": "data-center cooling"})
    assert suggestions.status_code == 200 and suggestions.json()[0]["title"] == idea.title
    response = client.post(
        "/api/runs",
        json={
            "topic": idea.title, "auto": True, "thesis_idea": idea.model_dump(),
            "thesis_profile": {"domain": "data-center cooling", "interests": ["resilience"]},
        },
    )
    run_id = response.json()["run_id"]
    detail = _wait(client, run_id)
    assert detail["thesis_idea"]["id"] == "idea-1"
    assert detail["state"]["thesis_profile"]["interests"] == ["resilience"]
    assert client.get(f"/api/runs/{run_id}/report/document").status_code == 200


def test_results_manifest_and_reproducibility_export(client):
    run_id = client.post("/api/runs", json={"topic": "reproducible", "auto": True}).json()["run_id"]
    _wait(client, run_id)
    results = client.get(f"/api/runs/{run_id}/results")
    assert results.status_code == 200
    assert results.json()["status"] == "ok"
    assert results.json()["quality_report"]["valid"] is True
    assert len(results.json()["analysis_protocol_sha256"]) == 64
    assert len(results.json()["experiment_plan_sha256"]) == 64
    assert len(results.json()["raw_dataset_sha256"]) == 64
    assert results.json()["cases"][0]["result_file_integrity"] == "verified"
    assert len(results.json()["cases"][0]["result_file_sha256"]) == 64
    revisions = client.get(f"/api/runs/{run_id}/results/revisions")
    assert revisions.status_code == 200
    assert len(revisions.json()) == 1 and revisions.json()[0]["current"] is True
    revision = client.get(
        f"/api/runs/{run_id}/results/revisions/{revisions.json()[0]['id']}"
    )
    assert revision.status_code == 200
    assert revision.json()["analysis_revision_id"] == revisions.json()[0]["id"]
    assert client.get(f"/api/runs/{run_id}/results/revisions/not-a-hash").status_code == 404
    manifest = client.get(f"/api/runs/{run_id}/manifest")
    assert manifest.status_code == 200
    assert manifest.json()["run_id"] == run_id
    assert "api_key" not in manifest.text.lower()
    export = client.get(f"/api/runs/{run_id}/artifacts/export")
    assert export.status_code == 200
    assert export.headers["content-type"] == "application/zip"
    assert export.content.startswith(b"PK")


def test_terminal_runs_can_be_archived_and_retry_requires_a_checkpoint(client, monkeypatch):
    run_id = client.post("/api/runs", json={"topic": "lifecycle", "auto": True}).json()["run_id"]
    _wait(client, run_id)

    archived = client.patch(f"/api/runs/{run_id}", json={"archived": True})
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None
    restored = client.patch(f"/api/runs/{run_id}", json={"archived": False})
    assert restored.status_code == 200
    assert restored.json()["archived_at"] is None

    import rcp.api.main as api_main

    api_main.manager._bump(run_id, status="failed", retryable=True, error="transient failure")
    submitted = []
    monkeypatch.setattr(
        api_main.manager.pool, "submit",
        lambda function, *args: submitted.append((function, args)),
    )
    retried = client.post(f"/api/runs/{run_id}/retry")
    assert retried.status_code == 200
    assert retried.json()["status"] == "resuming"
    assert retried.json()["retry_count"] == 1
    assert len(submitted) == 1

    api_main.manager._bump(run_id, status="failed", retryable=False)
    refused = client.post(f"/api/runs/{run_id}/retry")
    assert refused.status_code == 409
    assert "no resumable checkpoint" in refused.json()["detail"]


def test_revision_series_is_case_scoped_and_fails_closed_on_raw_tampering(client):
    run_id = client.post("/api/runs", json={"topic": "series integrity", "auto": True}).json()["run_id"]
    _wait(client, run_id)
    results = client.get(f"/api/runs/{run_id}/results").json()
    revision_id = client.get(f"/api/runs/{run_id}/results/revisions").json()[0]["id"]
    case = results["cases"][0]

    series = client.get(
        f"/api/runs/{run_id}/series",
        params={"case_id": case["case_id"], "revision_id": revision_id},
    )
    assert series.status_code == 200
    assert series.json()["T"] == [27.0, 24.0]

    raw_path = Path(case["result_file"])
    raw_path.write_text(raw_path.read_text() + "\n")
    compromised = client.get(
        f"/api/runs/{run_id}/series",
        params={"case_id": case["case_id"], "revision_id": revision_id},
    )
    assert compromised.status_code == 409
    assert "SHA-256 integrity" in compromised.json()["detail"]


def test_supervisor_acceptance_is_versioned_and_final(client):
    run_id = client.post("/api/runs", json={"topic": "accepted cycle", "auto": True}).json()["run_id"]
    detail = _wait(client, run_id)
    response = client.post(
        f"/api/runs/{run_id}/review",
        json={"decision": "accept", "expected_version": detail["version"]},
    )
    assert response.status_code == 200
    assert response.json()["decision"] == "accept"
    assert response.json()["successor_run_id"] is None
    refreshed = client.get(f"/api/runs/{run_id}").json()
    assert refreshed["review"]["decision"] == "accept"
    duplicate = client.post(
        f"/api/runs/{run_id}/review",
        json={"decision": "accept", "expected_version": refreshed["version"]},
    )
    assert duplicate.status_code == 409
    lineage = client.get(f"/api/runs/{run_id}/lineage").json()
    assert lineage["root_run_id"] == run_id and len(lineage["runs"]) == 1
    exported = client.get(f"/api/runs/{run_id}/artifacts/export")
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        assert any(name.endswith("/review.json") for name in archive.namelist())
    from rcp.api.manager import RunManager
    reloaded = RunManager()
    assert reloaded.get(run_id)["review"]["decision"] == "accept"
    assert reloaded.lineage(run_id).runs[0].run_id == run_id
    reloaded.pool.shutdown(wait=False)


def test_plan_and_hypothesis_reviews_create_human_gated_successors(client):
    plan_parent = client.post("/api/runs", json={"topic": "revise plan", "auto": True}).json()["run_id"]
    plan_detail = _wait(client, plan_parent)
    original_plan = Path(plan_detail["state"]["report_path"]).read_bytes()
    revised = client.post(
        f"/api/runs/{plan_parent}/review",
        json={
            "decision": "revise_plan", "feedback": "Use a narrower experiment horizon.",
            "expected_version": plan_detail["version"],
        },
    )
    assert revised.status_code == 200
    plan_child = revised.json()["successor_run_id"]
    child_detail = _wait(client, plan_child, statuses=("waiting_gate",))
    assert child_detail["gate"]["gate"] == "spec_approval"
    assert child_detail["entry_point"] == "spec" and child_detail["auto"] is False
    assert child_detail["parent_run_id"] == plan_parent and child_detail["root_run_id"] == plan_parent
    assert child_detail["node_history"][0]["node"] == "spec_compile"
    assert Path(plan_detail["state"]["report_path"]).read_bytes() == original_plan

    hypothesis_parent = client.post("/api/runs", json={"topic": "refine hypothesis", "auto": True}).json()["run_id"]
    hypothesis_detail = _wait(client, hypothesis_parent)
    refined = client.post(
        f"/api/runs/{hypothesis_parent}/review",
        json={
            "decision": "refine_hypothesis", "feedback": "Test the saturation boundary explicitly.",
            "expected_version": hypothesis_detail["version"],
        },
    )
    hypothesis_child = refined.json()["successor_run_id"]
    child_detail = _wait(client, hypothesis_child, statuses=("waiting_gate",))
    assert child_detail["gate"]["gate"] == "hypothesis_selection"
    assert child_detail["entry_point"] == "hypothesis"
    assert child_detail["node_history"][0]["node"] == "hypothesis_gen"
    lineage = client.get(f"/api/runs/{hypothesis_child}/lineage").json()
    assert [item["run_id"] for item in lineage["runs"]] == [hypothesis_parent, hypothesis_child]


def test_reanalysis_successor_reuses_verified_raw_data_without_modelica(client):
    parent = client.post("/api/runs", json={"topic": "protocol sensitivity", "auto": True}).json()["run_id"]
    detail = _wait(client, parent)
    before = client.get(f"/api/runs/{parent}/results").json()
    revised = client.post(
        f"/api/runs/{parent}/review",
        json={
            "decision": "reanalyse", "feedback": "Test a lower thermal threshold.",
            "expected_version": detail["version"],
            "protocol_changes": {"thermal_threshold_degC": 26.0},
        },
    )
    assert revised.status_code == 200, revised.text
    child = revised.json()["successor_run_id"]
    child_detail = _wait(client, child)
    assert child_detail["status"] == "done" and child_detail["entry_point"] == "reanalysis"
    after = client.get(f"/api/runs/{child}/results").json()
    assert after["raw_dataset_sha256"] == before["raw_dataset_sha256"]
    assert after["analysis_protocol_sha256"] != before["analysis_protocol_sha256"]
    assert after["experiment_plan_sha256"] != before["experiment_plan_sha256"]
    assert child_detail["node_history"][0]["node"] == "analyze_results"
    manifest = client.get(f"/api/runs/{child}/manifest").json()
    assert manifest["lineage"]["parent_run_id"] == parent


def test_reanalysis_rejects_unchanged_protocol_and_raw_tampering(client):
    parent = client.post("/api/runs", json={"topic": "blocked reanalysis", "auto": True}).json()["run_id"]
    detail = _wait(client, parent)
    unchanged = client.post(
        f"/api/runs/{parent}/review",
        json={
            "decision": "reanalyse", "feedback": "No effective change.",
            "expected_version": detail["version"],
            "protocol_changes": {"thermal_threshold_degC": 27.0},
        },
    )
    assert unchanged.status_code == 409
    refreshed = client.get(f"/api/runs/{parent}").json()
    raw = Path(refreshed["state"]["result_bundle"]["result_file"])
    raw.write_text(raw.read_text() + "\n")
    tampered = client.post(
        f"/api/runs/{parent}/review",
        json={
            "decision": "reanalyse", "feedback": "Change threshold.",
            "expected_version": refreshed["version"],
            "protocol_changes": {"thermal_threshold_degC": 26.0},
        },
    )
    assert tampered.status_code == 409
    assert "SHA-256" in tampered.json()["detail"]


# ---------- literature full text ----------

def _cache_pdf(payload: bytes) -> str:
    """Write a PDF into the content-addressed cache the way acquisition would."""
    import hashlib

    from rcp.literature.acquire import asset_path, pdf_path
    from rcp.objects import PdfAsset

    sha = hashlib.sha256(payload).hexdigest()
    path = pdf_path(sha)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    asset_path(sha).write_text(
        PdfAsset(
            status="available", sha256=sha, bytes=len(payload), page_count=1,
            oa_status="gold", license="cc-by", source_url="https://oa.example/p.pdf",
        ).model_dump_json()
    )
    return sha


def test_literature_pdf_is_served_with_range_support(client):
    from tests.pdf_fixture import make_pdf

    payload = make_pdf()
    sha = _cache_pdf(payload)

    whole = client.get(f"/api/literature/pdf/{sha}")
    assert whole.status_code == 200
    assert whole.headers["content-type"] == "application/pdf"
    assert whole.headers["accept-ranges"] == "bytes"
    assert whole.headers["etag"] == f'"{sha}"'
    assert whole.content == payload

    # pdf.js asks for byte ranges rather than pulling a whole paper.
    part = client.get(f"/api/literature/pdf/{sha}", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206
    assert part.headers["content-range"] == f"bytes 0-99/{len(payload)}"
    assert part.content == payload[:100]

    unsatisfiable = client.get(
        f"/api/literature/pdf/{sha}", headers={"Range": "bytes=99999999-"}
    )
    assert unsatisfiable.status_code == 416
    assert unsatisfiable.headers["content-range"] == f"bytes */{len(payload)}"


def test_literature_pdf_rejects_anything_that_is_not_a_content_hash(client):
    for bad in ["../../etc/passwd", "..%2f..%2fsecrets", "not-a-hash", "A" * 64, "b" * 63]:
        assert client.get(f"/api/literature/pdf/{bad}").status_code == 404


def test_literature_asset_exposes_licence_and_provenance(client):
    from tests.pdf_fixture import make_pdf

    sha = _cache_pdf(make_pdf())
    asset = client.get(f"/api/literature/assets/{sha}").json()
    assert asset["status"] == "available"
    assert asset["license"] == "cc-by"
    assert asset["oa_status"] == "gold"
    assert client.get(f"/api/literature/assets/{'c' * 64}").status_code == 404


def test_every_interrupt_gate_is_registered_with_the_manager():
    """A gate the manager does not know is mislabelled and unanswerable in the UI."""
    import re as _re
    from pathlib import Path as _Path

    from rcp.api.manager import GATE_NODES, NODE_ORDER

    source = _Path("src/rcp/graph/nodes.py").read_text()
    emitted = set(_re.findall(r'"gate":\s*"([a-z_]+)"', source))
    assert emitted, "expected at least one interrupt gate in the graph"
    assert emitted <= set(GATE_NODES), f"unregistered gates: {emitted - set(GATE_NODES)}"
    for gate in emitted:
        assert GATE_NODES[gate] in NODE_ORDER


def test_an_excluded_paper_cannot_reach_a_gap_or_a_claim(client):
    """Exclusion is enforced structurally: the card is simply absent downstream."""
    run_id = client.post("/api/runs", json={"topic": "curated run"}).json()["run_id"]
    detail = _wait(client, run_id, statuses=("waiting_gate",))
    assert detail["gate"]["gate"] == "literature_triage"

    # The fixture yields a single paper, so excluding it must be refused rather
    # than producing a run with no literature at all.
    refused = client.post(
        f"/api/runs/{run_id}/gate",
        json={"included_paper_ids": [], "exclusions": [{"paper_id": "p1", "reason": "off-topic"}]},
    )
    assert refused.status_code == 200  # accepted by the API, rejected inside the node
    failed = _wait(client, run_id, statuses=("failed",))
    assert "at least one paper" in failed["error"]


def test_auto_runs_record_that_no_human_curated_the_literature(client):
    run_id = client.post("/api/runs", json={"topic": "auto topic", "auto": True}).json()["run_id"]
    detail = _wait(client, run_id)
    assert detail["status"] == "done"

    triage = detail["state"]["literature_triage"]
    assert triage["mode"] == "auto"
    assert any("No human literature triage" in w for w in triage["warnings"])

    # And the disclosure travels with the synthesis every consumer reads.
    synthesis = client.get(f"/api/runs/{run_id}/synthesis").json()
    assert any("No human literature triage" in w for w in synthesis["warnings"])


def test_triage_is_recorded_as_a_run_artifact_not_a_snapshot_edit(client):
    run_id = client.post("/api/runs", json={"topic": "auto topic", "auto": True}).json()["run_id"]
    _wait(client, run_id)
    from rcp.config import data_dir

    triage_file = data_dir() / "runs" / run_id / "literature" / "triage.json"
    assert triage_file.is_file()
    manifest = client.get(f"/api/runs/{run_id}/manifest").json()
    paths = {artifact["path"] for artifact in manifest["artifacts"]}
    assert "literature/triage.json" in paths, "human input must be hashed into the manifest"


def _seed_pdf_for(paper_id: str, run_id: str, client, pages: list[str]):
    """Attach a real cached PDF to a paper already in a paused run's state."""
    import hashlib

    from rcp.api.main import manager
    from rcp.literature.acquire import asset_path, pdf_path
    from rcp.objects import PdfAsset
    from tests.pdf_fixture import make_pdf

    payload = make_pdf(pages)
    sha = hashlib.sha256(payload).hexdigest()
    path = pdf_path(sha)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    asset = PdfAsset(status="available", sha256=sha, bytes=len(payload), page_count=len(pages),
                     oa_status="gold", license="cc-by")
    asset_path(sha).write_text(asset.model_dump_json())

    # Put the asset onto the card the graph is holding, as acquisition would have.
    state = manager.state_snapshot(run_id)
    for card in state["paper_cards"]:
        if card["id"] == paper_id:
            card["pdf"] = asset.model_dump(mode="json")
    manager.graph.update_state({"configurable": {"thread_id": run_id}}, {"paper_cards": state["paper_cards"]})
    return sha


def test_full_text_reaches_its_tier_only_through_a_human_confirmation(client, monkeypatch):
    run_id = client.post("/api/runs", json={"topic": "full text run"}).json()["run_id"]
    detail = _wait(client, run_id, statuses=("waiting_gate",))
    assert detail["gate"]["gate"] == "literature_triage"
    assert detail["state"]["paper_cards"][0]["extraction_basis"] == "title"

    body = "Raising the chilled-water setpoint reduced chiller energy by 14 percent."
    sha = _seed_pdf_for("p1", run_id, client, [body])

    from rcp.objects import PaperCardPatch, ResearchFinding
    import rcp.literature.fulltext as fulltext

    calls: list[str] = []

    def fake_extract(*args, **kwargs):
        calls.append("called")
        return PaperCardPatch(
            method="Simulation of nine matched pairs",
            findings=[ResearchFinding(id="x", paper_id="x", statement="Energy fell 14%.",
                                      direction="decrease", source_pages=[1], quote=body)],
        )

    monkeypatch.setattr(fulltext, "llm_json", fake_extract)

    proposal = client.post(f"/api/runs/{run_id}/literature/full-text", json={"paper_id": "p1"})
    assert calls, "the substituted extractor must be the one that ran, not a live provider"
    assert proposal.status_code == 200
    extraction = proposal.json()
    assert extraction["status"] == "proposed"
    assert extraction["proposed"]["findings"][0]["id"] == "p1:finding:ft1"

    # A proposal on its own must not move the tier.
    still = client.get(f"/api/runs/{run_id}").json()
    assert still["state"]["paper_cards"][0]["extraction_basis"] == "title"

    client.post(f"/api/runs/{run_id}/gate", json={
        "included_paper_ids": ["p1"], "reviewer": "gsw",
        "full_text_confirmations": [
            {"extraction_id": extraction["id"], "accepted": True,
             "accepted_fields": ["method", "findings"]},
        ],
    })
    detail = _wait(client, run_id, statuses=("waiting_gate",))
    card = detail["state"]["paper_cards"][0]
    assert card["extraction_basis"] == "full_text"
    assert card["field_provenance"]["method"] == ["full_text", f"pdf:{sha[:12]}", "confirmed:gsw"]
    assert card["findings"][0]["source_pages"] == [1]


def test_full_text_extraction_is_refused_outside_the_triage_gate(client):
    run_id = client.post("/api/runs", json={"topic": "auto topic", "auto": True}).json()["run_id"]
    _wait(client, run_id)
    refused = client.post(f"/api/runs/{run_id}/literature/full-text", json={"paper_id": "p1"})
    assert refused.status_code == 409
    assert "triage gate" in refused.json()["detail"]


def test_an_automatic_run_can_never_produce_a_full_text_card(client):
    run_id = client.post("/api/runs", json={"topic": "auto topic", "auto": True}).json()["run_id"]
    detail = _wait(client, run_id)
    assert detail["status"] == "done"
    assert all(card["extraction_basis"] != "full_text" for card in detail["state"]["paper_cards"])


# ---------- reviewer annotations ----------

def test_annotations_are_accepted_at_any_point_and_reach_the_manifest(client):
    run_id = client.post("/api/runs", json={"topic": "auto topic", "auto": True}).json()["run_id"]
    _wait(client, run_id)

    created = client.post(f"/api/runs/{run_id}/annotations", json={
        "evidence_id": "claim:1", "kind": "comment", "body": "Check Table 3.", "author": "gsw",
    })
    assert created.status_code == 201

    listed = client.get(f"/api/runs/{run_id}/annotations").json()
    assert [item["body"] for item in listed] == ["Check Table 3."]

    manifest = client.get(f"/api/runs/{run_id}/manifest").json()
    paths = {artifact["path"] for artifact in manifest["artifacts"]}
    assert "annotations.jsonl" in paths, "the annotation log must be hashed like any artifact"

    bundle = client.get(f"/api/runs/{run_id}/artifacts/export")
    with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
        assert any(name.endswith("annotations.jsonl") for name in archive.namelist())


def test_an_annotation_on_an_unknown_object_is_refused(client):
    run_id = client.post("/api/runs", json={"topic": "auto topic", "auto": True}).json()["run_id"]
    _wait(client, run_id)
    refused = client.post(f"/api/runs/{run_id}/annotations", json={
        "evidence_id": "claim:99", "body": "About nothing.", "author": "gsw",
    })
    assert refused.status_code == 422
    assert "unknown evidence id" in refused.json()["detail"]


def test_a_blocking_dispute_holds_up_acceptance_until_resolved(client):
    run_id = client.post("/api/runs", json={"topic": "auto topic", "auto": True}).json()["run_id"]
    detail = _wait(client, run_id)

    blocker = client.post(f"/api/runs/{run_id}/annotations", json={
        "evidence_id": "claim:1", "kind": "flag", "severity": "blocker",
        "body": "This claim overstates the effect.", "author": "gsw",
    }).json()

    refused = client.post(f"/api/runs/{run_id}/review", json={
        "decision": "accept", "expected_version": detail["version"],
    })
    assert refused.status_code == 409
    assert "blocking reviewer annotation" in refused.json()["detail"]

    client.post(f"/api/runs/{run_id}/annotations/{blocker['id']}/resolve",
                json={"resolution_note": "Reworded.", "author": "supervisor"})
    accepted = client.post(f"/api/runs/{run_id}/review", json={
        "decision": "accept", "expected_version": client.get(f"/api/runs/{run_id}").json()["version"],
    })
    assert accepted.status_code == 200


def test_a_dispute_does_not_change_the_workflow_outcome(client):
    """The run still completes; the objection is disclosed, not enforced."""
    run_id = client.post("/api/runs", json={"topic": "auto topic", "auto": True}).json()["run_id"]
    detail = _wait(client, run_id)
    assert detail["status"] == "done"
    assert detail["state"]["review_bundle"]["valid"] is True


# ---------- evaluation rubric ----------

def _scores(**overrides):
    from rcp.objects import RUBRIC_DIMENSIONS

    return {**dict.fromkeys(RUBRIC_DIMENSIONS, 4), **overrides}


def test_peer_scores_stay_concealed_until_two_reviewers_have_submitted(client):
    run_id = client.post("/api/runs", json={"topic": "auto topic", "auto": True}).json()["run_id"]
    _wait(client, run_id)

    first = client.post(f"/api/runs/{run_id}/evaluation",
                        json={"reviewer_id": "alice", **_scores()})
    assert first.status_code == 201

    # Reviewer B sees nothing of A's judgement before submitting their own.
    hidden = client.get(f"/api/runs/{run_id}/evaluation", params={"reviewer_id": "bob"}).json()
    assert hidden["revealed"] is False
    assert hidden["scorecards"] == []
    assert hidden["summary"] is None
    assert hidden["count"] == 1

    # A always gets their own card back.
    mine = client.get(f"/api/runs/{run_id}/evaluation", params={"reviewer_id": "alice"}).json()
    assert [card["reviewer_id"] for card in mine["scorecards"]] == ["alice"]

    client.post(f"/api/runs/{run_id}/evaluation",
                json={"reviewer_id": "bob", **_scores(missing_evidence_visibility=2)})
    revealed = client.get(f"/api/runs/{run_id}/evaluation").json()
    assert revealed["revealed"] is True
    assert len(revealed["scorecards"]) == 2
    assert "missing_evidence_visibility" in revealed["summary"]["disagreement_dimensions"]


def test_the_api_states_that_blinding_is_a_claim_not_a_guarantee(client):
    run_id = client.post("/api/runs", json={"topic": "auto topic", "auto": True}).json()["run_id"]
    _wait(client, run_id)
    body = client.get(f"/api/runs/{run_id}/evaluation").json()
    assert "self-declared" in body["blinding_note"]


def test_out_of_range_and_duplicate_scores_are_refused(client):
    run_id = client.post("/api/runs", json={"topic": "auto topic", "auto": True}).json()["run_id"]
    _wait(client, run_id)
    assert client.post(f"/api/runs/{run_id}/evaluation",
                       json={"reviewer_id": "a", **_scores(claim_verification_effort=6)}
                       ).status_code == 422
    assert client.post(f"/api/runs/{run_id}/evaluation", json={"reviewer_id": "a", **_scores()}
                       ).status_code == 201
    duplicate = client.post(f"/api/runs/{run_id}/evaluation", json={"reviewer_id": "a", **_scores()})
    assert duplicate.status_code == 409
    assert "already scored" in duplicate.json()["detail"]


def test_the_scoring_packet_is_stripped_of_the_platforms_own_confidence(client):
    run_id = client.post("/api/runs", json={"topic": "auto topic", "auto": True}).json()["run_id"]
    _wait(client, run_id)
    packet = client.get(f"/api/runs/{run_id}/evaluation/packet").json()
    flat = json.dumps(packet)
    for banned in ["selection_score", "ranking_factors", "peer_review_confidence", "rank_score"]:
        assert banned not in flat, f"{banned} would anchor the judgement being measured"

    baseline = client.get(f"/api/runs/{run_id}/evaluation/packet",
                          params={"condition": "baseline"}).json()
    # The documented baseline: titles and abstracts only, plus the raw data.
    assert set(baseline["packet"]) == {"papers", "raw_result_files"}
    assert "claims" not in baseline["packet"]


def test_the_event_stream_emits_a_keepalive_while_a_run_is_parked(client, monkeypatch):
    """A run waiting at a human gate changes no version, so it would send zero bytes.

    Reverse proxies drop idle connections, and the symptom -- a timeline that
    silently stops updating -- only ever appears in front of a real proxy. The
    keepalive comment is the fix; EventSource ignores comment lines.
    """
    import rcp.api.main as api_main

    # The run sits at one version for a few polls (the "parked at a gate" case),
    # then finishes so the stream terminates and the response can close. An
    # endlessly-open stream deadlocks TestClient on exit.
    polls = iter([1, 2, 3, 4])
    def fake_get(run_id):
        if next(polls, None) is None:
            return {"version": 8, "status": "done", "run_id": "parked"}
        return {"version": 7, "status": "running", "run_id": "parked"}

    monkeypatch.setattr(api_main, "SSE_KEEPALIVE_SECONDS", 0.0)
    monkeypatch.setattr(api_main.manager, "get", fake_get)
    health = api_main.manager.checkpoint_store_health()  # captured before stubbing
    monkeypatch.setattr(
        api_main.manager, "checkpoint_snapshot", lambda run_id: ({}, health, None)
    )
    monkeypatch.setattr(
        api_main, "derive_run_outcome",
        lambda rec, state: SimpleNamespace(model_dump=lambda mode="json": {}),
    )

    with client.stream("GET", "/api/runs/parked/events") as response:
        assert response.status_code == 200
        frames = [line for line in response.iter_lines() if line]

    assert frames[0].startswith("data: ")           # the initial state still goes out
    assert ": keepalive" in frames                  # and the parked polls stay warm
    assert frames[-1].startswith("data: ")          # the terminal state closes the stream
