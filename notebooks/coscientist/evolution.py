"""Evolution agent — Methods, "Evolution agent".

Six refinement strategies. Each one produces a **new** hypothesis: "The Evolution agent generates
new hypotheses; it doesn't modify or replace existing ones. This strategy protects the quality of
top-ranked hypotheses from flawed improvements, as each new hypothesis must also compete in the
tournament."

  enhance_by_grounding   weaknesses → search queries → retrieved articles → filled reasoning gaps
  improve_feasibility    coherence / practicality / feasibility (prompt from Supp. Note 9.4)
  inspiration            a new hypothesis inspired by one top-ranked hypothesis
  combination            combine the best aspects of several top-ranked hypotheses
  simplification         simplify for easier verification and testing
  out_of_the_box         divergent idea moving away from a subset of hypotheses (Supp. Note 9.4)
"""
from __future__ import annotations

import common

from .generation import HYPOTHESIS_SCHEMA, _feedback_block, _mk, _validate
from .literature import bibliography, search_many
from .state import Hypothesis, Memory, ResearchPlan

SYSTEM = ("You are a specialised Evolution agent inside a multi-agent AI co-scientist. You refine and "
          "diversify research hypotheses; you never merely restate the input.")


def _gen(memory: Memory, plan: ResearchPlan, prompt: str, strategy: str, parents: list[str],
         *, rnd: int = 0, tag: str, max_tokens: int = 2000, articles=None) -> Hypothesis:
    obj = common.chat_json(prompt, SYSTEM, tag=tag, max_tokens=max_tokens, validate=_validate)
    return _mk(memory, plan, obj, strategy, parents=parents, rnd=rnd,
               articles=[a.title for a in (articles or [])[:4]])


