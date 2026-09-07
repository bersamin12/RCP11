"""Plot helpers for the KTPO notebook: circle-packing layouts and the KTPO iteration cycle.

``packing_of`` re-runs a candidate program to recover (centers, radii) so the best packing found
by the search can be drawn (paper Fig. 4); ``cycle_diagram`` draws the three phases of Algorithm 1
(Refine → Train → Update pool) with the line numbers each phase covers.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from .evaluator import TIMEOUT_S, _oe, with_fixed_tail


def packing_of(src: str, timeout_s: int = TIMEOUT_S) -> tuple[np.ndarray, np.ndarray]:
    """Run a candidate program and return its (centers, radii) arrays."""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(with_fixed_tail(src))
        path = f.name
    try:
        centers, radii, _ = _oe.run_with_timeout(path, timeout_seconds=timeout_s)
        return np.asarray(centers, dtype=float), np.asarray(radii, dtype=float)
    finally:
        Path(path).unlink(missing_ok=True)


def plot_packing(centers: np.ndarray, radii: np.ndarray, ax=None, title: str | None = None):
    """Draw a circle packing in the unit square (paper Fig. 4 style)."""
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle

    if ax is None:
        _, ax = plt.subplots(figsize=(4.2, 4.2))
    cmap = plt.get_cmap("viridis")
    lo, hi = float(radii.min()), float(radii.max())
    for (x, y), r in zip(centers, radii):
        shade = 0.25 + 0.6 * (r - lo) / (hi - lo + 1e-12)
        ax.add_patch(Circle((x, y), r, facecolor=cmap(shade), edgecolor="black", lw=0.6, alpha=0.85))
    ax.add_patch(plt.Rectangle((0, 0), 1, 1, fill=False, lw=1.2, color="black"))
    ax.set(xlim=(-0.02, 1.02), ylim=(-0.02, 1.02), xticks=[], yticks=[])
    ax.set_aspect("equal")
    ax.set_title(title or f"n={len(radii)}, Σr = {radii.sum():.4f}", fontsize=9)
    return ax


def cycle_diagram(ax=None):
    """Compact diagram of one KTPO iteration: Refine → Train → Update pool (Alg. 1 lines 5-24)."""
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

    if ax is None:
        _, ax = plt.subplots(figsize=(10.5, 3.6))
    boxes = [
        (0.03, "Pool $\\mathcal{P}$", "line 1, 7\n`pool.ProgramPool`\nsample $p_i\\sim$Uniform($\\mathcal{P}$)\nB parents", "#dbe7f3"),
        (0.28, "1 · Refine", "lines 8-12\n`refine.multistep_refine`\nN children × k steps\n$s^*_{i,j}=\\max_\\ell s(c^{(\\ell)}_{i,j})$", "#d8ecd8"),
        (0.53, "2 · Train", "line 15\n`grpo_train.KTPOReward`\n$r\\in\\{+1,0,-\\frac{1}{2}\\}$, GRPO\n$\\hat A_j=(r_j-\\bar r)/\\sigma_r$", "#fbe6cc"),
        (0.78, "3 · Update pool", "lines 17-24\n`reward.EvictionTracker`\n$\\beta_i\\geq\\tau_t\\Rightarrow$ record\n$\\bar s$ = mean $\\mathcal{R}$[last W]", "#f3dbe2"),
    ]
    for x, title, body, color in boxes:
        ax.add_patch(FancyBboxPatch((x, 0.28), 0.19, 0.5, boxstyle="round,pad=0.012",
                                    facecolor=color, edgecolor="#44506b", lw=1.1))
        ax.text(x + 0.095, 0.71, title, ha="center", va="center", fontsize=10, weight="bold")
        ax.text(x + 0.095, 0.48, body, ha="center", va="center", fontsize=7.4)
    for x in (0.22, 0.47, 0.72):
        ax.add_patch(FancyArrowPatch((x, 0.53), (x + 0.06, 0.53), arrowstyle="-|>", mutation_scale=14, color="#44506b"))
    ax.add_patch(FancyArrowPatch((0.875, 0.27), (0.125, 0.27), arrowstyle="-|>", mutation_scale=14,
                                 color="#44506b", connectionstyle="arc3,rad=-0.18", linestyle="--"))
    ax.text(0.5, 0.06, "line 11: add valid children  ·  line 24: $\\mathcal{P}\\leftarrow\\{p:s(p)\\geq\\bar s\\}$  →  next iteration $t{+}1$",
            ha="center", fontsize=8, color="#44506b",
            bbox=dict(facecolor="white", edgecolor="none", pad=1.5))
    ax.text(0.5, 0.9, "One KTPO iteration (Algorithm 1, lines 3-25)", ha="center", fontsize=10.5, weight="bold")
    ax.set(xlim=(0, 1), ylim=(0, 1)); ax.axis("off")
    return ax
