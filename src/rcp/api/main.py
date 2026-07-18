"""FastAPI backend for the RCP2026/11 web UI."""

import asyncio
import json
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from rcp.api.manager import NODE_ORDER, RunManager
from rcp.config import data_dir
from rcp.objects import ExperimentSpec
from rcp.simulation.collector import build_result_bundle, load_series
from rcp.simulation.registry import get_model, load_registry
from rcp.simulation.runner import SimulationError, run_simulation

app = FastAPI(title="RCP2026/11 API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = RunManager()


class CreateRun(BaseModel):
    topic: str
    constraints: list[str] = Field(default_factory=list)
    auto: bool = False


class GateAnswer(BaseModel):
    answer: str


class SimRequest(BaseModel):
    model_name: str = "DataCenterRoom"
    parameters: dict[str, float] = Field(default_factory=dict)
    stop_time: float | None = None


@app.get("/api/health")
def health():
    return {"ok": True, "nodes": NODE_ORDER}


# ---------- runs ----------

@app.post("/api/runs")
def create_run(body: CreateRun):
    if not body.topic.strip():
        raise HTTPException(422, "topic must not be empty")
    run_id = manager.create(body.topic.strip(), body.constraints, body.auto)
    return {"run_id": run_id}


@app.get("/api/runs")
def list_runs():
    return manager.list_runs()


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str):
    try:
        rec = manager.get(run_id)
    except KeyError:
        raise HTTPException(404, f"unknown run {run_id}")
    rec["state"] = manager.state_snapshot(run_id)
    return rec


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str):
    try:
        manager.get(run_id)
    except KeyError:
        raise HTTPException(404, f"unknown run {run_id}")

    async def stream():
        last_version = -1
        while True:
            rec = manager.get(run_id)
            if rec["version"] != last_version:
                last_version = rec["version"]
                rec["state"] = manager.state_snapshot(run_id)
                yield f"data: {json.dumps(rec)}\n\n"
                if rec["status"] in ("done", "failed"):
                    return
            await asyncio.sleep(0.7)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/runs/{run_id}/gate")
def answer_gate(run_id: str, body: GateAnswer):
    try:
        manager.answer_gate(run_id, body.answer)
    except KeyError:
        raise HTTPException(404, f"unknown run {run_id}")
    except ValueError as err:
        raise HTTPException(409, str(err))
    return {"ok": True}


@app.get("/api/runs/{run_id}/report", response_class=PlainTextResponse)
def run_report(run_id: str):
    path = data_dir() / "runs" / run_id / "report.md"
    if not path.exists():
        raise HTTPException(404, "report not drafted yet")
    return path.read_text()


@app.get("/api/runs/{run_id}/series")
def run_series(run_id: str, points: int = 200):
    """Time series from the run's simulation CSV, downsampled for charting."""
    base = data_dir() / "runs" / run_id
    candidates = list(base.glob("sim/*_res.csv")) + list(base.glob("*_res.csv"))
    if not candidates:
        raise HTTPException(404, "no simulation results for this run")
    series = load_series(candidates[0])
    n = len(next(iter(series.values()), []))
    step = max(1, n // points)
    return {k: v[::step] for k, v in series.items()}


# ---------- knowledge base ----------

@app.get("/api/memory")
def memory_topics():
    root = data_dir() / "memory"
    topics = []
    if root.exists():
        for d in sorted(root.iterdir()):
            pointer = d / "latest.json"
            if not pointer.exists():
                continue
            snap = d / json.loads(pointer.read_text())["snapshot"]
            cards_file = snap / "paper_cards.json"
            count = len(json.loads(cards_file.read_text())) if cards_file.exists() else 0
            topics.append({"slug": d.name, "cards": count, "snapshot": snap.name})
    return topics


@app.get("/api/memory/{slug}")
def memory_detail(slug: str):
    d = data_dir() / "memory" / slug
    pointer = d / "latest.json"
    if not pointer.exists():
        raise HTTPException(404, f"unknown topic {slug}")
    snap = d / json.loads(pointer.read_text())["snapshot"]
    return {
        "slug": slug,
        "snapshot": snap.name,
        "paper_cards": json.loads((snap / "paper_cards.json").read_text()),
        "themes": json.loads((snap / "themes.json").read_text()),
    }


# ---------- models & simulations ----------

@app.get("/api/models")
def models():
    return {
        name: {
            "description": m.description,
            "default_stop_time": m.default_stop_time,
            "outputs": m.outputs,
            "parameters": {p: s.model_dump() for p, s in m.parameters.items()},
        }
        for name, m in load_registry().items()
    }


@app.post("/api/simulations")
def quick_simulate(body: SimRequest):
    try:
        info = get_model(body.model_name)
    except KeyError as err:
        raise HTTPException(404, str(err))
    spec = ExperimentSpec(
        id="manual-" + uuid.uuid4().hex[:6],
        hypothesis_id="manual",
        model_name=body.model_name,
        parameters=body.parameters,
        outputs=info.outputs,
        stop_time=body.stop_time or info.default_stop_time,
    )
    workdir = data_dir() / "runs" / spec.id
    try:
        csv_path, log = run_simulation(spec, workdir)
    except SimulationError as err:
        raise HTTPException(422, str(err)[:1500])
    return build_result_bundle(spec, workdir, csv_path, log).model_dump()


# ---------- static frontend (production) ----------

_dist = Path(__file__).parent.parent.parent.parent / "webapp" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="webapp")
