# RCP Platform — AI Agent Workflow for Scientific Discovery in Data Center Digital Twins

RCP2026/11 · Renaissance Capstone Project AY2026/27. The platform combines a
resumable LangGraph research loop, provenance-aware Research Memory, a pinned
Modelica comparison benchmark, deterministic evidence review, and a versioned
report workspace.
See [docs/PRD.md](docs/PRD.md) for full requirements.

## Quickstart

```bash
cd rcp-platform
conda create -n rcp python=3.13 && conda activate rcp
pip install -e ".[dev]"
# (alternative without conda: uv venv .venv && uv pip install -e ".[dev]" && source .venv/bin/activate)
cp .env.example .env        # fill in OPENROUTER_API_KEY

rcp verify-llm              # smoke-test the LLM provider
rcp doctor                  # verify storage, registry, Docker/omc, and runtime image
rcp models                  # list simulation models
rcp sim-run --set Q_it=60000 --stop-time 43200     # one simulation (needs docker or omc)
rcp model-validate --model DataCenterRoom           # offline physics checks (CI-safe)
rcp memory-build "data center cooling optimization" # Module 1 only
rcp run "data center cooling optimization"          # full closed loop with human gates
rcp run "..." --auto        # auto-resolve gates (testing)
```

Run commands from the repo root (the `.env` and `data/` directory are resolved
relative to the working directory).

## Reproducible benchmark

The publication-oriented benchmark compares the Buildings 13.0.0 integrated
and non-integrated primary-secondary waterside-economizer examples. Its
pre-registered matrix contains 18 cases: two configurations × three room loads
(400/500/600 kW) × three chilled-water setpoints (6/8/10 °C), joined into nine
matched pairs.

```bash
rcp benchmark-setup          # build the pinned OM 1.26.3 + MSL 4.1.0 + Buildings 13 image
rcp benchmark-run --smoke    # one matched pair; useful before a full study
rcp benchmark-validate       # repeatability + pinned upstream Dymola trajectories
rcp benchmark-run            # full 18-case study
```

The first case for each model is compiled once; subsequent parameter cases
reuse that executable. Every case is checkpointed, so rerunning an interrupted
plan skips successful outputs. The workflow retries transient backend failures
once and requires an explicit revise/continue-partial/abort decision for other
failures.

Primary metrics are HVAC and IT energy, PUE, peak room temperature, thermal
degree-hours above 27 °C, cooling-mode hours, and mode-switch count. Raw CSV,
logs, comparisons, validation warnings, and SHA-256 hashes remain available.
OpenModelica produces isolated nonphysical mover-power impulses at some mode
transitions in this upstream example. The primary energy integral therefore
interpolates internal samples outside a pre-registered 0–2 MW physical screen
(using the nearest valid value at a boundary); the
raw upstream integral, raw power series, screened series, and excluded-sample
mask/count are retained as diagnostics. The UI defaults to the approved screened
series and provides an explicit raw-series toggle.

The pinned source revisions live in
`src/rcp/models_library/models.lock.json`. This is a library-regression
benchmark, not calibration against a physical data center.

## Scientific safeguards

- Paper-card fields state whether they came from a title, abstract, or full
  text. Missing abstracts are marked insufficient; the LLM is not asked to
  invent methods or limitations from a title.
- Research-memory snapshots preserve query/config metadata and can be reused by
  a later run.
- Abstract-backed paper cards capture discrete findings and study conditions.
  Structured gaps, contradictions, and weaker tensions retain their paper and
  finding IDs; title-only records cannot contribute findings or conflicts.
- Hypotheses are ranked reproducibly with fixed model-fit, evidence,
  testability, and opportunity weights. The LLM proposes candidates but does
  not assign the displayed score.
- Experiment plans, cases, comparison pairs, metric directions, and units are
  structured objects approved before execution. The approved plan also freezes
  metric formulas, numerical screens, plausibility ranges, comparison tie
  tolerances, and acceptance rules in a hashed analysis protocol. If that
  protocol changes, metrics are recomputed from the preserved raw CSV files
  without rerunning the physical simulation, and the reanalysis is disclosed.
  Every approved plan and executable case also has its own hash, preventing a
  changed parameter set from accidentally resuming against an older CSV.
- Every raw simulation CSV is content-addressed with SHA-256 before analysis. A mismatch fails
  study quality and blocks claims. Completed analyses are retained in an
  append-only revision directory keyed by the approved plan and raw dataset,
  so a reanalysis cannot erase the result it superseded.
- Whole-study checks verify case and metric completeness, matched-pair coverage,
  finite outputs, PUE plausibility, screened-sample fraction, and cooling-mode
  time balance, plus IT-energy monotonicity with declared load. Failed checks
  block claim generation; warnings remain attached to claims and reports.
- Comparative claims cite exact comparison, case, and paper IDs. Unsupported
  claim links fail closed before report drafting.
- Runs survive service restarts through SQLite checkpoints and persisted
  metadata. Node timings, LLM token usage (when supplied by the provider), code
  revision/dirty state, runtime versions, inputs, model versions, and artifact
  hashes are written to `manifest.json`.
- Checkpoint deserialization uses an explicit application-type allowlist.
  Missing, incompatible, or corrupt state is surfaced separately from legacy
  terminal artifacts instead of being treated as an empty workflow.
- Reports preserve evidence links, edit history, optimistic-lock conflicts,
  validation, and Markdown/DOCX/PDF export.

See [docs/EVALUATION.md](docs/EVALUATION.md) for the evaluation protocol and
acceptance criteria.

## What's implemented (PRD requirement IDs)

