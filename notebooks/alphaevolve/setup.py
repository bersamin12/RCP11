"""Wire the vendored OpenEvolve onto OpenRouter (paths, config, usage log)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

NB_DIR = Path(__file__).resolve().parents[1]
OE_DIR = NB_DIR / "vendor" / "openevolve"
CP_DIR = OE_DIR / "examples" / "circle_packing"
INITIAL_PROGRAM = CP_DIR / "initial_program.py"
#: quiet, short-timeout wrapper around the example's evaluator (see cp_eval.py)
EVAL_FILE = Path(__file__).resolve().parent / "cp_eval.py"


def add_to_path() -> None:
    """Import the vendored package without installing it."""
    if str(OE_DIR) not in sys.path:
        sys.path.insert(0, str(OE_DIR))


def openevolve_env(usage_log: str | Path) -> None:
    """Switch on the two behaviours added by patches/openevolve_openrouter.patch.

    They are environment-driven because evolution runs in worker *processes*:
    ``_worker_init`` copies the parent environment, so both flags survive the fork.
    """
    os.environ["OPENEVOLVE_OPENROUTER"] = "1"
    os.environ["OPENEVOLVE_USAGE_LOG"] = str(usage_log)
    Path(usage_log).parent.mkdir(parents=True, exist_ok=True)


def usage_from_log(path: str | Path, *, reset: bool = True) -> dict[str, Any]:
    """Read (and by default truncate) the cross-process usage log."""
    p = Path(path)
    if not p.exists():
        return {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0}
    rows = [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
    if reset:
        p.write_text("")
    return {
        "calls": len(rows),
        "prompt_tokens": sum(r["prompt_tokens"] for r in rows),
        "completion_tokens": sum(r["completion_tokens"] for r in rows),
        "cost": sum(r["cost"] for r in rows),
    }


SYSTEM_MESSAGE = """You are an expert mathematician specializing in circle packing problems and \
computational geometry. Your task is to improve a constructor function that directly produces a \
specific arrangement of 26 circles in a unit square, maximizing the sum of their radii. The \
AlphaEvolve paper achieved a sum of 2.635 for n=26.

Key geometric insights:
- Circle packings often follow hexagonal patterns in the densest regions
- Maximum density for infinite circle packing is pi/(2*sqrt(3)) ~= 0.9069
- Edge effects make square container packing harder than infinite packing
- Circles can be placed in layers or shells when confined to a square
- Similar radius circles often form regular patterns, while varied radii allow better space use

