"""Meta-review agent — Methods, "Meta-review agent".

"This agent operates on the tournament state and summarizes common patterns identified in reviews
and scientific debates in the tournament matches into a meta-review critique." The critique is
*appended to the other agents' prompts in the next iteration* — feedback propagation without any
back-propagation (Methods: "enables feedback propagation and learning without back-propagation
techniques ... which is simply appended to their prompts in the next iteration").

It also produces the research overview, the main artefact handed back to the scientist.
"""
from __future__ import annotations

import common

from .state import Hypothesis, Memory, ResearchPlan

SYSTEM = ("You are a specialised Meta-review agent inside a multi-agent AI co-scientist. You never "
          "evaluate individual proposals; you synthesise patterns across many reviews and debates.")

META_PROMPT = """You are an expert in scientific research and meta-analysis.
Synthesize a comprehensive meta-review of provided reviews pertaining to the following research goal:

Goal: {goal}

Preferences:
{preferences}

Additional instructions:
{instructions}

Provided reviews for meta-analysis:
{reviews}

Tournament debate transcripts (win/loss patterns):
{debates}

Instructions:
* Generate a structured meta-analysis report of the provided reviews.
* Focus on identifying recurring critique points and common issues raised by reviewers.
* The generated meta-analysis should provide actionable insights for researchers developing future proposals.
* Refrain from evaluating individual proposals or reviews; focus on producing a synthesized meta-analysis.

Return JSON:
{{"critique_markdown": "the structured meta-analysis, markdown with 2-4 top-level sections",
  "recurring_critiques": [{{"pattern": "short name", "count": <how many reviews raised it>, "guidance": "what future hypotheses must do"}}],
  "winning_traits": ["traits shared by hypotheses that win their matches"],
  "losing_traits": ["traits shared by hypotheses that lose"]}}"""


def synthesize(memory: Memory, plan: ResearchPlan, *, max_reviews: int = 24, max_debates: int = 6,
               instructions: str = "") -> dict:
    reviews = memory.reviews[-max_reviews:]
    rtxt = "\n\n".join(
        f"[review {i + 1}] hypothesis {r.hid} ({r.kind}) decision={r.decision} "
        f"scores={r.scores}\ncritiques: " + "; ".join(r.critiques[:6]) + f"\n{r.text[:600]}"
        for i, r in enumerate(reviews)) or "(no reviews)"
    dtxt = "\n\n".join(
        f"[match] {m.a} vs {m.b} ({m.mode}) → winner {m.winner}\n{m.rationale[:500]}"
        for m in memory.matches[-max_debates:]) or "(no tournament matches yet)"
    obj = common.chat_json(
        META_PROMPT.format(goal=plan.goal, preferences=plan.preferences_text,
                           instructions=instructions or "Be concrete; name the physical quantities involved.",
                           reviews=rtxt, debates=dtxt),
        SYSTEM, tag="meta.synthesize", max_tokens=2600,
        validate=lambda o: o["critique_markdown"] and o["recurring_critiques"] is not None)
    memory.feedback = str(obj["critique_markdown"])
    return obj


OVERVIEW_PROMPT = """You are the Meta-review agent of an AI co-scientist. Synthesize the top-ranked hypotheses into a single, coherent research overview for the scientist: a roadmap outlining the main research directions, justifying their importance and suggesting specific experiments within each.

Goal: {goal}

Preferences:
{preferences}

Top-ranked hypotheses (with Elo ratings):
{hypotheses}

Meta-review critique of the reviews so far:
{critique}

Return JSON:
{{"directions": [
   {{"name": "...",
     "rationale": "why this direction matters for the goal",
     "recent_findings": "what the retrieved literature and reviews established",
     "areas": [{{"why": "...", "what": "...", "example_experiment": "a concrete simulation or measurement, with the metric and acceptance criterion"}}],
     "hypotheses": ["the ids of the hypotheses that belong to this direction"]}}],
 "next_steps": ["..."],
 "contacts": [{{"expertise": "the kind of domain expert to consult", "why": "..."}}]}}
Give 2-4 directions."""


def research_overview(memory: Memory, plan: ResearchPlan, *, top_n: int = 6) -> dict:
    top = memory.elo.top(top_n, among=[h.hid for h in memory.active()])
    listing = "\n\n".join(f"[{hid}, Elo {r:.0f}] {memory.get(hid).title}\n{memory.get(hid).statement}\n"
                          f"Experiment: {memory.get(hid).experiment[:400]}" for hid, r in top)
    obj = common.chat_json(
        OVERVIEW_PROMPT.format(goal=plan.goal, preferences=plan.preferences_text, hypotheses=listing,
                               critique=(memory.feedback or "(none)")[:3000]),
        SYSTEM, tag="meta.overview", max_tokens=3000, validate=lambda o: o["directions"])
    memory.overview = render_overview(obj)
    return obj


def render_overview(obj: dict) -> str:
    lines = ["## Research overview\n", "**Main research directions**\n"]
    for d in obj.get("directions", []):
        lines.append(f"- **{d.get('name','')}** — {d.get('rationale','')}")
    for d in obj.get("directions", []):
        lines.append(f"\n### {d.get('name','')}")
        lines.append(f"- *Rationale:* {d.get('rationale','')}")
        if d.get("recent_findings"):
            lines.append(f"- *Recent findings:* {d['recent_findings']}")
        if d.get("hypotheses"):
            lines.append(f"- *Hypotheses:* {', '.join(map(str, d['hypotheses']))}")
        for a in d.get("areas", []) or []:
            lines.append(f"- **Why research?** {a.get('why','')}\n  - **What to research?** {a.get('what','')}"
                         f"\n  - **Example experiment:** {a.get('example_experiment','')}")
    if obj.get("next_steps"):
        lines.append("\n### Next steps\n" + "\n".join(f"- {s}" for s in obj["next_steps"]))
    if obj.get("contacts"):
        lines.append("\n### Research contacts to identify\n"
                     + "\n".join(f"- {c.get('expertise','')} — {c.get('why','')}" for c in obj["contacts"]))
    return "\n".join(lines)
