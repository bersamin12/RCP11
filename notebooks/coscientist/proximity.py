"""Proximity agent — Methods, "Proximity agent".

"The Proximity agent calculates the similarity between research hypotheses and proposals, and
builds a proximity graph, taking into account the specific research goal. ... it assists the
Ranking agent in organizing tournament matches" and enables "clustering of similar ideas,
de-duplication, and efficient exploration of the hypothesis landscape".

Similarity here is **LLM-judged** (one call per pair, run in parallel), not embedding-based: the
project's OpenRouter endpoint exposes chat completions only, and the paper's requirement that
similarity be computed "taking into account the specific research goal" is easier to honour with a
judge that sees the goal. Clustering and de-duplication below are pure Python.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from itertools import combinations

import common

from .state import Hypothesis, Memory, ResearchPlan

SYSTEM = ("You are a specialised Proximity agent inside a multi-agent AI co-scientist. You judge how "
          "close two research hypotheses are, relative to a research goal.")

SIM_PROMPT = """Judge the similarity of two research hypotheses with respect to the research goal.

Research goal: {goal}

Hypothesis A: {a}

Hypothesis B: {b}

Similarity is 1.0 if they propose essentially the same intervention and mechanism (only wording differs),
0.6-0.8 if they act on the same subsystem or share the dominant mechanism,
0.3-0.5 if they are related but attack different parts of the problem,
0.0-0.2 if they are unrelated approaches.

Return JSON: {{"similarity": 0.0-1.0, "shared_mechanism": "...", "rationale": "one sentence"}}"""


def similarity(plan: ResearchPlan, a: Hypothesis, b: Hypothesis) -> tuple[float, str]:
    obj = common.chat_json(
        SIM_PROMPT.format(goal=plan.goal, a=a.compact()[:900], b=b.compact()[:900]),
        SYSTEM, tag="prox.sim", max_tokens=400, validate=lambda o: o["similarity"] is not None)
    return max(0.0, min(1.0, float(obj["similarity"]))), str(obj.get("rationale", ""))


def build_graph(memory: Memory, plan: ResearchPlan, hyps: list[Hypothesis] | None = None, *,
                workers: int = 8, only_missing: bool = True) -> dict[tuple[str, str], float]:
    """Asynchronously (re)compute the proximity graph over all pairs. Existing edges are kept."""
    hyps = hyps if hyps is not None else memory.active()
    pairs = [(a, b) for a, b in combinations(hyps, 2)
             if not (only_missing and (a.hid, b.hid) in memory.proximity)]
    def one(p):
        try:
            return similarity(plan, *p)
        except Exception as exc:
            print(f"  ! similarity {p[0].hid}~{p[1].hid} failed: {type(exc).__name__}: {exc}")
            return None

    if pairs:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            sims = list(ex.map(one, pairs))
        for (a, b), sr in zip(pairs, sims):
            if sr is not None:
                memory.proximity[(a.hid, b.hid)] = sr[0]
    return memory.proximity


# --------------------------------------------------------------------------- pure-Python graph ops
def matrix(memory: Memory, hids: list[str]) -> list[list[float]]:
    return [[1.0 if a == b else memory.sim(a, b) for b in hids] for a in hids]


def clusters(memory: Memory, hids: list[str], threshold: float = 0.6) -> list[list[str]]:
    """Single-linkage clustering: connected components of the graph thresholded at `threshold`."""
    parent = {h: h for h in hids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in combinations(hids, 2):
        if memory.sim(a, b) >= threshold:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb
    groups: dict[str, list[str]] = {}
    for h in hids:
        groups.setdefault(find(h), []).append(h)
    return sorted(groups.values(), key=lambda g: (-len(g), g[0]))


def duplicates(memory: Memory, hids: list[str], threshold: float = 0.85) -> list[tuple[str, str, float]]:
    return sorted([(a, b, memory.sim(a, b)) for a, b in combinations(hids, 2)
                   if memory.sim(a, b) >= threshold], key=lambda t: -t[2])


def dedupe(memory: Memory, threshold: float = 0.85) -> list[tuple[str, str, float]]:
    """Mark the lower-rated member of each near-duplicate pair as a duplicate (it leaves the tournament)."""
    hids = [h.hid for h in memory.active()]
    dropped = []
    for a, b, s in duplicates(memory, hids, threshold):
        ha, hb = memory.get(a), memory.get(b)
        if ha.status == "duplicate" or hb.status == "duplicate":
            continue
        loser = a if memory.elo.rating(a) <= memory.elo.rating(b) else b
        keep = b if loser == a else a
        memory.get(loser).status = "duplicate"
        memory.get(loser).reject_reason = f"near-duplicate of {keep} (similarity {s:.2f})"
        dropped.append((loser, keep, s))
    return dropped
