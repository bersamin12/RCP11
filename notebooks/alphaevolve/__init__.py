"""Helpers for notebook 09 (AlphaEvolve / OpenEvolve).

Nothing here re-implements an AlphaEvolve component: the module only wires the
vendored OpenEvolve package onto OpenRouter, keeps the noisy example evaluator
quiet inside a notebook, collects cross-process usage/cost bookkeeping, and
unrolls one controller iteration for the paper's "No evolution" ablation.
"""
from alphaevolve.setup import (  # noqa: F401
    CP_DIR,
    EVAL_FILE,
    INITIAL_PROGRAM,
    OE_DIR,
    SYSTEM_MESSAGE,
    TEMPLATE_VARIATIONS,
    add_to_path,
    best_curve,
    grid_matrix,
    history,
    make_config,
    openevolve_env,
    quiet_logging,
    record_usage,
    usage_from_log,
)

TEMPLATE_DIR = str(__import__("pathlib").Path(__file__).resolve().parent / "templates")
