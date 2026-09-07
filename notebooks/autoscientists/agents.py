"""LLM-driven roles: analyst proposals, experiment-agent code edits, discussion, consolidation.

Prompts are adapted from the reference repository's ROLE-ANALYST.md / ROLE-GPU.md /
HEARTBEAT.md (Part 2) and from paper App. A.3 / A.7. Everything the paper specifies as a
*rule* (ambition quota, diversity constraints, dead-end avoidance, one change per experiment,
roster validity) is enforced in Python after the model replies; the model only supplies the
scientific content.
"""
from __future__ import annotations

import ast
import difflib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common  # noqa: E402

from .priors import AxisPrior, numeric_parameters  # noqa: E402
from .roster import validate_roster  # noqa: E402

TASK_DESCRIPTION = (
    "Task: maximise validation accuracy of `train.py` (an sklearn MLP on the 8x8 digits dataset, "
    "~1350 training / 450 validation images). The metric is stochastic across seeds. Each "
    "experiment applies ONE change to the champion script and trains once (~1 s)."
)


# ----------------------------------------------------------------------------- analyst (Alg. 4)
ANALYST_SYSTEM = """You are an ANALYST agent in a self-organising team of AI scientists (AutoScientists).
You never run experiments yourself. Each cycle you audit the champion program and the shared
experiment log, then propose EXACTLY TWO new experiments for your team's queue.

Rules (enforced by the harness, so follow them):
1. Each proposal changes exactly ONE research axis (one top-level hyperparameter constant, or one
   clearly named structural change) of the champion script.
2. The two proposals must target DIFFERENT axes.
3. AMBITION QUOTA: at least one proposal must be BOLD: a >=10% change of a numeric parameter that
   has already been tested, OR a never-tested axis, OR a probe that would clearly confirm or falsify
   your team's hypothesis. If neither qualifies, set "exempt_reason".
4. DIVERSITY: never propose a value inside a range already recorded in the dead-end registry unless
   you say explicitly what differs; do not repeat the same (axis, direction) as the last two
   experiments.
5. POST-KEEP FOLLOW-UP: if the champion changed recently, one proposal must follow up on the property
   that made the winning change work, via a DIFFERENT mechanism.
6. Prefer axes ranked high by empirical effect size; cold (untested) axes deserve exploration.
"""

ANALYST_SCHEMA_HINT = """Return JSON:
{"proposals": [
   {"axis": "<PARAM_NAME or short structural label>", "direction": "up|down|other",
    "change": "<one sentence: exactly what to change, with the new value>",
    "rationale": "<one sentence>", "bold": true|false, "expected_delta": <float>},
   {...}
 ],
 "exempt_reason": null | "<why no bold move exists>",
 "keep_followup": null | "<which property of the last KEEP this follows up on>"}"""


def validate_proposals(obj: dict) -> None:
    """The paper's per-cycle proposal rules (App. A.7), checked in Python after the model replies.

    Exactly two proposals · different research directions · ambition quota (at least one bold
    move, else a public ``[EXEMPT]`` justification). Shared by ``analyst_propose`` and by the
    live pi analyst session so both are held to identical rules.
    """
    ps = obj["proposals"]
    assert len(ps) == 2, "need exactly two proposals"
    assert ps[0]["axis"] != ps[1]["axis"], "proposals must target different axes"
    for p in ps:
        assert p["direction"] in ("up", "down", "other")
        assert p["change"] and p["axis"]
    if not any(p.get("bold") for p in ps):
        assert obj.get("exempt_reason"), "no bold proposal and no exempt_reason"


def flag_proposals(proposals: list[dict], dead_ends: list[dict], recent_experiments: list[dict]) -> list[dict]:
    """Harness-side diversity constraints (A.7 (ii)-(iii)): annotate violating proposals in place."""
    for p in proposals:
        for d in dead_ends:
            if d["axis"] == p["axis"] and d["direction"] == p["direction"] and "differ" not in str(p.get("rationale", "")).lower():
                p["flag"] = f"same (axis,direction) as dead end value={d['value']}"
        last_two = [(e["axis"], e["direction"]) for e in recent_experiments[-2:]]
        if len(last_two) == 2 and last_two[0] == last_two[1] == (p["axis"], p["direction"]):
            p["flag"] = "third consecutive push in the same direction"
    return proposals


