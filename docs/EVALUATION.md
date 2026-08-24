# Scientific evaluation protocol

This protocol distinguishes software correctness, numerical regression, and
scientific validity. Passing one category must not be presented as passing the
others.

## Automated acceptance gates

| Gate | Command | Acceptance criterion |
|---|---|---|
| Backend contracts | `pytest -q` | All object, provenance, evidence, API, report, and batch tests pass |
| Frontend behavior | `npm test -- --run` | All component tests pass |
| Browser accessibility | `npm run test:e2e` | Light/dark axe audits, keyboard focus, 200% zoom, and 390/768/1440 px layouts pass |
| Production bundle | `npm run build` | TypeScript and Vite build without errors |
| Environment | `rcp doctor` | Registry, lock, storage, backend, and pinned image are available |
| Conceptual model | `rcp model-validate --model DataCenterRoom` | All analytic physics/reference checks pass |
| Buildings benchmark | `rcp benchmark-validate` | Two default pairs are metric-repeatable (temperature ≤0.05 K; other metrics ≤0.1%) and both configurations remain within 0.5% normalized RMSE of the pinned Buildings Dymola reference trajectories |
| Study quality | `rcp benchmark-run --smoke` | The hashed analysis protocol matches the approved plan and every deterministic study-quality check is passed or explicitly warning-only |
| Raw-data integrity | `pytest -q tests/test_batch.py` | Each successful CSV matches its recorded SHA-256; tampering fails study quality without silently rerunning or recomputing |
| Research intelligence | `pytest -q tests/test_synthesis.py tests/test_hypotheses.py` | Title-only records cannot produce findings; conflict references validate; unsupported contradictions are demoted; hypothesis scores are deterministic and registry-grounded |
| Checkpoint compatibility | `pytest -q tests/test_checkpoints.py` | Every workflow type round-trips through the strict allowlist and restart states are classified without silently discarding errors |

The Buildings reference comparison covers every common time-varying variable
published in its two upstream reference files. It does not use the primary HVAC
energy metric because those upstream files do not publish that trajectory.

## Evaluation fixtures

Run these in order and retain each run directory or exported reproducibility
ZIP.

1. Deep benchmark: `rcp benchmark-run`. Review all 18 cases, nine matched pairs,
   physical-screen warnings, comparison directions, and manifest hashes.
2. Numerical smoke: `rcp benchmark-run --smoke`. Confirm both cases succeed and
   every primary metric yields a structured matched comparison. Confirm the
   study-quality report is valid, PUE is inside 1–3, cooling-mode hours balance
   to the horizon, screened HVAC samples remain below 1%, and IT energy is
   non-decreasing with declared room load at fixed model/setpoint. Confirm the
   raw-series integrity check passes and the analysis revision is archived.
3. Evidence smoke: run `pytest -q tests/test_batch.py`. This fixture proves an
   unsupported comparative claim is rejected and a claim with valid comparison,
   case, and paper IDs is accepted.
4. Memory smoke: run `pytest -q tests/test_memory_provenance.py tests/test_ranking.py`. Confirm
   missing abstracts produce insufficient-evidence markers and frozen snapshot
   paths can be reused without refetching literature.
5. Intelligence smoke: inspect a Run Detail Intelligence tab. Confirm evidence
   coverage is visible, contradictions and tensions are distinct, every chip
   opens a valid source object, and the same hypothesis ordering survives a
   service restart.

## Manual baseline comparison

Use the same topic and frozen memory snapshot for both conditions:

- Baseline: a reviewer receives only paper titles/abstracts and raw simulation
  CSV files.
- Platform: a reviewer receives the RCP report, claim table, experiment plan,
  validation report, and reproducibility ZIP.

Blindly score each output from 1 (poor) to 5 (excellent) on:

- claim-to-number traceability;
- claim-to-literature traceability;
- visibility of missing source evidence;
- experiment comparability and pre-registration;
- reproducibility from captured inputs and versions;
- calibration/validation disclosures;
- time required to locate and verify a challenged claim.

Record disagreements and verification time as raw observations. Do not combine
them into a single “scientific validity” score. At least two reviewers should
independently score the outputs before discussing differences.

`reviewer_id` is a self-declared string: the platform has no per-user accounts, so
it cannot verify who submitted a scorecard. Serving the app behind the shared HTTP
Basic password described in `docs/DEPLOYMENT.md` does **not** change this — one
credential is shared by everyone, so it identifies nobody. Independence and blinding
remain procedural commitments by the reviewers, not properties the system enforces.

## Interpretation limits

- `DataCenterRoom` is conceptual and supports exploratory findings only.
- The Buildings benchmark establishes regression agreement with a pinned
  library/reference pair, not empirical agreement with a facility.
- The 0–2 MW HVAC-power screen handles known OpenModelica event impulses using
  linear interpolation internally and the nearest valid value at a boundary. Its
  excluded-sample count and raw integral must accompany any reported energy or
  PUE result. The screen, threshold, method, and maximum accepted fraction are
  frozen inside the approved analysis protocol and hashed into the result set.
- Comparison tie tolerances and study acceptance rules are part of that same
  hash. A protocol revision triggers deterministic metric reanalysis from the
  preserved raw CSV and is disclosed in result warnings. The preceding result
  remains available under `sim/analysis_revisions/`.
- A changed execution specification receives a new content-addressed case
  directory. Existing CSVs are reused only when the case hash matches; every
  raw file is then checked against its recorded SHA-256 before analysis.
- A dirty-code manifest is reproducible only with the local uncommitted patch;
  archive that patch before external review.
- LLM token counts depend on provider metadata. Missing usage metadata is shown
  as absent rather than estimated.
