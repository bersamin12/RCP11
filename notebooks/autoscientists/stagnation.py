"""Stagnation detection (paper Sec. 3.2 / App. A.2-A.3, Alg. 4 line 1).

The reference implementation carries three independent detectors; all three are provided so
the notebook can show when each fires:

* ``no_keep_in_last(n=10)``       — orchestrator rule: no KEEP among the last 10 experiments;
* ``cycles_since_keep(...) >= 3`` — analyst rule: three heartbeat cycles without a KEEP;
* ``axis_concentration(...)``     — search-class diversity: the last ≥8 DISCARDs sit in ≤3 axes.
"""
from __future__ import annotations


def no_keep_in_last(experiments: list[dict], n: int = 10) -> bool:
    recent = experiments[-n:]
    return len(recent) >= n and not any(e["outcome"] == "KEEP" for e in recent)


def cycles_since_keep(experiments: list[dict], current_cycle: int) -> int:
    keeps = [e["cycle"] for e in experiments if e["outcome"] == "KEEP"]
    return current_cycle - (max(keeps) if keeps else 0)


def axis_concentration(experiments: list[dict], window: int = 8, max_axes: int = 3) -> bool:
    discards = [e for e in experiments if e["outcome"] in ("DISCARD", "NEAR-MISS")][-window:]
    return len(discards) >= window and len({e["axis"] for e in discards}) <= max_axes


def check_stagnation(experiments: list[dict], current_cycle: int, min_cycles: int = 3) -> list[str]:
    fired = []
    if no_keep_in_last(experiments, 10):
        fired.append("no KEEP in last 10 experiments")
    if experiments and cycles_since_keep(experiments, current_cycle) >= min_cycles:
        fired.append(f"{cycles_since_keep(experiments, current_cycle)} cycles since last KEEP")
    if axis_concentration(experiments):
        fired.append("last 8 DISCARDs concentrated in ≤3 axes")
    return fired


def hypothesis_falsified(team_experiments: list[dict], age_cycles: int, min_age: int = 3, min_refuted: int = 3) -> bool:
    """Team-level rule: old enough, zero supporting KEEPs, and ≥3 refuting DISCARDs."""
    keeps = sum(e["outcome"] == "KEEP" for e in team_experiments)
    refuted = sum(e["outcome"] in ("DISCARD", "NEAR-MISS") for e in team_experiments)
    return age_cycles >= min_age and keeps == 0 and refuted >= min_refuted
