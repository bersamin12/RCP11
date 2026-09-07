"""Ranking agent — the Elo tournament of Methods, "Ranking agent".

  * newly reviewed hypotheses enter at Elo 1200 (AddToTournament, Supp. Note 8);
  * most pairs are compared with a single-turn pairwise comparison (Supp. Note 9.3, prompt 1);
  * top-ranked pairs are compared through a multi-turn simulated scientific debate
    (Supp. Note 9.3, prompt 2), which the paper reports reduces positional bias;
  * pairing prioritises (1) similar hypotheses, using the Proximity agent's graph, and
    (2) newer and top-ranked hypotheses.
"""
from __future__ import annotations

import random
import re
from concurrent.futures import ThreadPoolExecutor

import common

from .state import Hypothesis, Match, Memory, ResearchPlan

SYSTEM = ("You are a specialised Ranking agent inside a multi-agent AI co-scientist. You compare "
          "research hypotheses without positional bias and always end with the required verdict line.")

COMPARE_PROMPT = """You are an expert evaluator tasked with comparing two hypotheses.

Evaluate the two provided hypotheses (hypothesis 1 and hypothesis 2) and determine which one is superior based on the specified {idea_attributes}.
Provide a concise rationale for your selection, concluding with the phrase "better hypothesis: <1 or 2>".

Goal: {goal}

Evaluation criteria:
{preferences}

Considerations:
{notes}
Each hypothesis includes an independent review. These reviews may contain numerical scores. Disregard these scores in your comparative analysis, as they may not be directly comparable across reviews.

Hypothesis 1:
{h1}

Hypothesis 2:
{h2}

Review of hypothesis 1:
{r1}

Review of hypothesis 2:
{r2}

Reasoning and conclusion (end with "better hypothesis: <1 or 2>"):"""

DEBATE_PROMPT = """You are an expert in comparative analysis, simulating a panel of domain experts engaged in a structured discussion to evaluate two competing hypotheses. The objective is to rigorously determine which hypothesis is superior based on a predefined set of attributes and criteria. The experts possess no pre-existing biases toward either hypothesis and are solely focused on identifying the optimal choice, given that only one can be implemented.

Goal: {goal}

Criteria for hypothesis superiority:
{preferences}

Hypothesis 1:
{h1}

Hypothesis 2:
{h2}

Initial review of hypothesis 1:
{r1}

Initial review of hypothesis 2:
{r2}

Debate procedure:

The discussion will unfold in a series of turns, typically ranging from 3 to 5, with a maximum of 10.

Turn 1: begin with a concise summary of both hypotheses and their respective initial reviews.
Subsequent turns:
* Pose clarifying questions to address any ambiguities or uncertainties.
* Critically evaluate each hypothesis in relation to the stated Goal and Criteria. This evaluation should consider aspects such as:
       - Potential for correctness/validity.
       - Utility and practical applicability.
       - Sufficiency of detail and specificity.
       - Novelty and originality.
       - Desirability for implementation.
* Identify and articulate any weaknesses, limitations, or potential flaws in either hypothesis.

Additional notes:
{notes}

Termination and judgment:

Once the discussion has reached a point of sufficient depth (typically 3-5 turns, up to 10 turns) and all relevant questions and concerns have been thoroughly addressed, provide a conclusive judgment. This judgment should succinctly state the rationale for the selection. Then, indicate the superior hypothesis by writing the phrase "better idea: ", followed by "1" (for hypothesis 1) or "2" (for hypothesis 2).

#BEGIN TRANSCRIPT#
{transcript}
#END TRANSCRIPT#

Your turn:"""

_VERDICT = re.compile(r"better\s+(?:idea|hypothesis)\s*:\s*\**\s*([12])", re.I)


def parse_verdict(text: str) -> int | None:
    hits = _VERDICT.findall(text or "")
    return int(hits[-1]) if hits else None


