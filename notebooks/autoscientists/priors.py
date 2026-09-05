"""Analyst analytics (paper App. A.7): baseline coverage audit and empirical axis priors.

    μ_{a,d} = 1/|E_{a,d}| Σ_{e ∈ E_{a,d}} |Δ_e|                                  (3)

Directions with |E_{a,d}| < 3 are *cold* and receive an exploration bonus; directions whose
mean effect size falls below the noise floor (μ < σ) are deprioritised; the team queue is
sorted by the resulting ranking.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass

COLD_THRESHOLD = 3


def numeric_parameters(source: str) -> dict[str, float]:
    """Top-level ALL_CAPS numeric constants of a training script (the audit surface)."""
    params: dict[str, float] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name.isupper() and isinstance(node.value, ast.Constant) and isinstance(node.value.value, (int, float)):
                params[name] = node.value.value
    return params


def coverage_audit(source: str, experiments: list[dict]) -> dict[str, int]:
    """How many logged experiments varied each parameter; 0 = never tested (A.7 'coverage audit')."""
    counts = {p: 0 for p in numeric_parameters(source)}
    for e in experiments:
        if e["axis"] in counts:
            counts[e["axis"]] += 1
    return counts


@dataclass
class AxisPrior:
    axis: str
    direction: str
    n: int
    mu: float | None          # mean |Δ|; None when cold with no data
    status: str               # "cold" | "hot" | "below_noise"
    keeps: int


def axis_priors(experiments: list[dict], sigma: float, axes: list[str] | None = None) -> list[AxisPrior]:
    """Equation (3) per (axis, direction), with cold / below-noise classification."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for e in experiments:
        if e["outcome"] == "INVALID":
            continue
        groups[(e["axis"], e["direction"])].append(e)
    keys = set(groups)
    for a in axes or []:
        keys |= {(a, "up"), (a, "down")}
    out = []
    for axis, direction in sorted(keys):
        es = groups.get((axis, direction), [])
        n = len(es)
        mu = sum(abs(e["delta"]) for e in es) / n if n else None
        if n < COLD_THRESHOLD:
            status = "cold"
        elif mu < sigma:
            status = "below_noise"
        else:
            status = "hot"
        out.append(AxisPrior(axis, direction, n, mu, status, sum(e["outcome"] == "KEEP" for e in es)))
    return rank_priors(out)


def rank_priors(priors: list[AxisPrior]) -> list[AxisPrior]:
    """Hot directions by descending μ, then cold (exploration bonus), then below-noise last."""
    order = {"hot": 0, "cold": 1, "below_noise": 2}
    return sorted(priors, key=lambda p: (order[p.status], -(p.mu or 0.0), p.axis, p.direction))


def rank_queue(pending: list[dict], priors: list[AxisPrior]) -> list[dict]:
    """Sort queue items by their (axis, direction) prior rank; unknown pairs are treated as cold."""
    rank = {(p.axis, p.direction): i for i, p in enumerate(priors)}
    cold_rank = min([i for i, p in enumerate(priors) if p.status == "cold"], default=len(priors))
    return sorted(pending, key=lambda it: (rank.get((it["axis"], it["direction"]), cold_rank), it.get("priority", 0)))
