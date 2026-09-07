"""Reflection agent — the six review strategies of Methods, "Reflection agent".

  initial review            quick, tool-free filter on correctness / quality / novelty / safety
  full review               same axes but grounded in retrieved literature
  deep verification review  decompose into assumptions and sub-assumptions, probe each independently
  observation review        can the hypothesis explain long-tail observations in an article
                            (prompt reproduced from Supplementary Note 9.2)
  simulation review         step-wise simulation of the mechanism / experiment, failure scenarios
  tournament (recurrent)    a full review adapted to the meta-review critique and tournament state
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import common

from .literature import Article, bibliography, search_many
from .state import Hypothesis, Memory, Review, ResearchPlan

SYSTEM = ("You are a specialised Reflection agent inside a multi-agent AI co-scientist. You act as a "
          "rigorous scientific peer reviewer: exacting, specific, and willing to reject.")

SCORE_KEYS = ("correctness", "quality", "novelty", "safety")

# The paper leaves the discard decision to the model. We keep the model's recommendation but make
# the *filter* deterministic, so the notebook can show exactly which hypotheses are discarded and
# why; the thresholds follow the paper's default criteria (plausibility, novelty, safety).
INITIAL_THRESHOLDS = {"correctness": 4.0, "quality": 4.0, "novelty": 3.0, "safety": 5.0}


def passes(scores: dict[str, float], thresholds: dict[str, float] | None = None) -> tuple[bool, str]:
    """Deterministic quick filter over the reviewer's scores. Returns (passed, reason)."""
    th = thresholds or INITIAL_THRESHOLDS
    bad = [f"{k}={scores.get(k, 0):.0f}<{v:.0f}" for k, v in th.items() if float(scores.get(k, 0)) < v]
    return (not bad), ("below threshold: " + ", ".join(bad) if bad else "all criteria above threshold")


def _feedback(memory: Memory) -> str:
    if not memory.feedback:
        return ""
    return ("\n\nMeta-review critique from previous iterations — make sure your review explicitly "
            "addresses these recurring issues:\n" + memory.feedback.strip())


# --------------------------------------------------------------------------- initial review
INITIAL_PROMPT = """You are performing an INITIAL REVIEW: a fast, tool-free triage whose purpose is to discard flawed, non-novel or unsuitable hypotheses before any expensive review.

Goal: {goal}

Evaluation criteria:
{preferences}

Constraints the output must satisfy:
{constraints}

Hypothesis:
{hypothesis}
{feedback}

Assess, using only your own knowledge (no external sources):
1. Correctness — is the mechanism physically/technically sound? Name any readily apparent flaw.
2. Quality — is it specific, detailed and testable, or vague?
3. Novelty — is this simply standard practice already deployed at scale, or does it propose something not routine?
4. Safety — could acting on it cause harm (equipment damage, thermal excursion, unsafe operation)?

Return JSON:
{{"correctness": 0-10, "quality": 0-10, "novelty": 0-10, "safety": 0-10,
  "critiques": ["specific, actionable critique", ...],
  "decision": "accept" or "reject",
  "reason": "one sentence justifying the decision"}}
Reject if correctness < 4, or novelty < 3 (routine practice), or safety < 5."""


def initial_review(h: Hypothesis, plan: ResearchPlan, memory: Memory) -> Review:
    obj = common.chat_json(
        INITIAL_PROMPT.format(goal=plan.goal, preferences=plan.preferences_text,
                              constraints=plan.constraints_text, hypothesis=h.compact(),
                              feedback=_feedback(memory)),
        SYSTEM, tag="ref.initial", max_tokens=1200,
        validate=lambda o: [o[k] for k in SCORE_KEYS] and o["decision"])
    scores = {k: float(obj[k]) for k in SCORE_KEYS}
    ok, why = passes(scores)
    r = Review(h.hid, "initial", scores, "accept" if ok else "reject",
               [str(c) for c in obj.get("critiques", [])],
               str(obj.get("reason", "")) + f" [filter: {why}]",
               {"model_decision": str(obj["decision"]).lower(), "filter_reason": why})
    return r


