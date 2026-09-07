"""Shared/context memory, hypothesis records, the Elo table and the asynchronous task queue.

Everything in this file is pure Python (no LLM calls) so the deterministic parts of the paper's
machinery — the Elo update rule, the task queue, the weighted agent sampling — can be unit-tested
on hand-built inputs.

Paper: Gottweis et al., "Accelerating scientific discovery with Co-Scientist" (arXiv 2502.18864),
Methods ("Ranking agent", "Overview of Co-Scientist architecture") and Supplementary Note 8.
"""
from __future__ import annotations

import heapq
import itertools
import json
import math
import random
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

# Methods, Ranking agent: "We set the initial Elo rating of 1200 for the newly added hypothesis."
ELO_INITIAL = 1200.0
# The paper does not state K; 32 is the classical Elo value (Elo 2008, ref. 30) and is what we use.
ELO_K = 32.0


# --------------------------------------------------------------------------- research plan config
@dataclass
class ResearchPlan:
    """Supplementary Note 10.1: a research goal parsed into preferences / attributes / constraints."""

    goal: str
    preferences: list[str] = field(default_factory=list)
    attributes: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    idea_attributes: str = "novel and feasible"
    notes: str = ""

    @property
    def preferences_text(self) -> str:
        return "\n".join(f"- {p}" for p in self.preferences) or "- (none specified)"

    @property
    def constraints_text(self) -> str:
        return "\n".join(f"- {c}" for c in self.constraints) or "- (none specified)"

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- records
@dataclass
class Hypothesis:
    """One research hypothesis in the paper's structured output format (Supplementary Note 10.2)."""

    hid: str
    title: str
    category: str
    summary: str
    statement: str          # "Hypothesis"
    rationale: str          # "Rationale and specificity"
    experiment: str         # "Experimental design and validation"
    assumptions: list[str] = field(default_factory=list)
    strategy: str = ""      # which Generation/Evolution strategy produced it
    parents: list[str] = field(default_factory=list)
    round: int = 0
    articles: list[str] = field(default_factory=list)
    status: str = "new"     # new | reviewed | rejected | duplicate
    reject_reason: str = ""

    def render(self, width: int = 0) -> str:
        def cut(t: str) -> str:
            t = (t or "").strip()
            return t if not width or len(t) <= width else t[:width] + " …"

        return (
            f"### {self.hid} · {self.title}\n"
            f"*strategy:* `{self.strategy}` · *category:* {self.category} · *round:* {self.round}"
            + (f" · *parents:* {', '.join(self.parents)}" if self.parents else "")
            + f"\n\n**Summary.** {cut(self.summary)}\n\n"
            f"**Hypothesis.** {cut(self.statement)}\n\n"
            f"**Rationale and specificity.** {cut(self.rationale)}\n\n"
            f"**Experimental design and validation.** {cut(self.experiment)}\n"
            + ("\n**Assumptions.** " + "; ".join(self.assumptions) + "\n" if self.assumptions else "")
        )

    def compact(self) -> str:
        """The form shown to other agents inside prompts."""
        return (
            f"[{self.hid}] {self.title}\n"
            f"Hypothesis: {self.statement}\n"
            f"Rationale: {self.rationale}\n"
            f"Experiment: {self.experiment}"
        )


@dataclass
class Review:
    """One review produced by the Reflection agent (Methods, Reflection agent)."""

    hid: str
    kind: str               # initial | full | deep_verification | observation | simulation | tournament
    scores: dict[str, float] = field(default_factory=dict)
    decision: str = "accept"           # accept | reject
    critiques: list[str] = field(default_factory=list)
    text: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Match:
    """One tournament match run by the Ranking agent."""

    a: str
    b: str
    winner: str
    mode: str               # "single-turn" | "multi-turn-debate"
    rationale: str = ""
    turns: int = 1
    round: int = 0
    transcript: str = ""


# --------------------------------------------------------------------------- Elo
class EloTable:
    """Elo ratings with the classical logistic expectation and symmetric update.

        E_a = 1 / (1 + 10^((R_b - R_a)/400));   R_a' = R_a + K (S_a - E_a)

    Ratings start at 1200 (Methods, Ranking agent).
    """

    def __init__(self, k: float = ELO_K, initial: float = ELO_INITIAL):
        self.k = float(k)
        self.initial = float(initial)
        self.ratings: dict[str, float] = {}
        self.games: dict[str, int] = {}
        self.history: list[dict[str, Any]] = []

    def add(self, hid: str) -> bool:
        """AddToTournament (Supp. Note 8): no-op if the hypothesis already has a rating."""
        if hid in self.ratings:
            return False
        self.ratings[hid] = self.initial
        self.games[hid] = 0
        return True

    def rating(self, hid: str) -> float:
        return self.ratings.get(hid, self.initial)

    def expected(self, a: str, b: str) -> float:
        return 1.0 / (1.0 + 10.0 ** ((self.rating(b) - self.rating(a)) / 400.0))

    def update(self, winner: str, loser: str) -> tuple[float, float]:
        self.add(winner)
        self.add(loser)
        e_w = self.expected(winner, loser)
        delta = self.k * (1.0 - e_w)
        self.ratings[winner] += delta
        self.ratings[loser] -= delta
        self.games[winner] += 1
        self.games[loser] += 1
        return delta, -delta

    def top(self, n: int = 10, among: Iterable[str] | None = None) -> list[tuple[str, float]]:
        keys = list(self.ratings) if among is None else [h for h in among if h in self.ratings]
        return sorted(((h, self.ratings[h]) for h in keys), key=lambda kv: -kv[1])[:n]

    def snapshot(self, label: str) -> None:
        self.history.append({"label": label, "ratings": dict(self.ratings), "games": dict(self.games)})


