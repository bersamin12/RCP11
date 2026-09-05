"""Program pool P (paper Sec. 3, Alg. 1 lines 1, 7, 11, 24).

* initialised with the seed program p0;
* parents are sampled uniformly from P;
* every intermediate program with positive score is added (line 11);
* ``evict(threshold)`` removes all programs with s(p) < s̄ (line 24).
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field


@dataclass
class Program:
    src: str
    score: float
    parent: str | None = None
    iteration: int = 0
    origin: str = "seed"        # seed | child | grpo

    @property
    def pid(self) -> str:
        return hashlib.sha1(self.src.encode()).hexdigest()[:8]


@dataclass
class ProgramPool:
    programs: dict[str, Program] = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)   # (iteration, size, best, evicted)

    @classmethod
    def from_seed(cls, src: str, score: float) -> "ProgramPool":
        pool = cls()
        pool.add(Program(src, score))
        return pool

    def add(self, prog: Program) -> bool:
        """Add a program if it is valid (score > 0) and new. Returns True if added."""
        if prog.score <= 0 or prog.pid in self.programs:
            return False
        self.programs[prog.pid] = prog
        return True

    def sample(self, rng: random.Random, k: int = 1) -> list[Program]:
        """Uniform sampling of parents (Alg. 1 line 7)."""
        return [rng.choice(list(self.programs.values())) for _ in range(k)]

    def evict(self, threshold: float, keep_best: bool = True) -> list[Program]:
        """P ← {p ∈ P : s(p) ≥ s̄}. The best program is always retained so P never empties."""
        best = self.best
        evicted = [p for p in self.programs.values() if p.score < threshold and not (keep_best and p is best)]
        for p in evicted:
            del self.programs[p.pid]
        return evicted

    @property
    def best(self) -> Program:
        return max(self.programs.values(), key=lambda p: p.score)

    @property
    def scores(self) -> list[float]:
        return sorted((p.score for p in self.programs.values()), reverse=True)

    def __len__(self) -> int:
        return len(self.programs)

    def record(self, iteration: int, evicted: int, threshold: float | None) -> None:
        self.history.append({"iteration": iteration, "size": len(self), "best": self.best.score,
                             "mean": sum(self.scores) / len(self), "evicted": evicted, "threshold": threshold})
