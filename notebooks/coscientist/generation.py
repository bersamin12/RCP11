"""Generation agent — the four strategies of Methods, "Generation agent".

  * literature exploration via web search  (Supp. Note 9.1, prompt 1)
  * simulated scientific debate            (Supp. Note 9.1, prompt 2 — multi-turn self-play)
  * iterative assumptions identification   (Methods; conditional reasoning hops)
  * research expansion                     (Methods; uses the Meta-review agent's feedback)

Every model call goes through ``common.chat`` / ``common.chat_json``.
"""
from __future__ import annotations

import json
import re

import common

from .literature import Article, bibliography, search_many
from .state import Hypothesis, Memory, ResearchPlan

HYPOTHESIS_SCHEMA = """Return a JSON object with exactly these keys:
{"title": "<= 12 words",
 "category": "one short phrase categorising the idea (e.g. 'airflow management')",
 "summary": "2-3 sentences a domain expert can skim",
 "hypothesis": "the core hypothesis: specific entities, mechanisms and anticipated outcomes",
 "rationale": "rationale and specificity: why this mechanism, what makes it specific and non-obvious",
 "experiment": "experimental design and validation, including the measurable quantities and the acceptance criterion",
 "assumptions": ["3-6 testable intermediate assumptions the hypothesis rests on"]}"""

SYSTEM = ("You are a specialised Generation agent inside a multi-agent AI co-scientist. "
          "You produce novel, plausible, testable research hypotheses for an expert audience.")


def _feedback_block(memory: Memory) -> str:
    """Methods, Meta-review agent: feedback "is simply appended to their prompts in the next iteration"."""
    if not memory.feedback:
        return ""
    return ("\n\nFeedback from the Meta-review agent (recurring critique patterns observed in previous "
            "reviews and tournament debates — use it to avoid repeating these issues, but do not "
            "over-fit to it):\n" + memory.feedback.strip())


def _mk(memory: Memory, plan: ResearchPlan, obj: dict, strategy: str, *, parents: list[str] | None = None,
        articles: list[str] | None = None, rnd: int = 0) -> Hypothesis:
    h = Hypothesis(
        hid=memory.new_id(),
        title=str(obj.get("title", ""))[:160],
        category=str(obj.get("category", "")),
        summary=str(obj.get("summary", "")),
        statement=str(obj.get("hypothesis", obj.get("statement", ""))),
        rationale=str(obj.get("rationale", "")),
        experiment=str(obj.get("experiment", "")),
        assumptions=[str(a) for a in (obj.get("assumptions") or [])][:8],
        strategy=strategy,
        parents=parents or [],
        round=rnd,
        articles=articles or [],
    )
    return memory.add(h)


def _validate(obj):
    for k in ("title", "hypothesis", "rationale", "experiment"):
        if not str(obj.get(k, "")).strip():
            raise ValueError(f"missing field {k!r}")


# --------------------------------------------------------------------------- 1. literature exploration
def search_queries(plan: ResearchPlan, n: int = 3, memory: Memory | None = None) -> list[str]:
    """The agent first decides what to search for (the 'iteratively searches the web' step)."""
    prompt = (f"Research goal: {plan.goal}\n\nCriteria for a strong hypothesis:\n{plan.preferences_text}\n"
              f"{_feedback_block(memory) if memory else ''}\n\n"
              f"Propose {n} distinct literature search queries that would ground a novel hypothesis for "
              f"this goal. Cover different mechanisms, not paraphrases of each other. "
              f'Return JSON: {{"queries": ["...", ...]}}')
    obj = common.chat_json(prompt, SYSTEM, tag="gen.queries", max_tokens=600,
                           validate=lambda o: o["queries"])
    return [str(q) for q in obj["queries"]][:n]


LITERATURE_PROMPT = """You are an expert tasked with formulating a novel and robust hypothesis to address the following objective.

Describe the proposed hypothesis in detail, including specific entities, mechanisms, and anticipated outcomes.

This description is intended for an audience of domain experts.

You have conducted a thorough review of relevant literature and developed a logical framework for addressing the objective. The articles consulted, along with your analytical reasoning, are provided below.

Goal: {goal}

Criteria for a strong hypothesis:
{preferences}

Constraints:
{constraints}

Existing hypothesis (if applicable):
{source_hypothesis}

{instructions}{feedback}

Literature review and analytical rationale (chronologically ordered, beginning with the most recent analysis):

{articles_with_reasoning}

Proposed hypothesis (detailed description for domain experts):

{schema}"""


