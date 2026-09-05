# Paper test notebooks

One Jupyter notebook per paper in [`../papers/`](../papers). Each notebook exercises the paper's
building blocks **one section at a time** (so a single mechanism can be run and inspected on its
own) and ends with a small end-to-end run. All LLM calls are real and go through the project's
OpenRouter configuration in the repo-root `.env` (`OPENROUTER_API_KEY`, `RCP_MODEL`, `RCP_BASE_URL`).

| Notebook | Paper | How the code is sourced |
|---|---|---|
| `01_autoscientists.ipynb` | AutoScientists: Self-Organizing Agent Teams for Long-Running Scientific Experimentation (arXiv 2605.28655) | **Standalone re-implementation** in `autoscientists/`. The authors' repo is a Claude Code prompt bundle (markdown roles + a bootstrap script) with no LLM abstraction, no tests, no toy task and no license; its algorithms are pseudocode inside markdown, used here as the spec. |
| `02_ideagent.ipynb` | IDEAgent: Agentic Quality-Diversity Search for Research Idea Generation (arXiv 2607.22375) | **Drives the authors' repo** (`declare-lab/IDEAgent` @ `1213761`), vendored into `vendor/IDEAgent` by the setup cell and patched with `patches/ideagent_openrouter.patch` (fixes a crashing kwarg in the runner, adds `base_url` so every role can use OpenRouter, controls hidden reasoning). Yield (Alg. 2) and topic selection (Alg. 1) are not in the repo and live in `ideagent_extras.py`. |
| `03_ktpo.ipynb` | KTPO: K-Step Test-Time Policy Optimization for Long-Horizon Discovery (COLM 2026) | **Standalone re-implementation** in `ktpo/` (the authors' GitHub repo was an empty placeholder when this was written). The Circle Packing seed program and validity checker are OpenEvolve's example (Apache-2.0, `vendor/openevolve_circle_packing/`). Includes a tiny real GRPO run with TRL on the local GPU. |

## Setup

```bash
# from the repo root, inside the project's virtualenv
uv pip install -r notebooks/requirements.txt          # jupyter, sklearn, torch (CUDA), transformers, trl, peft, IDEAgent deps
python -m ipykernel install --user --name rcp --display-name "Python (rcp)"
cp .env.example .env && $EDITOR .env                   # OPENROUTER_API_KEY, optional RCP_MODEL
cd notebooks && jupyter lab                            # open a notebook, kernel "Python (rcp)"
```

Run the notebooks from the `notebooks/` directory (they `sys.path`-insert `.`). Headless:

```bash
cd notebooks
NB_QUICK=1 jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=3600 01_autoscientists.ipynb
```

Environment switches (all optional):

| Variable | Effect |
|---|---|
| `NB_QUICK=1` | smaller budgets everywhere (fewer cycles / seeds / iterations / GRPO steps) |
| `NB_REASONING` | `off` (default), `low`, `medium`, `high` — hidden reasoning effort for reasoning models via OpenRouter; reasoning tokens count against the completion budget, so `off` is safest for code generation |
| `NB_ABLATIONS=1` | also run the ablation variants in 01 §10b and 03 §6b |
| `GRPO_FROM_POOL=1` | 03 §7 samples GRPO parents from the §6 search pool instead of the seed program |

## Layout

```
notebooks/
  common.py              .env loading, OpenRouter chat + JSON helpers, usage/cost tracker, vendoring + patching
  ideagent_extras.py     Yield (Alg. 2), successful topics, CST, greedy max–min topics (Alg. 1), evaluator wrappers
  autoscientists/        state.py queue.py gate.py priors.py stagnation.py roster.py agents.py heartbeat.py task/train.py
  ktpo/                  evaluator.py pool.py reward.py refine.py search.py grpo_train.py
  patches/               ideagent_openrouter.patch
  vendor/                (gitignored) IDEAgent clone, OpenEvolve circle-packing files — re-created by the notebooks
  outputs/               (gitignored) run artifacts: shared-state directories, pools, GRPO metrics, LoRA adapter
```

## Cost and time (observed, `deepseek/deepseek-v4-flash`)

Measured on the executed notebooks committed here (single run each, 2026-09-05); the last cell of each notebook prints the exact numbers for that run.

| Notebook | Mode | LLM calls | Cost | Wall clock | Notes |
|---|---|---|---|---|---|
| 01 AutoScientists | full (6 cycles, 2 analysts + 3 experiment agents) | 50 | $0.016 | ≈12 min | CPU only; each experiment trains an sklearn MLP in ~0.2 s; 18 experiments, 2 KEEPs |
| 02 IDEAgent | full (B=3 seeds, C_A=3, K_aux=1, M=5) | 130 | $0.040 | ≈20 min | mostly evaluator calls (82 quality/soundness, 17 judge); the end-to-end run alone is 55 calls |
| 03 KTPO | full (T=5, B=2, N=2, k=3 search + 20 GRPO steps) | 64 | $0.038 | ≈43 min | search ≈17 min (best packing 2.54 from a 0.96 seed); GRPO ≈23 min on the RTX A4500 (20 steps × 8 completions × ≤1536 tokens, ~9 GB peak); valid-rate stays noisy at this budget |

## Caveats

* **Model.** The papers used frontier models (Claude Sonnet 4.6 as a coding agent; gpt-5.6 / gemini-3.x;
  Qwen3-4B/9B trained on 8×H100). The notebooks use one cheap OpenRouter model for every role, so
  absolute numbers differ from the papers; the mechanisms, not the scores, are what is being tested.
* **AutoScientists** has no LICENSE file; the notebook adapts its role prompts and pseudocode as a
  specification and cites it, but does not vendor the repository.
* **KTPO** code is unpublished; `ktpo/` follows Algorithm 1 and Appendix D of the paper. The GRPO run is
  a 1.5B LoRA model on one GPU — it demonstrates the pipeline and the shape of the curves, not the results.
  A short engineering hint is appended to the paper's prompt for the small model (`--no-hint` removes it),
  and the evaluator re-attaches the benchmark's fixed `run_packing()` entry point when a rewrite drops it.
* **IDEAgent's** shipped runner crashes on a stray constructor argument and has no OpenRouter/base_url
  support; the patch is ~100 lines and is re-applied idempotently by the notebook's setup cell.
* Every notebook keeps its executed outputs, so the results can be read without re-running.
