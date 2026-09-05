"""Noise-aware champion validation (paper App. A.6, equations 1-2).

    promote(p') = true                 if Δ > Mσ
                  confirm(p', seed2)   if 0 < Δ ≤ Mσ
                  false                if Δ ≤ 0                              (1)

    σ = sqrt( 1/(2n) Σ_i (ℓ_{1,i} − ℓ_{2,i})² )   over duplicate-seed pairs   (2)

σ is calibrated lazily: every time the middle branch fires, the pair of same-code
measurements is recorded; σ is estimated once n ≥ 3 pairs exist and locked at 5 pairs so
later pairs cannot retroactively reclassify earlier decisions. Until then a conservative
default band is used.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

M_DEFAULT = 2.0


def pooled_sigma(pairs: list[tuple[float, float]]) -> float:
    """Equation (2): within-pair pooled standard deviation of the metric at fixed code."""
    if not pairs:
        raise ValueError("need at least one pair")
    return math.sqrt(sum((a - b) ** 2 for a, b in pairs) / (2 * len(pairs)))


@dataclass
class NoiseFloor:
    default_sigma: float           # conservative band used before calibration
    min_pairs: int = 3             # σ estimated once n ≥ 3
    lock_at: int = 5               # σ locked once 5 pairs recorded
    pairs: list = None
    locked_sigma: float | None = None

    def __post_init__(self):
        self.pairs = list(self.pairs or [])

    @property
    def sigma(self) -> float:
        if self.locked_sigma is not None:
            return self.locked_sigma
        if len(self.pairs) >= self.min_pairs:
            return pooled_sigma(self.pairs)
        return self.default_sigma

    @property
    def status(self) -> str:
        if self.locked_sigma is not None:
            return f"locked (n={len(self.pairs)})"
        if len(self.pairs) >= self.min_pairs:
            return f"estimated (n={len(self.pairs)})"
        return f"default (n={len(self.pairs)} < {self.min_pairs})"

    def add_pair(self, l1: float, l2: float) -> None:
        self.pairs.append((l1, l2))
        if self.locked_sigma is None and len(self.pairs) >= self.lock_at:
            self.locked_sigma = pooled_sigma(self.pairs)


@dataclass
class GateDecision:
    promote: bool
    branch: str                    # "clear" | "confirm" | "reject"
    delta: float
    band: float                    # M·σ
    second_metric: float | None = None
    detail: str = ""


def promote(
    candidate_metric: float,
    champion_metric: float,
    noise: NoiseFloor,
    confirm: Callable[[], float] | None = None,
    M: float = M_DEFAULT,
) -> GateDecision:
    """Equation (1). ``confirm`` re-runs the candidate on a fresh seed and returns its metric.

    The middle branch records the duplicate-seed pair into ``noise`` (lazy calibration) and
    promotes only if BOTH runs strictly beat the champion.
    """
    delta = candidate_metric - champion_metric
    band = M * noise.sigma
    if delta > band:
        return GateDecision(True, "clear", delta, band, detail=f"Δ={delta:+.4f} > Mσ={band:.4f}")
    if delta <= 0:
        return GateDecision(False, "reject", delta, band, detail=f"Δ={delta:+.4f} ≤ 0")
    if confirm is None:
        return GateDecision(False, "confirm", delta, band, detail="inside noise band; no confirm() supplied")
    second = confirm()
    noise.add_pair(candidate_metric, second)
    ok = second > champion_metric  # first run already > champion (delta > 0)
    return GateDecision(
        ok, "confirm", delta, band, second_metric=second,
        detail=(f"Δ={delta:+.4f} inside band {band:.4f}; second seed {second:.4f} "
                f"{'>' if ok else '≤'} champion {champion_metric:.4f} → {'promote' if ok else 'near-miss'}"),
    )