def from_literature(memory: Memory, plan: ResearchPlan, articles: list[Article], *,
                    instructions: str = "", source_hypothesis: str = "none", rnd: int = 0) -> Hypothesis:
    prompt = LITERATURE_PROMPT.format(
        goal=plan.goal, preferences=plan.preferences_text, constraints=plan.constraints_text,
        source_hypothesis=source_hypothesis, instructions=instructions,
        feedback=_feedback_block(memory), articles_with_reasoning=bibliography(articles),
        schema=HYPOTHESIS_SCHEMA)
    obj = common.chat_json(prompt, SYSTEM, tag="gen.literature", max_tokens=2000, validate=_validate)
    return _mk(memory, plan, obj, "literature", articles=[a.title for a in articles[:4]], rnd=rnd)


# --------------------------------------------------------------------------- 2. simulated debate
DEBATE_PROMPT = """You are an expert participating in a collaborative discourse concerning the generation of a {idea_attributes} hypothesis. You will engage in a simulated discussion with other experts. The overarching objective of this discourse is to collaboratively develop a novel and robust {idea_attributes} hypothesis.

Goal: {goal}

Criteria for a high-quality hypothesis:
{preferences}

Instructions:
{instructions}

Review Overview:
{reviews_overview}

Procedure:

Initial contribution (if initiating the discussion):
Propose three distinct {idea_attributes} hypotheses.

Subsequent contributions (continuing the discussion):
* Pose clarifying questions if ambiguities or uncertainties arise.
* Critically evaluate the hypotheses proposed thus far, addressing the following aspects:
      - Adherence to {idea_attributes} criteria.
      - Utility and practicality.
      - Level of detail and specificity.
* Identify any weaknesses or potential limitations.
* Propose concrete improvements and refinements to address identified weaknesses.
* Conclude your response with a refined iteration of the hypothesis.

General guidelines:
* Exhibit boldness and creativity in your contributions.
* Maintain a helpful and collaborative approach.
* Prioritize the generation of a high-quality {idea_attributes} hypothesis.

Termination condition:
When sufficient discussion has transpired (typically 3-5 conversational turns, with a maximum of 10 turns) and all relevant questions and points have been thoroughly addressed and clarified, conclude the process by writing "HYPOTHESIS" (in all capital letters) followed by a concise and self-contained exposition of the finalized idea.

#BEGIN TRANSCRIPT#
{transcript}
#END TRANSCRIPT#

Your Turn:"""


def simulated_debate(memory: Memory, plan: ResearchPlan, *, max_turns: int = 4, rnd: int = 0,
                     reviews_overview: str = "", verbose: bool = False) -> tuple[Hypothesis, list[str]]:
    """Self-play: the same model plays every expert; the transcript grows turn by turn.

    Returns the finalised hypothesis and the raw transcript turns.
    """
    turns: list[str] = []
    final = ""
    for t in range(max_turns):
        transcript = "\n\n".join(f"--- turn {i + 1} ---\n{x}" for i, x in enumerate(turns)) or "(empty — you are initiating the discussion)"
        prompt = DEBATE_PROMPT.format(
            idea_attributes=plan.idea_attributes, goal=plan.goal, preferences=plan.preferences_text,
            instructions=(plan.notes or "Be concrete and quantitative.") + _feedback_block(memory),
            reviews_overview=reviews_overview or "(no reviews yet)", transcript=transcript)
        reply = common.chat(prompt, SYSTEM, tag="gen.debate", max_tokens=1400,
                            temperature=0.9 if t == 0 else 0.7)
        turns.append(reply)
        if verbose:
            print(f"  debate turn {t + 1}: {len(reply)} chars"
                  + ("  → HYPOTHESIS declared" if "HYPOTHESIS" in reply else ""))
        if "HYPOTHESIS" in reply and t >= 1:
            final = reply.split("HYPOTHESIS", 1)[1].strip()
            break
    final = final or turns[-1]
    obj = common.chat_json(
        f"Goal: {plan.goal}\n\nA panel of experts concluded a scientific debate with this finalised idea:\n\n{final}\n\n"
        f"Restate it in the structured format below without adding new content.\n\n{HYPOTHESIS_SCHEMA}",
        SYSTEM, tag="gen.debate.format", max_tokens=1800, validate=_validate)
    return _mk(memory, plan, obj, "debate", rnd=rnd), turns


