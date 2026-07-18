# Claude Design Prompt — RCP11 Web UI

Copy everything below the line into a fresh Claude Code session opened at the
`rcp-platform` repo root. It is fully self-contained: Claude will design and
build the production web app without needing any other context.

---

## Role & Goal

You are building the **production web UI** for an existing, working Python
platform: **RCP2026/11 — AI Agent Workflow for Scientific Discovery in Data
Center Digital Twins** (a university capstone project). The platform is a
closed-loop AI research system: given a research topic, it builds a literature
knowledge base, mines gaps, generates hypotheses, compiles a simulation
experiment, runs OpenModelica physics simulations, analyzes results, and drafts
an evidence-linked technical report — pausing at two human-approval gates.

Today it is CLI-only. Your job: add a **FastAPI backend** (`src/rcp/api/`) that
wraps the existing package, and a **React frontend** (`webapp/`) that makes the
whole loop operable from the browser. Build it production-quality: typed,
tested, documented.

## The existing system (reference — do not modify existing modules)

Repo layout (Python 3.11+, installed with `uv pip install -e ".[dev]"`, venv at `.venv/`):

```
src/rcp/
  objects.py              # the six standard data objects (schemas below)
  config.py               # pydantic-settings; .env holds OPENROUTER_API_KEY etc.
  llm.py                  # provider-agnostic chat model + llm_json helper
  cli.py                  # typer CLI: run / memory-build / sim-run / models / verify-llm
  graph/
    state.py              # RCPState (global workflow state, pydantic)
    nodes.py              # all workflow nodes incl. the two human gates
    build.py              # build_graph(checkpointer) -> compiled LangGraph; make_checkpointer()
  memory/                 # Module 1: pipeline.py, connectors.py (OpenAlex/Semantic Scholar),
                          # dedup.py, papercard.py, theme.py, store.py (MemoryStore)
  simulation/
    registry.py           # load_registry(), get_model(), validate_spec() -> violations list
    runner.py             # run_simulation(spec, workdir) via omc (docker or local)
    collector.py          # load_series(csv), compute_metrics(), build_result_bundle()
  models_library/         # DataCenterRoom.mo + registry.json
```

### The workflow graph (LangGraph)

Nodes in execution order — the UI's run stepper must mirror these:

```
research_memory_build → gap_mining → hypothesis_gen → select_hypothesis (GATE 1)
→ spec_compile → approve_spec (GATE 2) → run_modelica → analyze_results → draft_report
```

`approve_spec` has a conditional edge: rejection with feedback routes **back to
`spec_compile`** (revision loop, max 3 attempts), approval routes to `run_modelica`.

Mechanics you must build against (already implemented, do not change):

- `from rcp.graph.build import build_graph` → `graph = build_graph()` (uses a
  SQLite checkpointer at `data/checkpoints.sqlite`; every step is checkpointed
  and resumable).
- Start a run:
  `graph.invoke(RCPState(run_id=..., topic=ResearchTopic(title=..., constraints=[...]), auto=False), config={"configurable": {"thread_id": run_id}})`
- `invoke`/`stream` **block** until the graph finishes or hits a gate. On a
  gate, the returned state dict contains `"__interrupt__"`: a list whose first
  element has `.value` = the gate payload:
  - Gate 1: `{"gate": "hypothesis_selection", "question": ..., "options": ["H1: ...", "H2: ...", ...]}` — resume with the **index** of the chosen option as a string.
  - Gate 2: `{"gate": "spec_approval", "question": ..., "spec": {ExperimentSpec dict}}` — resume with `"yes"` to approve, or any other text as revision feedback.
- Resume: `graph.invoke(Command(resume=answer), config)` with the same
  `thread_id` (`from langgraph.types import Command`).
- For node-level progress, prefer `graph.stream(input, config, stream_mode="updates")`
  which yields `{node_name: partial_state_update}` per completed node.
- `RCPState(auto=True)` auto-resolves both gates (used for testing).

### The six standard data objects (`src/rcp/objects.py`, pydantic v2 — exact fields)

```python
class ResearchTopic:  title: str; constraints: list[str] = []; notes: str = ""

class PaperCard:      id, title: str; year: int|None; doi, url, venue: str|None
                      authors: list[str]; citations: int = 0; abstract: str
                      problem, method: str; metrics, limitations, tags: list[str]

class Hypothesis:     id, statement: str; rationale, expected_effect: str
                      variables, metrics, risks: list[str]

class ExperimentSpec: id, hypothesis_id, model_name: str
                      parameters: dict[str, float]; outputs: list[str]
                      stop_time: float = 86400; intervals: int = 500; description: str

class ResultBundle:   spec_id: str; status: "ok"|"failed"; workdir: str
                      result_file: str|None; metrics: dict[str, float]; log_excerpt: str

class Claim:          statement, evidence: str; confidence: "low"|"medium"|"high"
class ClaimBundle:    hypothesis_id: str; claims: list[Claim]; summary: str
```

`RCPState` (graph state) additionally holds: `run_id, topic, auto, paper_cards,
themes (dict tag→[titles]), gaps (list[str]), hypotheses, selected_hypothesis,
experiment_spec, spec_approved, spec_feedback, spec_attempts, result_bundle,
claim_bundle, report_path`.

### Storage layout (all under `data/`, gitignored)

```
data/memory/<topic-slug>/<UTC timestamp>/raw_papers.json | paper_cards.json | themes.json
data/memory/<topic-slug>/latest.json          # {"snapshot": "<timestamp>"}
data/runs/<run_id>/sim/                       # .mo, run.mos, <Model>_res.csv
data/runs/<run_id>/report.md                  # final markdown report
data/checkpoints.sqlite                       # LangGraph checkpoints
```

