"""KTPO reward, GRPO advantages, improvement rate, and eviction schedule (paper Sec. 3.2-3.3).

    r_j = +1 if s*_j > s(p_i);  0 if valid but s*_j ≤ s(p_i);  −0.5 if invalid        (1)
    Â_j = (r_j − r̄) / σ_r                    within each group of N children
    β_i = 1/N Σ_j 1[s*_j > s(p_i)]                                                     (2)
    τ_t = τ_0 + (τ_T − τ_0)·t/T              mastery threshold, linear decay (Alg. 1 line 4)
    s̄   = mean(R[last W])                    eviction threshold over mastered-parent scores
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

INVALID_PENALTY = -0.5


def reward(best_child_score: float, parent_score: float, valid: bool) -> float:
    """Equation (1). ``best_child_score`` is s*_j = max over the k revision steps."""
    if not valid:
        return INVALID_PENALTY
    return 1.0 if best_child_score > parent_score else 0.0


def grpo_advantages(rewards: list[float], eps: float = 1e-6) -> list[float]:
    """Group-relative advantages Â_j = (r_j − mean) / std over one parent's N children."""
    if len(rewards) < 2:
        return [0.0 for _ in rewards]
    mean = statistics.fmean(rewards)
    std = statistics.pstdev(rewards)
    return [(r - mean) / (std + eps) for r in rewards]


def improvement_rate(best_child_scores: list[float], parent_score: float) -> float:
    """Equation (2): fraction of children whose best-in-trajectory score beats the parent."""
    if not best_child_scores:
        return 0.0
    return sum(s > parent_score for s in best_child_scores) / len(best_child_scores)


def mastery_threshold(t: int, T: int, tau0: float = 0.3, tauT: float = 0.0) -> float:
    """Alg. 1 line 4: τ_t decays linearly from τ_0 to τ_T over the run."""
    return tau0 + (tauT - tau0) * t / T


@dataclass
class EvictionTracker:
    """Rolling buffer R of mastered-parent scores and the resulting eviction threshold s̄."""

    window: int = 10
    mastered: list[float] = field(default_factory=list)

    def record_if_mastered(self, beta: float, parent_score: float, tau_t: float) -> bool:
        if beta >= tau_t:
            self.mastered.append(parent_score)
            return True
        return False

    @property
    def threshold(self) -> float | None:
        recent = self.mastered[-self.window:]
        return statistics.fmean(recent) if recent else None