def analyst_propose(
    *, agent: str, team: str, hypothesis: str, champion_src: str, champion_metric: float,
    priors: list[AxisPrior], coverage: dict[str, int], dead_ends: list[dict],
    recent_experiments: list[dict], last_keep: dict | None, sigma: float,
) -> dict:
    params = numeric_parameters(champion_src)
    prior_lines = "\n".join(
        f"  {p.axis:>12} {p.direction:<5} n={p.n} mean|Δ|={'-' if p.mu is None else f'{p.mu:.4f}'} [{p.status}] keeps={p.keeps}"
        for p in priors
    ) or "  (no experiments yet)"
    untested = [k for k, v in coverage.items() if v == 0]
    dead = "\n".join(f"  {d['axis']} {d['direction']} value={d['value']} Δ={d['delta']:+.4f}: {d['reason']}" for d in dead_ends[-12:]) or "  (none)"
    recent = "\n".join(
        f"  {e['exp_id']} {e['axis']} {e['direction']} → {e['outcome']} Δ={e['delta']:+.4f} ({e.get('change', '')})"
        for e in recent_experiments[-8:]
    ) or "  (none)"
    prompt = f"""{TASK_DESCRIPTION}

You are {agent} on team "{team}". Team hypothesis: {hypothesis}
Current champion metric: {champion_metric:.4f}; noise floor σ = {sigma:.4f} (a Δ must exceed 2σ={2*sigma:.4f} to count clearly).

Champion hyperparameters (top-level constants): {json.dumps(params)}
Never-tested parameters (coverage audit): {untested or 'none'}

Empirical axis priors (mean |Δ| per axis/direction, eq. 3):
{prior_lines}

Dead-end registry (do not re-propose inside these ranges):
{dead}

Most recent experiments:
{recent}

Last accepted improvement (KEEP): {json.dumps(last_keep) if last_keep else 'none yet'}

Champion script:
```python
{champion_src}
```

{ANALYST_SCHEMA_HINT}"""

    out = common.chat_json(prompt, ANALYST_SYSTEM, validate=validate_proposals, tag="analyst", temperature=0.8, max_tokens=1500)
    # Harness-side enforcement of the diversity constraints
    flag_proposals(out["proposals"], dead_ends, recent_experiments)
    return out


# ----------------------------------------------------------------------------- experiment agent (Alg. 3)
EXPERIMENT_SYSTEM = """You are an EXPERIMENT agent. You receive the champion training script and ONE
proposed change. Apply exactly that change and nothing else: keep every other line identical
(including comments and docstrings), keep the CLI (--seed) and the JSON output line, and keep
the script self-contained.
Output the COMPLETE modified script as a single ```python code block and nothing else."""


def experiment_apply(champion_src: str, proposal: dict, max_changed_lines: int = 12) -> tuple[str, str]:
    """Ask the model to apply the proposal; return (new_source, unified_diff). Enforces 'one change'."""
    prompt = f"""Proposal to apply — axis: {proposal['axis']}, direction: {proposal['direction']}
Change: {proposal['change']}

Champion script:
```python
{champion_src}
```"""
    for attempt in range(3):
        raw = common.chat(prompt, EXPERIMENT_SYSTEM, tag="experiment", temperature=0.2, max_tokens=2048)
        src = common.extract_code_block(raw)
        if src is None:
            prompt += "\n\nYour reply had no ```python block. Output the complete script in one code block."
            continue
        try:
            ast.parse(src)
        except SyntaxError as exc:
            prompt += f"\n\nYour script had a syntax error ({exc}). Fix it and output the complete script."
            continue
        diff = list(difflib.unified_diff(champion_src.splitlines(), src.splitlines(), "champion", "candidate", lineterm="", n=0))
        changed = [l for l in diff if l[:1] in "+-" and not l.startswith(("+++", "---"))]
        if not changed:
            prompt += "\n\nYour script was identical to the champion. Apply the change."
            continue
        if len(changed) > max_changed_lines:
            prompt += f"\n\nYou changed {len(changed)} lines; apply ONLY the single proposed change (a few lines at most)."
            continue
        return src, "\n".join(diff)
    raise RuntimeError("experiment agent failed to produce a valid one-change candidate")