Keep the `construct_packing()` signature and return `(centers, radii, sum_radii)` with shapes \
(26, 2) and (26,). Only the code between the EVOLVE-BLOCK markers may change."""

#: paper Sec. 2.2 "stochastic formatting": placeholders with human-provided alternatives,
#: instantiated from a distribution given in the config file (PromptConfig.template_variations).
TEMPLATE_VARIATIONS = {
    "improve_instruction": [
        "Suggest improvements to the program",
        "Propose a targeted modification of the program",
        "Think like an expert geometer and refine the program",
    ],
}


def make_config(
    *,
    model: str,
    api_base: str,
    api_key: str,
    max_iterations: int,
    num_islands: int = 2,
    diff_based_evolution: bool = True,
    num_top_programs: int = 2,
    num_diverse_programs: int = 1,
    population_size: int = 30,
    parallel_evaluations: int = 4,
    max_tokens: int = 8192,
    template_variations: dict | None = None,
    template_dir: str | None = None,
    include_artifacts: bool = True,
    random_seed: int = 42,
    log_dir: str | None = None,
):
    """Build an OpenEvolve ``Config`` for the circle-packing task on OpenRouter.

    Every field below is a real OpenEvolve config field; nothing is re-implemented.
    """
    add_to_path()
    from openevolve.config import Config

    return Config.from_dict(
        {
            "max_iterations": max_iterations,
            "checkpoint_interval": 10_000,  # no checkpoints for these tiny runs
            "log_level": "WARNING",
            "log_dir": log_dir,
            "random_seed": random_seed,
            "diff_based_evolution": diff_based_evolution,
            "max_code_length": 20_000,
            "llm": {
                "primary_model": model,
                "primary_model_weight": 1.0,
                "api_base": api_base,
                "api_key": api_key,
                "temperature": 0.8,
                "max_tokens": max_tokens,
                "timeout": 120,   # per attempt; OpenRouter occasionally stalls a request
                "retries": 2,
                "retry_delay": 5,
            },
            "prompt": {
                "system_message": SYSTEM_MESSAGE,
                "template_dir": template_dir,
                "num_top_programs": num_top_programs,
                "num_diverse_programs": num_diverse_programs,
                "use_template_stochasticity": template_variations is not None,
                "template_variations": template_variations or {},
                "include_artifacts": include_artifacts,
            },
            "database": {
                "population_size": population_size,
                "archive_size": 12,
                "num_islands": num_islands,
                "feature_dimensions": ["complexity", "score"],
                "feature_bins": 6,
                "migration_interval": 3,
                "migration_rate": 0.2,
                "random_seed": random_seed,
                "log_prompts": True,
            },
            "evaluator": {
                "timeout": 90,
                "max_retries": 1,
                "cascade_evaluation": True,
                "cascade_thresholds": [0.3],
                "parallel_evaluations": parallel_evaluations,
                "use_llm_feedback": False,
            },
        }
    )


def record_usage(path: str | Path, tag: str, seconds: float = 0.0) -> dict[str, Any]:
    """Fold the worker-process usage log into ``common.USAGE`` under ``tag``."""
    from types import SimpleNamespace

    import common

    u = usage_from_log(path, reset=True)
    for i in range(u["calls"]):
        common.USAGE.add(
            SimpleNamespace(
                prompt_tokens=u["prompt_tokens"] if i == 0 else 0,
                completion_tokens=u["completion_tokens"] if i == 0 else 0,
                cost=u["cost"] if i == 0 else 0.0,
            ),
            seconds if i == 0 else 0.0,
            tag,
        )
    return u


def quiet_logging() -> None:
    """Drop the console/file handlers OpenEvolve's controller installs on the root logger.

    ``OpenEvolve._setup_logging`` adds a new pair of handlers on every construction, so
    without this a notebook that builds several controllers prints each line N times.
    """
    import logging

    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openevolve").setLevel(logging.WARNING)


def history(db) -> list[dict[str, Any]]:
    """Per-program evolution history: iteration, island, score, MAP-Elites cell."""
    rows = []
    for p in db.programs.values():
        island = p.metadata.get("island", 0)
        rows.append(
            {
                "iteration": p.iteration_found,
                "id": p.id[:8],
                "parent": (p.parent_id or "-")[:8],
                "island": island,
                "generation": p.generation,
                "combined_score": float(p.metrics.get("combined_score", 0.0)),
                "sum_radii": float(p.metrics.get("sum_radii", 0.0)),
                "cell": "-".join(str(c) for c in db._calculate_feature_coords(p)),
                "changes": (p.metadata.get("changes", "") or "")[:60].replace("\n", " "),
            }
        )
    return sorted(rows, key=lambda r: r["iteration"])


def best_curve(rows: list[dict[str, Any]]) -> tuple[list[int], list[float]]:
    """Best combined_score so far vs iteration."""
    xs, ys, best = [], [], float("-inf")
    for r in rows:
        best = max(best, r["combined_score"])
        xs.append(r["iteration"])
        ys.append(best)
    return xs, ys


def grid_matrix(db, island: int = 0):
    """Occupancy / best-score matrix of one island's MAP-Elites grid."""
    import numpy as np

    bins = db.feature_bins
    mat = np.full((bins, bins), np.nan)
    for key, pid in db.island_feature_maps[island].items():
        i, j = (int(c) for c in key.split("-"))
        prog = db.programs.get(pid)
        if prog is not None:
            mat[j, i] = float(prog.metrics.get("combined_score", 0.0))
    return mat
