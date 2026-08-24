# Implementation Task List — RCP2026/11

Status key: `[ ]` open · `[~]` partial · `[x]` done.
Priority: **P0** (must for MVP/PRD correctness) · **P1** (roadmap Phases 3–6) · **P2** (nice-to-have).

---

## P0 — Completeness gaps (PRD marks these mandatory)

### Simulation (Role 2)
- [x] **M4.2 — OMPython runner.** Replace the `.mos`-script MVP with the `OMCSessionZMQ` interactive backend (load model, set params, run, read results). Keep `RCP_OM_BACKEND` pluggable so the `.mos`/Docker path remains a fallback.
- [x] **Initial model library.** Add Buildings-library `ChillerCooled` + `DXCooled` to `models_library/` and `registry.json` (PRD §6 requires them; only `DataCenterRoom` ships today). Extend the `.mos`/OMPython template with `installPackage(Buildings)`.
  - ⚠ Caveat: registered as `NonIntegratedPlant` / `IntegratedPlant` / `DXCooledAirside` and they compile, but full runtime is blocked by unresolved `modelica://` weather-file URIs (see README).

### Analysis (Role 3)
- [x] **M5.2 — Comparator.** Baseline-vs-candidate side-by-side comparison (metric deltas, per-operating-point table). Blocks the Reproduce/Improve task archetypes.
- [x] **M6.3 — Consistency check.** Real automated check: do report conclusions match the `ClaimBundle` evidence? (Today it's only a prompt instruction.)

### Orchestration / Cross-cutting (Role 4)
- [x] **§5.4 — Rollback decisions.** Human gate on the failure handler: when a run fails, surface a rollback/re-plan decision instead of just marking it failed.
- [ ] **X.1 — True closed loop.** Add the analysis→idea-refinement edge so results/feedback flow back to gap mining / hypothesis generation (today only spec-revision loops).
- [x] **X.3 — Hash-based traceability.** Record SHA-256 fingerprints of raw results, seal the approved spec/protocol, and link each claim to case/comparison/paper IDs (the report currently cites metrics only in prose).

---

## P1 — Roadmap Phases 3–6 (deepening)

### Knowledge & Idea (Role 1)
- [ ] **M2.2 — Contradiction Detector.** Flag conflicting conclusions / unexplained differences across papers.
- [ ] **M2.4 — Priority Ranker.** Rank hypotheses by novelty, feasibility, expected contribution.
- [ ] **M2.5 — Idea verify/improve loop.** idea → feasibility → refine → select.
- [~] **M1.5 — Theme Builder.** Add citation-based theme maps / topic trees (today: tag clustering only).

### Experiment Planning (Role 2)
- [ ] **M3.3 — Plan Expander.** Auto-generate baseline / ablation / parameter-sweep plans.
- [ ] **M3.4 — Experiment Registry.** Track all specs with version control and status.

### Execution (Role 2)
- [ ] **M4.3 — Batch Executor.** Expand one `ExperimentSpec` into multiple jobs (baseline / ablation / sweeps) and run them.

### Analysis & Writing (Role 3)
- [ ] **M5.3 — Trend & Anomaly Analyzer.** Pattern / outlier detection (builds on the known mover-power impulse issue).
- [ ] **M6.2 — Figure captions/numbering/variable definitions.** Auto-generate.
- [ ] **M6.4 — Internal review loop.** Checker + reviewer agents, review comments, terminology check.

---

## P2 — Nice-to-have

- [ ] **M4.6 — Co-sim Adapter.** Reserved interface for OMSimulator / FMI co-simulation.

---

## Cross-cutting (no single owner — pick up in order)

- [ ] **Frontend tests.** PRD/PI-review claims 60; the repo has **0**. Add vitest + a few screen tests.
- [ ] **Deployment security.** Basic auth, non-loopback lock, systemd unit, `docs/DEPLOYMENT.md` (the API has no auth today).
- [ ] **Evaluation doc.** `docs/EVALUATION.md` covering automated / numerical / manual-review tiers.
- [ ] **Success metrics (§8).** Run end-to-end topic→report on ≥1 (then ≥3) representative tasks; document usability + efficiency vs manual baseline.
- [ ] **Model calibration.** Acquire measured facility data to validate `DataCenterRoom` (and later Buildings models) against reality — currently only library-regression-tier.

---

## Suggested order

1. M4.2 + initial model library (unblocks real simulation work)
2. X.3 traceability + M6.3 consistency (unblocks §8 "100% claim traceability")
3. M5.2 comparator (unblocks Improve archetype)
4. X.1 closed loop + rollback gate
5. Then Phase 3–6 P1 items per role ownership.

*Owner mapping from PRD §10: Role 1 = Knowledge & Idea (M1, M2) · Role 2 = Experiment & Simulation (M3, M4) · Role 3 = Analysis & Writing (M5, M6) · Role 4 = Orchestration (X.1–X.5, Layer 4).*