# --------------------------------------------------------------------------- asynchronous task queue
@dataclass(order=True)
class Task:
    """A unit of work the Supervisor hands to a worker process."""

    priority: int
    seq: int = field(compare=True)
    agent: str = field(compare=False, default="")
    action: str = field(compare=False, default="")
    target: str | None = field(compare=False, default=None)
    payload: dict = field(compare=False, default_factory=dict)
    created_round: int = field(compare=False, default=0)

    def label(self) -> str:
        return f"{self.agent}.{self.action}" + (f"({self.target})" if self.target else "")


class TaskQueue:
    """A priority queue with FIFO tie-breaking — the GlobalTaskQueue of Supplementary Note 8."""

    def __init__(self) -> None:
        self._heap: list[Task] = []
        self._counter = itertools.count()
        self.completed: list[Task] = []

    def __len__(self) -> int:
        return len(self._heap)

    def push(self, agent: str, action: str, target: str | None = None, *, priority: int = 5,
             payload: dict | None = None, created_round: int = 0) -> Task:
        t = Task(priority, next(self._counter), agent, action, target, payload or {}, created_round)
        heapq.heappush(self._heap, t)
        return t

    def pop(self) -> Task | None:
        return heapq.heappop(self._heap) if self._heap else None

    def pending(self) -> list[Task]:
        return sorted(self._heap)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for t in self._heap:
            out[t.agent] = out.get(t.agent, 0) + 1
        return out


# --------------------------------------------------------------------------- context memory
class Memory:
    """The persistent context memory: hypotheses, reviews, matches, proximity graph, feedback.

    Methods, "Context memory": Co-Scientist "uses a persistent context memory to store and retrieve
    states of the agents and the system during the course of the computation".
    """

    def __init__(self, root: Path | str, plan: ResearchPlan | None = None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.plan = plan
        self.hypotheses: dict[str, Hypothesis] = {}
        self.reviews: list[Review] = []
        self.matches: list[Match] = []
        self.proximity: dict[tuple[str, str], float] = {}
        self.feedback: str = ""              # meta-review critique fed back into agent prompts
        self.overview: str = ""              # research overview
        self.articles: list[dict] = []       # literature seen so far
        self.elo = EloTable()
        self.id_prefix = "H"
        self._n = 0
        self._lock = threading.Lock()   # worker processes run concurrently

    # -- hypotheses
    def new_id(self, prefix: str | None = None) -> str:
        with self._lock:
            self._n += 1
            return f"{prefix or self.id_prefix}{self._n:02d}"

    def add(self, h: Hypothesis) -> Hypothesis:
        self.hypotheses[h.hid] = h
        return h

    def active(self) -> list[Hypothesis]:
        return [h for h in self.hypotheses.values() if h.status not in ("rejected", "duplicate")]

    def in_tournament(self) -> list[Hypothesis]:
        return [h for h in self.active() if h.hid in self.elo.ratings]

    def get(self, hid: str) -> Hypothesis:
        return self.hypotheses[hid]

    # -- reviews
    def add_review(self, r: Review) -> Review:
        self.reviews.append(r)
        return r

    def reviews_for(self, hid: str, kind: str | None = None) -> list[Review]:
        return [r for r in self.reviews if r.hid == hid and (kind is None or r.kind == kind)]

    def review_digest(self, hid: str, limit: int = 1200) -> str:
        rs = self.reviews_for(hid)
        if not rs:
            return "(no review yet)"
        parts = []
        for r in rs:
            sc = ", ".join(f"{k}={v}" for k, v in r.scores.items())
            parts.append(f"[{r.kind}] decision={r.decision} {sc}\n" + (r.text or "; ".join(r.critiques)))
        return "\n\n".join(parts)[:limit]

    # -- proximity
    def sim(self, a: str, b: str) -> float:
        return self.proximity.get((a, b), self.proximity.get((b, a), 0.0))

    # -- persistence
    def save(self) -> Path:
        blob = {
            "plan": self.plan.to_dict() if self.plan else None,
            "hypotheses": {k: asdict(v) for k, v in self.hypotheses.items()},
            "reviews": [asdict(r) for r in self.reviews],
            "matches": [asdict(m) for m in self.matches],
            "proximity": {f"{a}|{b}": v for (a, b), v in self.proximity.items()},
            "elo": {"ratings": self.elo.ratings, "games": self.elo.games, "history": self.elo.history},
            "feedback": self.feedback,
            "overview": self.overview,
        }
        p = self.root / "memory.json"
        p.write_text(json.dumps(blob, indent=1))
        return p


# --------------------------------------------------------------------------- helpers used by tests
def simulate_elo(strengths: dict[str, float], n_matches: int, seed: int = 0,
                 k: float = ELO_K) -> EloTable:
    """Play `n_matches` synthetic Bradley-Terry matches so the Elo update can be checked end-to-end."""
    rng = random.Random(seed)
    table = EloTable(k=k)
    names = list(strengths)
    for n in names:
        table.add(n)
    for _ in range(n_matches):
        a, b = rng.sample(names, 2)
        p_a = 1.0 / (1.0 + math.exp(-(strengths[a] - strengths[b])))
        w, l = (a, b) if rng.random() < p_a else (b, a)
        table.update(w, l)
    return table