Simulation metrics keys: `T_peak_degC, T_avg_steady_degC, T_std_steady_degC,
E_cool_kWh, P_cool_avg_W`. Result CSVs have columns `time, T, Q_cool, P_cool, E_cool`.

The model registry (`rcp.simulation.registry.load_registry()`) returns
`{name: ModelInfo}` where ModelInfo has `description, default_stop_time,
outputs: list[str], parameters: dict[name, ParamSpec(default, min, max, unit, description)]`.

## Backend to build (`src/rcp/api/`, FastAPI)

Runs are long (minutes: paper fetching, LLM calls, simulation) and the graph is
blocking — execute each run in a **background thread** (ThreadPoolExecutor),
keep an in-process run manager keyed by `run_id` that records: status
(`running | waiting_gate | done | failed`), current node, node history with
timestamps, the pending gate payload, and the latest state snapshot. Stream
node completions to the frontend via **SSE** (`GET /api/runs/{id}/events`);
also support plain polling via the detail endpoint.

Endpoints:

```
POST /api/runs                  {topic, constraints?, auto?} -> {run_id}
GET  /api/runs                  list: id, topic, status, current_node, created_at
GET  /api/runs/{id}             full detail: status + node history + state snapshot
                                (hypotheses, spec, metrics, claims, report_path, gate payload)
GET  /api/runs/{id}/events      SSE: node_completed / gate_reached / run_done / run_failed
POST /api/runs/{id}/gate        {answer: str} -> resumes Command(resume=answer) in the worker
GET  /api/runs/{id}/report      report.md content (404 until drafted)
GET  /api/memory                topics with snapshot timestamps
GET  /api/memory/{slug}         latest snapshot: paper_cards + themes
GET  /api/models                registry with full parameter specs
POST /api/simulations           {model_name, parameters, stop_time?} -> run directly
                                (reuse run_simulation + build_result_bundle), return ResultBundle
GET  /api/simulations/{spec_id}/series   parsed CSV series for charting
```

Notes: recreate/reuse one `build_graph()` instance; after a process restart,
list historical runs from `data/runs/` + checkpoint DB (status "done"/"unknown"
is fine — don't over-engineer resume-after-restart). Add `fastapi`, `uvicorn`,
`sse-starlette` to `pyproject.toml`. Pytest the API with `auto=True` runs and
the LLM/simulation layers **mocked** (monkeypatch `rcp.llm.llm_json`,
`rcp.simulation.runner.run_simulation`) so tests run offline.

## Frontend to build (`webapp/`, Vite + React + TypeScript + Tailwind)

Screens (client-side routing):

1. **Dashboard** — run cards/table: topic, status badge, current node, elapsed
   time; live-updating via SSE; prominent "New Run" button.
2. **New Run** — topic input, constraints (tag input), auto-mode toggle,
   submit → navigate to Run Detail.
3. **Run Detail** — the centerpiece:
   - Horizontal **stepper of the 9 graph nodes** (names above) with
     pending/active/done/failed states, live via SSE.
   - **Gate 1 modal/panel**: hypothesis cards (statement, rationale, expected
     effect, risks) with a select button each.
   - **Gate 2 modal/panel**: the ExperimentSpec rendered as a labeled parameter
     table (with units/ranges from `/api/models`), Approve button + free-text
     "Request changes" box (revision loop; show attempt count of 3 max).
   - Tabs below the stepper: Papers (PaperCards), Gaps & Hypotheses, Experiment
     (spec + status + log excerpt on failure), Results (metric stat tiles +
     time-series line charts of T and P_cool from the series endpoint), Report
     (rendered markdown), Claims (statement/evidence/confidence list).
4. **Knowledge Base** — topic list → snapshot browser: searchable PaperCard
   grid (title, year, venue, tags, problem/method/limitations expandable) and a
   theme cloud/list from themes.json.
5. **Models & Simulations** — registry viewer (parameter table with defaults,
   ranges, units) and a "Quick simulate" form (parameter sliders/inputs bound
   to registry ranges) that calls `POST /api/simulations` and charts the result.

Design language: modern research-tool aesthetic — clean, data-dense, generous
tables, monospace for IDs/parameters, light and dark mode. Color-code workflow
stages consistently across stepper, badges, and tabs: knowledge/memory = cyan,
idea/hypothesis = blue, experiment/simulation = teal, analysis/writing = violet,
gates = amber. Status colors: running = blue (animated), waiting on gate =
amber, done = green, failed = red. Charts: simple, clearly labeled axes with
units, no chartjunk.

## Constraints

- **Do not modify** existing `rcp` modules (graph, memory, simulation, objects,
  cli) except: add the new `rcp/api/` subpackage and new dependencies in
  `pyproject.toml`. The CLI must keep working.
- Keep the stack lean: no state-management or component libraries beyond
  Tailwind + a small chart lib (recharts) + a markdown renderer; no auth (single
  local researcher); no database beyond what exists.
- `npm run dev` proxies `/api` to `localhost:8000`; document both dev and
  production (built assets served by FastAPI) modes in the README.
- Secrets: the backend reads the existing `.env`; never expose the API key to
  the frontend.

## Verify before declaring done

1. `pytest` — existing 10 tests plus your new API tests pass offline.
2. `uvicorn rcp.api.main:app` + `npm run dev`: create a run with auto=false
   from the UI, watch the stepper advance live, answer Gate 1 by clicking a
   hypothesis, reject the spec once with feedback at Gate 2 (verify it
   recompiles and returns to the gate), approve it, and confirm metrics tiles,
   charts, and the rendered report appear.
   (If OpenModelica/docker is unavailable in your environment, mock
   `run_simulation` and state this clearly in your summary.)
3. Quick-simulate flow on the Models screen produces a chart.
4. Dashboard reflects the finished run after a browser refresh.