# ----------------------------------------------------------------------------- discussion (Alg. 2)
DISCUSSION_SYSTEM = """You are an agent in a self-organising team of AI scientists. A discussion has
been opened to (re)organise the crew into teams, each pursuing ONE research direction (axis
family) with a falsifiable hypothesis. Read the task, the champion and the prior posts, then post:
1. candidate research directions (2-4), each with a hypothesis and the axes it covers;
2. a ranking of ALL directions proposed so far (yours and others') by expected effect, with reasons;
3. a short critique of gaps or redundancy in earlier posts (empty if you are first);
4. your vote: "MORE" if the decomposition still needs discussion, "DONE" if a roster can be written.
"""


def discuss(*, agent: str, role: str, champion_src: str, champion_metric: float, prior_posts: list[dict],
            experiments_summary: str, trigger_reason: str, round_no: int = 1, max_rounds: int = 3) -> dict:
    params = numeric_parameters(champion_src)
    posts = "\n\n".join(f"--- {p['author']} ({p['tag']}) ---\n{p['body']}" for p in prior_posts) or "(you are first)"
    round_rule = (f"This is discussion round {round_no} of at most {max_rounds}. "
                  + ("Vote MORE only if a genuine gap remains; otherwise vote DONE." if round_no < max_rounds
                     else "This is the FINAL round: you must vote DONE."))
    prompt = f"""{TASK_DESCRIPTION}
You are {agent} ({role}). Discussion trigger: {trigger_reason}
{round_rule}
Champion metric {champion_metric:.4f}; hyperparameters {json.dumps(params)}.
Experiment history summary: {experiments_summary}

Prior posts in this thread:
{posts}

Return JSON: {{"directions": [{{"name": "...", "hypothesis": "...", "axes": ["PARAM", ...], "expected_effect": "high|medium|low"}}],
 "ranking": ["<direction name best first>", ...], "critique": "...", "vote": "MORE|DONE"}}"""

    def validate(o):
        vote = str(o.get("vote", "")).strip().strip(".!").upper()
        o["vote"] = "DONE" if vote.startswith("DONE") else ("MORE" if vote.startswith("MORE") else vote)
        assert o["vote"] in ("MORE", "DONE"), f"vote must be MORE or DONE, got {o.get('vote')!r}"
        assert o.get("directions"), "directions must be a non-empty list"
        if not o.get("ranking"):
            o["ranking"] = [d.get("name", str(i)) for i, d in enumerate(o["directions"])]
        o.setdefault("critique", "")

    out = common.chat_json(prompt, DISCUSSION_SYSTEM, validate=validate, tag="discussion", temperature=0.8, retries=3, max_tokens=1600)
    if round_no >= max_rounds:
        out["vote"] = "DONE"   # protocol rule enforced by the harness
    return out


CONSOLIDATE_SYSTEM = """You are the consolidating ANALYST. Turn the discussion below into a team roster.
Constraints: every experiment agent and every analyst appears in exactly one team; each team has
>=1 experiment agent, a research axis (parameter family), a one-sentence hypothesis, and a
falsification criterion. Form 2-3 teams pursuing DIFFERENT directions (never a single team); merge near-duplicate directions."""