| Area | PRD IDs | Notes |
|---|---|---|
| Standard objects | §5.3 | `src/rcp/objects.py` — the contracts between roles |
| LangGraph backbone | §5.2, X.2 | `src/rcp/graph/` — SQLite checkpoints, resumable |
| Human gates | §5.4 | structured hypothesis, plan approval, and failure-recovery decisions |
| Research Memory | M1.1–M1.6 | OpenAlex + Semantic Scholar → ranked, provenance-aware PaperCards + frozen snapshots |
| Research synthesis | M2.1–M2.2 | evidence-backed gaps, strict contradictions, conditional tensions, and coverage disclosures |
| Thesis ideation | M2.3–M2.4 | five ranked thesis ideas plus deterministically ranked in-run hypotheses grounded in the registry and synthesis |
| Scientific compiler | M3.1–M3.2 | `spec_compile` node + registry constraint checker |
| Simulation chain | M4.1, M4.2*, M4.4, M4.5 | pinned Modelica runtime, compiled-template reuse, case checkpoints, retry/recovery |
| Analysis | M5.1, M5.4 | deterministic matched comparisons + traceable ClaimBundle + evidence review |
| Model credibility | M4.3–M4.5 | analytic checks, operating ranges, runtime screening, repeatability, upstream trajectories |
| Reproducibility | X.2 | run manifests, artifact hashes, portable ZIP export, restart recovery |
| Report workspace | M6.1 | structured sections, evidence IDs, conflicts, revisions, validation, MD/DOCX/PDF export |

*M4.2 drives `omc` via reproducible `.mos` scripts and compiled executables. The
runner backend remains selectable with `RCP_OM_BACKEND`.

## Simulation backend

The Buildings benchmark uses the pinned Docker image:

```bash
sudo usermod -aG docker $USER   # then log out/in
rcp benchmark-setup
rcp doctor
```

The image verifies exact Git commits for Modelica Standard Library 4.1.0 and
Buildings 13.0.0 while building. `OPENMODELICALIBRARY` points only at the bundled
libraries. The self-contained `DataCenterRoom` model may also run under a local
`omc` installation.

`DataCenterRoom` is deliberately classified as **conceptual**, even though its
offline energy-balance, analytic-equilibrium, saturation, low-load,
repeatability, unit, and sensitivity checks pass. It has not been calibrated to
a physical facility. Results and generated claims therefore retain a persistent
exploratory-evidence disclosure. The Buildings wrappers are classified
`library-validated`; they also remain explicitly uncalibrated.

## Architecture

```
cli.py                          workflow, diagnostics, simulation, benchmark CLI
graph/   state.py               global workflow state (pydantic)
         nodes.py               all workflow nodes incl. human gates
         build.py               StateGraph assembly + SqliteSaver checkpointing
memory/  pipeline.py            query plan → fetch → dedup → extract → themes → snapshot
simulation/ registry.py         model registry + constraints + credibility metadata
            batch.py            pre-registered cases, resume, comparison engine
            runner.py           omc execution + compiled-template reuse
            collector.py        CSV → metrics + numerical screening
            reference.py        pinned Dymola trajectory comparison
evidence.py                     deterministic claim/evidence review
provenance.py                   manifests, hashes, reproducibility ZIPs
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
rcp serve                                   # serves the UI at http://127.0.0.1:8000
```

`rcp serve` refuses to start unless `RCP_AUTH_PASSWORD` is set, so a deployment cannot
end up unauthenticated by accident. Bare `uvicorn rcp.api.main:app` still works and
stays unauthenticated while that variable is empty — fine on loopback, never otherwise.
To reach it from another machine, see **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**.

Screens: Dashboard (live run list), New Run (profile → five ranked ideas →
editable configuration → confirmation, with direct entry retained), Run Detail (workflow stepper with
live SSE updates, structured hypothesis/plan/recovery gates, tabs for Papers /
Research Intelligence with gaps, conflicts, and ranked hypotheses / case matrix / matched Results / section-based Report /
traceable Claims, deterministic outcome summary, comparative heatmaps/trade-off
plots, and supervisor review), a sortable and credibility-filtered
Knowledge Base, and Models with validation details and quick simulation.

Completed cycles are immutable. A supervisor may accept the evidence package or
create a linked, human-gated successor that reanalyses verified raw data, revises
the experiment plan, or refines the hypothesis. Protocol-only reanalysis copies
and verifies every raw CSV, preserves the raw-dataset identity, and is forbidden
from invoking Modelica.

Key endpoints: `POST /api/thesis-ideas`, `POST /api/runs`,
`GET /api/runs/{id}` (+ `/events` SSE, `/results`, `/series?case_id=...`,
`/results/revisions`, `/manifest`, `/artifacts/export`),
`POST /api/runs/{id}/gate`, `POST /api/runs/{id}/review`,
`GET /api/runs/{id}/lineage`, `GET /api/runs/{id}/synthesis`, and structured report endpoints below
`/api/runs/{id}/report` (document, sections, reorder, revisions, validation,
and `export?format=md|docx|pdf`), `GET /api/memory[/{slug}]`,
`GET /api/models`, `GET /api/models/{name}/validation`, and
`POST /api/simulations` with integrity-checked
`GET /api/simulations/{spec_id}/series`. The original plain-text report endpoint and
`data/runs/{id}/report.md` remain available.

## Tests

```bash
.venv/bin/pytest        # backend/unit/API tests (LLM, providers, and simulation mocked)
cd webapp && npm test   # React component tests
cd webapp && npm run test:e2e  # Chrome accessibility/responsive tests
cd webapp && npm run build
```

Regular CI runs the Python and React suites. A scheduled/manual workflow builds
the pinned image, runs repeatability and upstream-reference validation, and
uploads the resulting artifacts.