# --------------------------------------------------------------------------- 3. iterative assumptions
ASSUMPTION_PROMPT = """You are an expert identifying testable intermediate assumptions that, if proven true, would lead to a novel scientific discovery for the stated goal.

Goal: {goal}
Criteria: {preferences}
{prior}{feedback}

Perform ONE conditional reasoning hop: for each assumption below, state what would become plausible *if it held*, and name the next, more specific sub-assumption implied by it.

Return JSON: {{"assumptions": [{{"assumption": "...", "if_true_then": "...", "sub_assumption": "...", "testable_with": "how it could be measured or simulated"}}]}}
Give {n} entries."""


def assumption_hops(plan: ResearchPlan, memory: Memory, *, hops: int = 2, n: int = 3) -> list[dict]:
    """Iterative assumptions identification: repeated conditional reasoning hops."""
    chain: list[dict] = []
    prior = ""
    for hop in range(hops):
        prompt = ASSUMPTION_PROMPT.format(goal=plan.goal, preferences=plan.preferences_text,
                                          prior=prior, feedback=_feedback_block(memory), n=n)
        obj = common.chat_json(prompt, SYSTEM, tag="gen.assumptions", max_tokens=1400,
                               validate=lambda o: o["assumptions"])
        step = [dict(a, hop=hop + 1) for a in obj["assumptions"]][:n]
        chain += step
        prior = ("\nAssumptions established in the previous hop (go one level deeper, do not repeat):\n"
                 + "\n".join(f"- {a['assumption']} → {a.get('sub_assumption','')}" for a in step) + "\n")
    return chain


def from_assumptions(memory: Memory, plan: ResearchPlan, chain: list[dict], *, rnd: int = 0) -> Hypothesis:
    """Aggregate the assumption chain into one complete hypothesis."""
    listing = "\n".join(f"- (hop {a.get('hop')}) {a['assumption']} ⇒ {a.get('if_true_then','')} "
                        f"[sub-assumption: {a.get('sub_assumption','')}]" for a in chain)
    prompt = (f"Goal: {plan.goal}\n\nCriteria:\n{plan.preferences_text}\n\n"
              f"The following testable intermediate assumptions and sub-assumptions were identified through "
              f"conditional reasoning hops:\n{listing}\n\n"
              f"Aggregate the strongest coherent chain of these assumptions into ONE complete hypothesis. "
              f"The hypothesis must depend on the chain, not merely restate it.{_feedback_block(memory)}\n\n{HYPOTHESIS_SCHEMA}")
    obj = common.chat_json(prompt, SYSTEM, tag="gen.assumptions.aggregate", max_tokens=1800, validate=_validate)
    return _mk(memory, plan, obj, "assumptions", rnd=rnd)


# --------------------------------------------------------------------------- 4. research expansion
def research_expansion(memory: Memory, plan: ResearchPlan, *, rnd: int = 0) -> tuple[Hypothesis, list[str]]:
    """"To identify previously unexplored areas of the hypothesis space, the Generation agent reviews
    existing hypotheses and the research overview and feedback provided by the Meta-review agent"."""
    existing = "\n".join(f"- [{h.hid}] {h.title} ({h.category}): {h.statement[:200]}"
                         for h in memory.active())
    prompt = (f"Goal: {plan.goal}\n\nCriteria:\n{plan.preferences_text}\n\n"
              f"Hypotheses explored so far:\n{existing or '(none)'}\n\n"
              f"Research overview from the Meta-review agent:\n{memory.overview or '(none yet)'}"
              f"{_feedback_block(memory)}\n\n"
              f"Step 1: name 3 areas of the hypothesis space for this goal that the existing set does NOT cover.\n"
              f"Step 2: develop ONE hypothesis in the most promising unexplored area.\n\n"
              f'Return JSON: {{"unexplored": ["...", "...", "..."], "hypothesis_record": {HYPOTHESIS_SCHEMA[len("Return a JSON object with exactly these keys:"):].strip()}}}')
    obj = common.chat_json(prompt, SYSTEM, tag="gen.expansion", max_tokens=2000,
                           validate=lambda o: _validate(o["hypothesis_record"]))
    h = _mk(memory, plan, obj["hypothesis_record"], "expansion", rnd=rnd)
    return h, [str(u) for u in obj.get("unexplored", [])]