# --------------------------------------------------------------------------- one match
def compare(memory: Memory, plan: ResearchPlan, a: Hypothesis, b: Hypothesis, *, rnd: int = 0,
            swap: bool = False) -> Match:
    """Single-turn pairwise comparison. ``swap`` presents b first, to average out positional bias."""
    h1, h2 = (b, a) if swap else (a, b)
    text = common.chat(
        COMPARE_PROMPT.format(idea_attributes=plan.idea_attributes, goal=plan.goal,
                              preferences=plan.preferences_text,
                              notes=memory.feedback[:1500] or "(none)",
                              h1=h1.compact(), h2=h2.compact(),
                              r1=memory.review_digest(h1.hid, 800), r2=memory.review_digest(h2.hid, 800)),
        SYSTEM, tag="rank.compare", max_tokens=1200)
    v = parse_verdict(text)
    win = h1 if v == 1 else h2 if v == 2 else (a if len(a.rationale) >= len(b.rationale) else b)
    return Match(a.hid, b.hid, win.hid, "single-turn", (text or "")[-500:].strip(), 1, rnd, text)


def debate(memory: Memory, plan: ResearchPlan, a: Hypothesis, b: Hypothesis, *, turns: int = 3,
           rnd: int = 0, swap: bool = False, verbose: bool = False) -> Match:
    """Multi-turn simulated scientific debate for top-ranked pairs."""
    h1, h2 = (b, a) if swap else (a, b)
    transcript: list[str] = []
    text = ""
    for t in range(turns):
        joined = "\n\n".join(f"--- turn {i + 1} ---\n{x}" for i, x in enumerate(transcript)) or "(empty — this is turn 1)"
        text = common.chat(
            DEBATE_PROMPT.format(goal=plan.goal, preferences=plan.preferences_text,
                                 h1=h1.compact(), h2=h2.compact(),
                                 r1=memory.review_digest(h1.hid, 800), r2=memory.review_digest(h2.hid, 800),
                                 notes=(memory.feedback[:1200] or "(none)")
                                 + ("\nThis is the final turn: deliver the judgment now." if t == turns - 1 else ""),
                                 transcript=joined),
            SYSTEM, tag="rank.debate", max_tokens=1400)
        transcript.append(text)
        if verbose:
            print(f"    debate turn {t + 1}: {len(text)} chars"
                  + (" → verdict" if parse_verdict(text) else ""))
        if parse_verdict(text) and t >= turns - 1:
            break
    v = parse_verdict("\n".join(transcript[-1:])) or parse_verdict("\n".join(transcript))
    win = h1 if v == 1 else h2 if v == 2 else a
    full = "\n\n".join(f"--- turn {i + 1} ---\n{x}" for i, x in enumerate(transcript))
    return Match(a.hid, b.hid, win.hid, "multi-turn-debate", (text or "")[-500:].strip(), len(transcript), rnd, full)


# --------------------------------------------------------------------------- pairing
def pair_scores(memory: Memory, hyps: list[Hypothesis], current_round: int,
                w_sim: float = 1.0, w_new: float = 0.6, w_top: float = 0.6,
                w_games: float = 0.5) -> list[tuple[float, str, str]]:
    """Score every candidate pair.

    Methods: "hypotheses are more likely to be compared with similar ones (based on the Proximity
    agent's graph); newer and top-ranking hypotheses are prioritized for participation".
    A match-count term keeps under-played hypotheses in the rotation.
    """
    if len(hyps) < 2:
        return []
    elo = memory.elo
    ratings = [elo.rating(h.hid) for h in hyps]
    lo, hi = min(ratings), max(ratings)
    span = (hi - lo) or 1.0
    max_games = max([elo.games.get(h.hid, 0) for h in hyps]) or 1
    out = []
    for i, a in enumerate(hyps):
        for b in hyps[i + 1:]:
            sim = memory.sim(a.hid, b.hid)
            new = max(0.0, min(1.0, 1.0 - (current_round - max(a.round, b.round)) / 3.0))
            top = max((elo.rating(a.hid) - lo) / span, (elo.rating(b.hid) - lo) / span)
            few = 1.0 - min(elo.games.get(a.hid, 0), elo.games.get(b.hid, 0)) / max_games
            out.append((w_sim * sim + w_new * new + w_top * top + w_games * few, a.hid, b.hid))
    return sorted(out, key=lambda t: -t[0])


