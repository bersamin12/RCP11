# RCP Platform — AI Agent Workflow for Scientific Discovery in Data Center Digital Twins

RCP2026/11 · Renaissance Capstone Project AY2026/27. Phases 1–2 implementation:
LangGraph backbone + Research Memory (Phase 1) and OpenModelica execution chain (Phase 2).
See [docs/PRD.md](docs/PRD.md) for full requirements.

## Quickstart

```bash
cd rcp-platform
conda create -n rcp python=3.13 && conda activate rcp
pip install -e ".[dev]"
# (alternative without conda: uv venv .venv && uv pip install -e ".[dev]" && source .venv/bin/activate)
cp .env.example .env        # fill in OPENROUTER_API_KEY

rcp verify-llm              # smoke-test the LLM provider
rcp models                  # list simulation models
rcp sim-run --set Q_it=60000 --stop-time 43200     # one simulation (needs docker or omc)
rcp memory-build "data center cooling optimization" # Module 1 only
rcp run "data center cooling optimization"          # full closed loop with human gates
rcp run "..." --auto        # auto-resolve gates (testing)
```

Run commands from the repo root (the `.env` and `data/` directory are resolved
relative to the working directory).

## What's implemented (PRD requirement IDs)

| Area | PRD IDs | Notes |
|---|---|---|
| Standard objects | §5.3 | `src/rcp/objects.py` — the contracts between roles |
| LangGraph backbone | §5.2, X.2 | `src/rcp/graph/` — SQLite checkpoints, resumable |
| Human gates | §5.4 | hypothesis selection + spec approval (with revision loop) |
| Research Memory | M1.1–M1.6 | `src/rcp/memory/` — OpenAlex + Semantic Scholar → PaperCards |
| Idea generation (MVP) | M2.1, M2.3 | gap mining + hypothesis nodes (deepen in Phase 3) |
| Scientific compiler | M3.1–M3.2 | `spec_compile` node + registry constraint checker |
| Simulation chain | M4.1, M4.2*, M4.4, M4.5 | `src/rcp/simulation/` — omc via Docker or local |
| Analysis (MVP) | M5.1, M5.4 | numeric metric engine + LLM ClaimBundle (deepen in Phase 5) |
| Writing (MVP) | M6.1 | report drafting with evidence links (deepen in Phase 5) |

*M4.2: MVP drives `omc` via `.mos` scripts (Docker image or local install). The
OMPython/`OMCSessionZMQ` interactive backend is the planned upgrade — the runner
backend is already pluggable (`RCP_OM_BACKEND`).

## Simulation backend

Either install OpenModelica locally (`omc` on PATH) or use Docker:

```bash
sudo usermod -aG docker $USER   # then log out/in
docker pull openmodelica/openmodelica:v1.25.0-minimal
```

The bundled `DataCenterRoom` model is self-contained (no Modelica Standard Library
dependencies). To add Buildings-library models (ChillerCooled, DXCooled): add the
`.mo`/package reference and an entry in `src/rcp/models_library/registry.json`,
and extend the `.mos` template in `runner.py` with `installPackage(Buildings)`.

## Architecture

```
cli.py                          typer CLI (run / memory-build / sim-run / models / verify-llm)
graph/   state.py               global workflow state (pydantic)
         nodes.py               all workflow nodes incl. human gates
         build.py               StateGraph assembly + SqliteSaver checkpointing
memory/  pipeline.py            query plan → fetch → dedup → extract → themes → snapshot
simulation/ registry.py         model registry + constraint checker
            runner.py           omc execution (docker/local), failure handler
            collector.py        CSV → ResultBundle + metric engine
objects.py                      ResearchTopic, PaperCard, Hypothesis, ExperimentSpec,
                                ResultBundle, ClaimBundle
llm.py                          provider-agnostic chat model + validated-JSON helper
```

Data lands in `data/`: `memory/<topic>/<timestamp>/` snapshots, `runs/<run_id>/`
(sim workdir + report.md), `checkpoints.sqlite`.

## Web UI

FastAPI backend (`src/rcp/api/`) + React frontend (`webapp/`), implementing the
Claude Design handoff (see `docs/UI_DESIGN_PROMPT.md` for the spec).

```bash
# development (two terminals)
uvicorn rcp.api.main:app --port 8000        # backend, from repo root
cd webapp && npm install && npm run dev     # frontend on :5173, proxies /api

# production (single server)
cd webapp && npm run build                  # emits webapp/dist
uvicorn rcp.api.main:app --port 8000        # serves the UI at http://localhost:8000
```

Screens: Dashboard (live run list), New Run, Run Detail (9-node stepper with
live SSE updates, Gate 1 hypothesis cards, Gate 2 spec approval with a
reject-and-revise loop, tabs for Papers / Gaps & Hypotheses / Experiment /
Results / Report / Claims), Knowledge Base browser, and Models with a
quick-simulate panel driven by the model registry.

Key endpoints: `POST /api/runs`, `GET /api/runs/{id}` (+ `/events` SSE,
`/report`, `/series`), `POST /api/runs/{id}/gate`, `GET /api/memory[/{slug}]`,
`GET /api/models`, `POST /api/simulations`.

## Tests

```bash
pytest        # offline: dedup/registry/collector units + API tests (LLM & sim mocked)
```