# --------------------------------------------------------------------------- full review
FULL_PROMPT = """You are performing a FULL REVIEW with literature search. Evaluate correctness, quality and novelty of the hypothesis, grounding every judgement in the retrieved articles below.

Goal: {goal}

Evaluation criteria:
{preferences}

Hypothesis:
{hypothesis}

Retrieved literature:
{articles}
{feedback}

For correctness and quality, scrutinise the underlying assumptions and reasoning.
For novelty, first summarise which aspects of the hypothesis are already known from the literature above ("aspects already explored"), then judge what remains genuinely new ("novel aspects").

Return JSON:
{{"aspects_already_explored": ["..."], "novel_aspects": ["..."],
  "correctness": 0-10, "quality": 0-10, "novelty": 0-10, "safety": 0-10,
  "critiques": ["..."], "decision": "accept" or "reject", "reason": "..."}}"""


def full_review(h: Hypothesis, plan: ResearchPlan, memory: Memory, *, articles: list[Article] | None = None,
                n_articles: int = 4) -> Review:
    arts = articles if articles is not None else search_many([f"{h.title} data center cooling", h.category], limit=n_articles // 2 + 1)
    obj = common.chat_json(
        FULL_PROMPT.format(goal=plan.goal, preferences=plan.preferences_text, hypothesis=h.compact(),
                           articles=bibliography(arts[:n_articles]), feedback=_feedback(memory)),
        SYSTEM, tag="ref.full", max_tokens=1800,
        validate=lambda o: [o[k] for k in SCORE_KEYS] and o["decision"])
    scores = {k: float(obj[k]) for k in SCORE_KEYS}
    ok, why = passes(scores)
    return Review(h.hid, "full", scores, "accept" if ok else "reject",
                  [str(c) for c in obj.get("critiques", [])], str(obj.get("reason", "")) + f" [filter: {why}]",
                  {"already_explored": obj.get("aspects_already_explored", []),
                   "novel_aspects": obj.get("novel_aspects", []),
                   "model_decision": str(obj["decision"]).lower(), "filter_reason": why,
                   "articles": [a.title for a in arts[:n_articles]]})


# --------------------------------------------------------------------------- deep verification
DECOMPOSE_PROMPT = """Decompose the hypothesis into its constituent assumptions, then break each assumption into fundamental sub-assumptions. Decontextualise every sub-assumption so that it can be evaluated on its own, without reference to the hypothesis.

Goal: {goal}

Hypothesis:
{hypothesis}

Return JSON: {{"assumptions": [{{"assumption": "...", "sub_assumptions": ["decontextualised statement", ...], "fundamental": true/false}}]}}
"fundamental" means: if this assumption is false, the core hypothesis collapses.
Give at most {n} assumptions, each with at most 3 sub-assumptions."""

PROBE_PROMPT = """Evaluate the correctness of this standalone scientific statement, independently of any hypothesis it may have come from.

Statement: {statement}

Domain context: data centre thermal management and cooling energy.

Return JSON: {{"verdict": "correct" | "partially correct" | "incorrect" | "unknown",
 "reasoning": "2-4 sentences with the relevant physics, standards or typical numbers",
 "confidence": 0-1}}"""

AGGREGATE_PROMPT = """You are concluding a DEEP VERIFICATION REVIEW. Below are the hypothesis, its decomposed assumptions, and an independent correctness probe of each sub-assumption.

Goal: {goal}

Hypothesis:
{hypothesis}

Probe results:
{probes}

Summarise the reasons for potential hypothesis invalidation. For each incorrect or partially correct element, decide whether the error is FUNDAMENTAL to the hypothesis (it collapses) or NON-FUNDAMENTAL (it can be addressed in a later refinement).

Return JSON: {{"invalidating_elements": ["..."], "non_fundamental_errors": ["..."],
 "correctness": 0-10, "quality": 0-10, "novelty": 0-10, "safety": 0-10,
 "decision": "accept" | "reject", "reason": "..."}}"""


def deep_verification(h: Hypothesis, plan: ResearchPlan, memory: Memory, *, n_assumptions: int = 3,
                      workers: int = 6) -> tuple[Review, list[dict]]:
    dec = common.chat_json(
        DECOMPOSE_PROMPT.format(goal=plan.goal, hypothesis=h.compact(), n=n_assumptions),
        SYSTEM, tag="ref.deep.decompose", max_tokens=1400, validate=lambda o: o["assumptions"])
    items: list[dict] = []
    for a in dec["assumptions"][:n_assumptions]:
        for s in (a.get("sub_assumptions") or [a["assumption"]])[:3]:
            items.append({"assumption": a["assumption"], "fundamental": bool(a.get("fundamental")),
                          "sub_assumption": str(s)})

    def probe(it: dict) -> dict:
        o = common.chat_json(PROBE_PROMPT.format(statement=it["sub_assumption"]), SYSTEM,
                             tag="ref.deep.probe", max_tokens=600, validate=lambda o: o["verdict"])
        return {**it, "verdict": str(o["verdict"]), "reasoning": str(o.get("reasoning", "")),
                "confidence": float(o.get("confidence", 0.5))}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        probes = list(ex.map(probe, items))

    txt = "\n".join(f"- [{p['verdict']}, conf {p['confidence']:.2f}] {p['sub_assumption']}\n    {p['reasoning']}"
                    for p in probes)
    agg = common.chat_json(AGGREGATE_PROMPT.format(goal=plan.goal, hypothesis=h.compact(), probes=txt),
                           SYSTEM, tag="ref.deep.aggregate", max_tokens=1400,
                           validate=lambda o: o["decision"])
    r = Review(h.hid, "deep_verification", {k: float(agg.get(k, 5)) for k in SCORE_KEYS},
               str(agg["decision"]).lower(),
               [str(c) for c in agg.get("invalidating_elements", [])], str(agg.get("reason", "")),
               {"probes": probes, "non_fundamental_errors": agg.get("non_fundamental_errors", [])})
    return r, probes


# --------------------------------------------------------------------------- observation review
OBSERVATION_PROMPT = """You are an expert in scientific hypothesis evaluation. Your task is to analyze the relationship between a provided hypothesis and observations from a scientific article. Specifically, determine if the hypothesis provides a novel causal explanation for the observations, or if they contradict it.

Instructions:

1. Observation extraction: list relevant observations from the article.
2. Causal analysis (individual): for each observation:
   a. State if its cause is already established.
   b. Assess if the hypothesis could be a causal factor (hypothesis => observation). Start with: "would we see this observation if the hypothesis was true:".
   c. Explain if it's a novel explanation. If not, or if a better explanation exists, state: "not a missing piece."
3. Causal analysis (summary): determine if the hypothesis offers a novel explanation for a subset of observations. Include reasoning. Start with: "would we see some of the observations if the hypothesis was true:".
4. Disproof analysis: determine if any observations contradict the hypothesis. Start with: "does some observations disprove the hypothesis:".
5. Conclusion: state: "hypothesis: <already explained, other explanations more likely, missing piece, neutral, or disproved>".

Scoring:
* Already explained: hypothesis consistent, but causes are known. No novel explanation.
* Other explanations more likely: hypothesis *could* explain, but better explanations exist.
* Missing piece: hypothesis offers a novel, plausible explanation.
* Neutral: hypothesis neither explains nor is contradicted.
* Disproved: observations contradict the hypothesis.

Important: if observations are expected regardless of the hypothesis, and don't disprove it, it's neutral.

Article:
{article}

Hypothesis:
{hypothesis}

Response (provide reasoning; end with: "hypothesis: <already explained, other explanations more likely, missing piece, neutral, or disproved>")."""

OBS_VERDICTS = ("missing piece", "already explained", "other explanations more likely", "disproved", "neutral")


def observation_review(h: Hypothesis, plan: ResearchPlan, memory: Memory, article: Article) -> Review:
    text = common.chat(OBSERVATION_PROMPT.format(article=article.block(1600), hypothesis=h.compact()),
                       SYSTEM, tag="ref.observation", max_tokens=1600)
    tail = text.lower()[-400:]
    verdict = next((v for v in OBS_VERDICTS if v in tail), "neutral")
    return Review(h.hid, "observation", {}, "accept", [], text,
                  {"verdict": verdict, "article": article.title})


# --------------------------------------------------------------------------- simulation review
SIMULATION_PROMPT = """You are performing a SIMULATION REVIEW. Simulate the proposed mechanism and the proposed experiment in a step-wise fashion, as an internal world model of the system would, and identify where it fails.

Goal: {goal}

Hypothesis:
{hypothesis}

Simulate the mechanism step by step (state each intermediate physical state and the quantities involved),
then simulate the proposed experiment/deployment, then enumerate failure scenarios.

Return JSON: {{"steps": [{{"step": "...", "state": "...", "risk": "..."}}],
 "failure_scenarios": ["..."],
 "correctness": 0-10, "quality": 0-10, "novelty": 0-10, "safety": 0-10,
 "decision": "accept" | "reject", "reason": "..."}}"""


def simulation_review(h: Hypothesis, plan: ResearchPlan, memory: Memory) -> Review:
    obj = common.chat_json(SIMULATION_PROMPT.format(goal=plan.goal, hypothesis=h.compact()),
                           SYSTEM, tag="ref.simulation", max_tokens=1800, validate=lambda o: o["steps"])
    return Review(h.hid, "simulation", {k: float(obj.get(k, 5)) for k in SCORE_KEYS},
                  str(obj.get("decision", "accept")).lower(),
                  [str(c) for c in obj.get("failure_scenarios", [])], str(obj.get("reason", "")),
                  {"steps": obj["steps"]})


# --------------------------------------------------------------------------- tournament / recurrent review
TOURNAMENT_PROMPT = """You are performing a RECURRENT (TOURNAMENT) REVIEW. Co-Scientist's knowledge has grown: below are the meta-review critique synthesised from all previous reviews and the results of this hypothesis' tournament matches. Adapt your full review accordingly — explicitly check the recurring issues, and explain the win/loss pattern.

Goal: {goal}

Hypothesis:
{hypothesis}

Previous reviews of this hypothesis:
{prior}

Tournament record:
{record}

Meta-review critique (recurring issues across the whole system):
{critique}

Return JSON:
{{"recurring_issues_present": ["which of the recurring issues this hypothesis exhibits"],
  "win_loss_explanation": "why it wins or loses its matches",
  "improvement_opportunities": ["..."],
  "correctness": 0-10, "quality": 0-10, "novelty": 0-10, "safety": 0-10,
  "decision": "accept" | "reject", "reason": "..."}}"""


def tournament_review(h: Hypothesis, plan: ResearchPlan, memory: Memory) -> Review:
    rec = [m for m in memory.matches if h.hid in (m.a, m.b)]
    record = "\n".join(
        f"- vs {m.b if m.a == h.hid else m.a} ({m.mode}): {'WIN' if m.winner == h.hid else 'LOSS'} — {m.rationale[:200]}"
        for m in rec) or "(no matches yet)"
    obj = common.chat_json(
        TOURNAMENT_PROMPT.format(goal=plan.goal, hypothesis=h.compact(),
                                 prior=memory.review_digest(h.hid, 1500), record=record,
                                 critique=memory.feedback or "(none yet)"),
        SYSTEM, tag="ref.tournament", max_tokens=1600, validate=lambda o: o["decision"])
    return Review(h.hid, "tournament", {k: float(obj.get(k, 5)) for k in SCORE_KEYS},
                  str(obj["decision"]).lower(),
                  [str(c) for c in obj.get("improvement_opportunities", [])], str(obj.get("reason", "")),
                  {"recurring_issues_present": obj.get("recurring_issues_present", []),
                   "win_loss_explanation": obj.get("win_loss_explanation", "")})


# --------------------------------------------------------------------------- filtering
def screen(memory: Memory, plan: ResearchPlan, hyps: list[Hypothesis], *, workers: int = 6,
           full: bool = True) -> list[Review]:
    """Initial review on every new hypothesis (parallel); survivors get a full review.

    Rejected hypotheses are marked and never enter the tournament (Methods: "Effective reviews
    filter inaccurate and, when stipulated, non-novel hypotheses").
    """
    def _try(fn, h):
        try:
            return fn(h)
        except Exception as exc:
            print(f"  ! review of {h.hid} failed: {type(exc).__name__}: {exc}")
            return None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        initials = list(ex.map(lambda h: _try(lambda x: initial_review(x, plan, memory), h), hyps))
    out = []
    survivors = []
    for h, r in zip(hyps, initials):
        if r is None:
            continue
        memory.add_review(r)
        out.append(r)
        if r.decision == "reject":
            h.status, h.reject_reason = "rejected", r.text or "; ".join(r.critiques)
        else:
            h.status = "reviewed"          # passes the quick filter → eligible for the tournament
            survivors.append(h)
    if full and survivors:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            fulls = list(ex.map(lambda h: _try(lambda x: full_review(x, plan, memory), h), survivors))
        for h, r in zip(survivors, fulls):
            if r is None:
                continue
            memory.add_review(r)
            out.append(r)
            if r.decision == "reject":
                h.status, h.reject_reason = "rejected", r.text
            else:
                h.status = "reviewed"
    return out