def consolidate_roster(*, agent: str, posts: list[dict], experiment_agents: list[str], analysts: list[str]) -> dict:
    thread = "\n\n".join(f"--- {p['author']} ---\n{p['body']}" for p in posts)
    prompt = f"""Experiment agents: {experiment_agents}
Analysts: {analysts}

Discussion thread:
{thread}

Return JSON: {{"teams": {{"<team-name>": {{"axis": "<parameter family / direction>", "hypothesis": "...",
 "falsification": "...", "members": ["agent", ...]}}}}}}"""

    def repair(teams: dict) -> dict:
        """Deterministic clean-up of an LLM roster: drop empty teams, place every agent exactly once,
        give every team >=1 experiment agent (merging teams that cannot get one)."""
        crew = experiment_agents + analysts
        teams = {k: {**v, "members": [m for m in v.get("members", []) if m in crew]} for k, v in teams.items()}
        seen: set[str] = set()
        for t in teams.values():                       # first occurrence wins
            t["members"] = [m for m in t["members"] if not (m in seen or seen.add(m))]
        teams = {k: v for k, v in teams.items() if v["members"]}
        if not teams:
            return teams
        for a in crew:                                 # unassigned agents -> smallest team
            if a not in seen:
                min(teams.values(), key=lambda t: len(t["members"]))["members"].append(a)
        for name in list(teams):                       # every team needs an experiment agent
            if not any(m in experiment_agents for m in teams[name]["members"]):
                donors = [t for k, t in teams.items() if k != name and sum(m in experiment_agents for m in t["members"]) >= 2]
                if donors:
                    donor = max(donors, key=lambda t: len(t["members"]))
                    mover = next(m for m in donor["members"] if m in experiment_agents)
                    donor["members"].remove(mover); teams[name]["members"].append(mover)
                else:                                  # merge into the largest other team
                    other = max((k for k in teams if k != name), key=lambda k: len(teams[k]["members"]), default=None)
                    if other is None:
                        break
                    teams[other]["members"] += teams[name]["members"]; teams.pop(name)
        return teams

    def validate(o):
        o["teams"] = repair(o["teams"])
        problems = validate_roster(o["teams"], experiment_agents, analysts)
        if len(experiment_agents) >= 2 and len(o["teams"]) < 2:
            problems.append("with >=2 experiment agents the roster must have at least 2 teams (parallel directions)")
        assert not problems, "; ".join(problems)

    return common.chat_json(prompt, CONSOLIDATE_SYSTEM, validate=validate, tag="consolidate", temperature=0.3, retries=3, max_tokens=1400)


# ----------------------------------------------------------------------------- post-KEEP induction (A.7)
def induce_keep_property(*, diff: str, delta: float, champion_src: str) -> dict:
    prompt = f"""A change to the training script was just accepted as the new champion (Δ={delta:+.4f}).
Diff:
{diff}

Answer the two post-KEEP questions from the AutoScientists analyst protocol:
1. Which property of the successful change made it work?
2. What other untried changes share that property (via a different mechanism)?
Return JSON: {{"property": "...", "followups": [{{"axis": "...", "direction": "up|down|other", "change": "..."}}]}}"""
    return common.chat_json(prompt, tag="induction", temperature=0.5, max_tokens=900)


# --------------------------------------------------------------- live coding-agent role files (Alg. 1/3, A.4)
# In the paper the backend is a Claude Code session: "each invocation is a single LLM session that
# wakes up, executes one heartbeat, and exits" (App. A.1), reading a role-specific heartbeat file as
# its system prompt and the shared state S from disk with its own file tools. The two constants below
# are that role text, adapted to the notebook's toy task, and are passed to `common.run_pi` as
# `system_prompt` so the pi session plays exactly one heartbeat of the corresponding role.

PI_EXPERIMENT_ROLE = """You are an EXPERIMENT AGENT in the AutoScientists crew (heartbeat = one session, then exit).
This is your ROLE file. Follow it literally; you have file and shell tools in the shared-state directory.

Your single heartbeat (Algorithm 3):
 1. Read `claim.json` — the ONE experiment you have already claimed from your team queue Q_k.
 2. Read `train.py` — your working copy of the champion program p*.
 3. Apply EXACTLY the one change described in claim.json["change"] to `train.py` with the edit tool.
    Change nothing else: keep every other line, the --seed CLI, and the final JSON output line intact.
 4. Train the candidate once: run `python train.py --seed <seed from claim.json>` with the bash tool.
    The script prints one JSON line ending with {"metric": <float>, ...}.
 5. Write that metric to `result.json` as {"metric": <float>, "seed": <int>, "change": "<one line>"}.
 6. Stop. Do NOT touch any other file (the champion record, the logs, the queue, the registries are
    written by the orchestrator, not by you), do NOT gate or promote anything yourself, and do NOT
    run more than one training command unless it failed.

The noise-aware promotion gate (Δ vs Mσ, App. A.6), the experiment log L, the [RESULT] post and the
dead-end registry are handled by the harness after you exit."""