def balanced_pairs(memory: Memory, hyps: list[Hypothesis], rng: random.Random) -> list[tuple[float, str, str]]:
    """Pairing for a *benchmark* tournament: prefer the pairs whose members have played least.

    Used by :func:`joint_tournament`, where every candidate must get a comparable number of matches;
    the proximity/newness/top-rank priorities of the main tournament would starve one arm.
    """
    out = []
    for i, a in enumerate(hyps):
        for b in hyps[i + 1:]:
            played = memory.elo.games.get(a.hid, 0) + memory.elo.games.get(b.hid, 0)
            out.append((-played + rng.random() * 0.5, a.hid, b.hid))
    return sorted(out, key=lambda t: -t[0])


def choose_pairs(memory: Memory, hyps: list[Hypothesis], n: int, current_round: int,
                 rng: random.Random | None = None, max_per_hyp: int = 3,
                 pairing: str = "proximity") -> list[tuple[str, str]]:
    """Take the highest-scoring pairs, capping how often one hypothesis appears in a round."""
    rng = rng or random.Random(0)
    scored = balanced_pairs(memory, hyps, rng) if pairing == "balanced" else pair_scores(memory, hyps, current_round)
    used: dict[str, int] = {}
    picked: list[tuple[str, str]] = []
    for _, a, b in scored:
        if len(picked) >= n:
            break
        if used.get(a, 0) >= max_per_hyp or used.get(b, 0) >= max_per_hyp:
            continue
        picked.append((a, b))
        used[a] = used.get(a, 0) + 1
        used[b] = used.get(b, 0) + 1
    return picked


# --------------------------------------------------------------------------- a tournament round
def run_round(memory: Memory, plan: ResearchPlan, *, n_matches: int = 6, current_round: int = 0,
              top_k: int = 3, debate_turns: int = 3, workers: int = 4,
              rng: random.Random | None = None, verbose: bool = True,
              pairing: str = "proximity") -> list[Match]:
    """Add newcomers at 1200, pick pairs, run the matches (parallel) and apply the Elo updates."""
    rng = rng or random.Random(current_round)
    hyps = [h for h in memory.active() if h.status in ("reviewed", "new")]
    for h in hyps:
        memory.elo.add(h.hid)
    pairs = choose_pairs(memory, hyps, n_matches, current_round, rng, pairing=pairing)
    top = {h for h, _ in memory.elo.top(top_k, among=[x.hid for x in hyps])}

    def play(idx_pair):
        i, (a, b) = idx_pair
        ha, hb = memory.get(a), memory.get(b)
        swap = bool(i % 2)                       # alternate presentation order across matches
        try:
            if a in top and b in top:
                return debate(memory, plan, ha, hb, turns=debate_turns, rnd=current_round, swap=swap)
            return compare(memory, plan, ha, hb, rnd=current_round, swap=swap)
        except Exception as exc:                 # one unusable reply must not abort the round
            print(f"  ! match {a} vs {b} skipped: {type(exc).__name__}: {exc}")
            return None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        matches = [m for m in ex.map(play, enumerate(pairs)) if m is not None]
    for m in matches:
        loser = m.b if m.winner == m.a else m.a
        d, _ = memory.elo.update(m.winner, loser)
        memory.matches.append(m)
        if verbose:
            print(f"  {m.a} vs {m.b} [{m.mode}] → {m.winner} (+{d:.1f})")
    memory.elo.snapshot(f"round {current_round}")
    return matches


# --------------------------------------------------------------------------- joint evaluation
def joint_tournament(hyps: list[Hypothesis], plan: ResearchPlan, root, *, rounds: int = 3,
                     n_matches: int = 6, workers: int = 4, verbose: bool = True) -> Memory:
    """Rank a mixed population (e.g. two system variants) inside one common Elo tournament.

    This is how the paper benchmarks Co-Scientist against baselines (Fig. 2b): every candidate
    enters the same tournament at 1200. No reviews are carried over, so both arms are judged on the
    hypothesis text alone, and all matches are single-turn comparisons.
    """
    ev = Memory(root, plan)
    for h in hyps:
        ev.hypotheses[h.hid] = h
        ev.elo.add(h.hid)
    ev.elo.snapshot("start")
    for r in range(rounds):
        run_round(ev, plan, n_matches=n_matches, current_round=r, top_k=0, workers=workers,
                  verbose=verbose, pairing="balanced")
    return ev