# --------------------------------------------------------------------------- enhancement through grounding
def enhance_by_grounding(memory: Memory, plan: ResearchPlan, h: Hypothesis, *, rnd: int = 0,
                         n_articles: int = 4) -> tuple[Hypothesis, list[str], list]:
    q = common.chat_json(
        f"Goal: {plan.goal}\n\nHypothesis:\n{h.compact()}\n\nReviews:\n{memory.review_digest(h.hid, 1200)}\n\n"
        f'Identify this hypothesis\' weakest, least-supported reasoning gaps and write 2 literature search '
        f'queries that would fill them. Return JSON: {{"weaknesses": ["..."], "queries": ["...", "..."]}}',
        SYSTEM, tag="evo.ground.queries", max_tokens=700, validate=lambda o: o["queries"])
    arts = search_many([str(x) for x in q["queries"]][:2], limit=n_articles // 2 + 1)
    prompt = (f"Goal: {plan.goal}\n\nCriteria:\n{plan.preferences_text}\n\n"
              f"Original hypothesis:\n{h.compact()}\n\n"
              f"Identified weaknesses:\n" + "\n".join(f"- {w}" for w in q.get("weaknesses", [])) + "\n\n"
              f"Retrieved literature to ground the fix:\n{bibliography(arts[:n_articles])}\n\n"
              f"Produce a NEW, strengthened hypothesis that uses this literature to fill the reasoning gaps "
              f"and elaborates the missing detail. Keep the core idea but make it defensible and specific."
              f"{_feedback_block(memory)}\n\n{HYPOTHESIS_SCHEMA}")
    new = _gen(memory, plan, prompt, "evo:grounding", [h.hid], rnd=rnd, tag="evo.ground", articles=arts)
    return new, [str(w) for w in q.get("weaknesses", [])], arts


# --------------------------------------------------------------------------- feasibility (Supp. Note 9.4)
FEASIBILITY_PROMPT = """You are an expert in scientific research and technological feasibility analysis. Your task is to refine the provided conceptual idea, enhancing its practical implementability by leveraging contemporary technological capabilities. Ensure the revised concept retains its novelty, logical coherence, and specific articulation.

Goal: {goal}

Guidelines:
1. Begin with an introductory overview of the relevant scientific domain.
2. Provide a concise synopsis of recent pertinent research findings and related investigations, highlighting successful methodologies and established precedents.
3. Articulate a reasoned argument for how current technological advancements can facilitate the realization of the proposed concept.
4. CORE CONTRIBUTION: Develop a detailed, innovative, and technologically viable alternative to achieve the objective, emphasizing simplicity and practicality.

Evaluation Criteria:
{preferences}

Original Conceptualization:
{hypothesis}

Known issues raised in review:
{critiques}
{feedback}

Response:

{schema}"""


def improve_feasibility(memory: Memory, plan: ResearchPlan, h: Hypothesis, *, rnd: int = 0) -> Hypothesis:
    prompt = FEASIBILITY_PROMPT.format(
        goal=plan.goal, preferences=plan.preferences_text, hypothesis=h.compact(),
        critiques="\n".join(f"- {c}" for r in memory.reviews_for(h.hid) for c in r.critiques) or "(none)",
        feedback=_feedback_block(memory), schema=HYPOTHESIS_SCHEMA)
    return _gen(memory, plan, prompt, "evo:feasibility", [h.hid], rnd=rnd, tag="evo.feasibility")


# --------------------------------------------------------------------------- inspiration / combination
def inspiration(memory: Memory, plan: ResearchPlan, h: Hypothesis, *, rnd: int = 0) -> Hypothesis:
    prompt = (f"Goal: {plan.goal}\n\nCriteria:\n{plan.preferences_text}\n\n"
              f"Top-ranked hypothesis to draw inspiration from:\n{h.compact()}\n\n"
              f"Create a NEW hypothesis inspired by it — same underlying insight, different intervention or "
              f"different point of application. It must not be a rewording of the original."
              f"{_feedback_block(memory)}\n\n{HYPOTHESIS_SCHEMA}")
    return _gen(memory, plan, prompt, "evo:inspiration", [h.hid], rnd=rnd, tag="evo.inspiration")


def combination(memory: Memory, plan: ResearchPlan, hs: list[Hypothesis], *, rnd: int = 0) -> Hypothesis:
    listing = "\n\n".join(h.compact() for h in hs)
    prompt = (f"Goal: {plan.goal}\n\nCriteria:\n{plan.preferences_text}\n\n"
              f"Top-ranked hypotheses:\n{listing}\n\n"
              f"Directly combine the best aspects of these hypotheses into ONE new, stronger hypothesis. "
              f"State explicitly which element comes from which parent and why the combination is more than "
              f"the sum of its parts (e.g. shared sensing, shared control loop, complementary energy paths)."
              f"{_feedback_block(memory)}\n\n{HYPOTHESIS_SCHEMA}")
    return _gen(memory, plan, prompt, "evo:combination", [h.hid for h in hs], rnd=rnd, tag="evo.combination")


def simplification(memory: Memory, plan: ResearchPlan, h: Hypothesis, *, rnd: int = 0) -> Hypothesis:
    prompt = (f"Goal: {plan.goal}\n\nCriteria:\n{plan.preferences_text}\n\n"
              f"Hypothesis to simplify:\n{h.compact()}\n\n"
              f"Produce a NEW, simplified hypothesis that is easier to verify and test: fewer moving parts, "
              f"fewer coupled assumptions, a single decisive measurement. Do not lose the core claim."
              f"{_feedback_block(memory)}\n\n{HYPOTHESIS_SCHEMA}")
    return _gen(memory, plan, prompt, "evo:simplification", [h.hid], rnd=rnd, tag="evo.simplification")


# --------------------------------------------------------------------------- out-of-the-box (Supp. Note 9.4)
OUT_OF_BOX_PROMPT = """You are an expert researcher tasked with generating a novel, singular hypothesis inspired by analogous elements from provided concepts.

Goal: {goal}

Instructions:
1. Provide a concise introduction to the relevant scientific domain.
2. Summarize recent findings and pertinent research, highlighting successful approaches.
3. Identify promising avenues for exploration that may yield innovative hypotheses.
4. CORE HYPOTHESIS: Develop a detailed, original, and specific single hypothesis for achieving the stated goal, leveraging analogous principles from the provided ideas. This should not be a mere aggregation of existing methods or entities. Think out-of-the-box.

Criteria for a robust hypothesis:
{preferences}

Inspiration may be drawn from the following concepts (utilize analogy and inspiration, not direct replication):
{hypotheses}
{feedback}

Response:

{schema}"""


def out_of_the_box(memory: Memory, plan: ResearchPlan, hs: list[Hypothesis], *, rnd: int = 0) -> Hypothesis:
    prompt = OUT_OF_BOX_PROMPT.format(
        goal=plan.goal, preferences=plan.preferences_text,
        hypotheses="\n\n".join(f"- {h.title}: {h.statement}" for h in hs),
        feedback=_feedback_block(memory), schema=HYPOTHESIS_SCHEMA)
    return _gen(memory, plan, prompt, "evo:out-of-the-box", [h.hid for h in hs], rnd=rnd,
                tag="evo.outofbox", max_tokens=2200)


STRATEGIES = ["grounding", "feasibility", "inspiration", "combination", "simplification", "out-of-the-box"]


def evolve_top(memory: Memory, plan: ResearchPlan, *, top_n: int = 3, rnd: int = 0,
               strategies: list[str] | None = None, workers: int = 4) -> list[Hypothesis]:
    """EvolveTopHypotheses (Supp. Note 8): apply a set of strategies to the current top hypotheses."""
    from concurrent.futures import ThreadPoolExecutor

    strategies = strategies or STRATEGIES
    top_ids = [h for h, _ in memory.elo.top(top_n, among=[x.hid for x in memory.active()])]
    if not top_ids:
        return []
    tops = [memory.get(h) for h in top_ids]
    jobs = []
    for s in strategies:
        if s == "grounding":
            jobs.append(lambda t=tops[0]: enhance_by_grounding(memory, plan, t, rnd=rnd)[0])
        elif s == "feasibility":
            jobs.append(lambda t=tops[min(1, len(tops) - 1)]: improve_feasibility(memory, plan, t, rnd=rnd))
        elif s == "inspiration":
            jobs.append(lambda t=tops[0]: inspiration(memory, plan, t, rnd=rnd))
        elif s == "combination" and len(tops) >= 2:
            jobs.append(lambda t=tops[:2]: combination(memory, plan, t, rnd=rnd))
        elif s == "simplification":
            jobs.append(lambda t=tops[min(2, len(tops) - 1)]: simplification(memory, plan, t, rnd=rnd))
        elif s == "out-of-the-box":
            jobs.append(lambda t=tops: out_of_the_box(memory, plan, t, rnd=rnd))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(lambda f: f(), jobs))