PI_ANALYST_ROLE = """You are an ANALYST agent in the AutoScientists crew (heartbeat = one session, then exit).
This is your ROLE file. You have read-only tools: you may run shell commands to inspect files and read
files, but you must not modify anything.

Your single heartbeat follows the list-decide-read protocol (App. A.4) — do the three steps in order:
 1. LIST: retrieve only lightweight metadata for the items in the shared state S first, e.g.
    `ls -la`, `find . -type f -printf '%p %s %TY-%Tm-%Td %TH:%TM\\n'` — paths, sizes, timestamps.
    Do not read file contents in this step.
 2. DECIDE: state briefly which items are relevant to a proposal cycle and read only those
    (typically the champion record, the experiment log, the team queue, the dead-end registry).
 3. PROPOSE: write NOTHING to disk. Read at most six items in total, and as soon as the reads have
    returned, emit the JSON object below as your ENTIRE final message (Algorithm 4 line 6). Never end a
    turn with a plan, a promise to read more, or prose: the heartbeat is over once the JSON is out.

Proposal rules (the harness re-checks all of them; violating them wastes the cycle):
 * EXACTLY two proposals, each changing exactly ONE top-level numeric hyperparameter of the champion;
 * the two proposals must target DIFFERENT axes;
 * AMBITION QUOTA: at least one proposal must be bold (>=10% change of an already-tested parameter,
   or a never-tested axis, or a probe that clearly confirms/falsifies the team hypothesis);
   if neither qualifies, set "exempt_reason" to a public justification;
 * DIVERSITY: nothing inside a range already recorded in the dead-end registry unless you say what
   differs, and no third consecutive push of the same (axis, direction).

Final message format (JSON only, no prose after it):
{"read_files": ["<paths you decided to read>"],
 "proposals": [{"axis": "PARAM", "direction": "up|down|other", "change": "...", "rationale": "...",
                "bold": true|false, "expected_delta": 0.0}, {...}],
 "exempt_reason": null | "...", "keep_followup": null | "..."}"""


def pi_experiment_prompt(*, agent: str, team: str, hypothesis: str, seed: int, python: str = "python") -> str:
    """The per-invocation user message for a live experiment-agent heartbeat (paper Alg. 3)."""
    return f"""{TASK_DESCRIPTION}

You are {agent} on team "{team}" (hypothesis: {hypothesis}). The current directory is the shared state S.
Execute one heartbeat now, exactly as your role file describes: read claim.json, read train.py, apply the
single claimed change, run `{python} train.py --seed {seed}` (use exactly this interpreter), write
result.json, then stop and report the metric in one sentence."""


def pi_analyst_prompt(*, agent: str, team: str, hypothesis: str, sigma: float) -> str:
    """The per-invocation user message for a live analyst heartbeat (paper Alg. 1 line 1/9, Alg. 4)."""
    return f"""{TASK_DESCRIPTION}

You are {agent} on team "{team}" (hypothesis: {hypothesis}). The current directory is the shared state S of a
run that already happened: champion.json / champion/ (the champion p*), logs/experiments.jsonl (the log L),
logs/forum.jsonl (the forum F), teams/<team>/queue.json and teams/<team>/dead_ends.json (team-local state),
knowledge/noise_pairs.json (noise-floor calibration; current σ = {sigma:.4f}, so a Δ must exceed 2σ = {2 * sigma:.4f}
to be clearly above noise).

Execute one heartbeat now: list the metadata first, decide what to read, read only that, and end with the
JSON object of two proposals. Write nothing."""
