"""Shared state S (paper Sec. 3.2 "Shared State", App. A / A.4 / A.5).

The paper's S has four layers: champion p*, experiment log L, forum F, and team-local state
(queues Q_k, dead-end registries D_k, hypothesis docs). The reference implementation keeps
these as files on a coordination server; here they are plain files under one directory so
every agent (thread) can read and write them. Access follows the paper's *list-decide-read*
protocol (A.4): ``list_items()`` returns lightweight metadata only, ``read()`` fetches content.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .queue import TeamQueue

FORUM_TAGS = (
    "[PROPOSAL]", "[RESULT]", "[NEAR-MISS]", "[AUDIT]", "[DISCUSSION]",
    "[DISCUSSION-TRIGGER]", "[DISCUSS-MORE]", "[DISCUSS-DONE]", "[TEAM-REFORMED]",
    "[HYPOTHESIS-FALSIFIED]", "[EXEMPT]", "[KEEP]",
)


def code_hash(src: str) -> str:
    return hashlib.sha1(src.encode()).hexdigest()[:10]


@dataclass
class Experiment:
    """One row of the experiment log L (schema after the reference repo's LOGGING.md)."""

    exp_id: str
    team: str
    agent: str
    axis: str            # research direction / parameter changed, e.g. "LR"
    direction: str       # "up" | "down" | "other"
    change: str          # human-readable diff description
    parent_metric: float
    metric: float
    delta: float
    outcome: str         # KEEP | DISCARD | NEAR-MISS | INVALID
    seed: int
    cycle: int
    second_seed_metric: float | None = None
    parent_hash: str = ""
    candidate_hash: str = ""
    proposal_post: str | None = None
    timestamp: float = field(default_factory=time.time)


class SharedState:
    def __init__(self, root: str | Path, champion_src: str | None = None, reset: bool = False):
        self.root = Path(root)
        if reset and self.root.exists():
            shutil.rmtree(self.root)
        for d in ("champion", "teams", "knowledge", "logs"):
            (self.root / d).mkdir(parents=True, exist_ok=True)
        if champion_src is not None and not (self.root / "champion.json").exists():
            self._write_json("champion.json", {
                "version": 0, "metric": None, "seed": None, "code_hash": code_hash(champion_src),
                "updated_by": "bootstrap", "history": [],
            })
            (self.root / "champion" / "train.py").write_text(champion_src)
        for name in ("experiments.jsonl", "forum.jsonl"):
            (self.root / "logs" / name).touch()
        if not (self.root / "teams" / "roster.json").exists():
            self._write_json("teams/roster.json", {"version": 0, "phase": "planning", "teams": {}})
        if not (self.root / "knowledge" / "noise_pairs.json").exists():
            self._write_json("knowledge/noise_pairs.json", {"pairs": [], "locked_sigma": None})

    # ------------------------------------------------------------------ raw file helpers
    def _path(self, rel: str) -> Path:
        return self.root / rel

    def _write_json(self, rel: str, obj: Any) -> None:
        p = self._path(rel)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(obj, indent=2, default=str))
        os.replace(tmp, p)

    def _read_json(self, rel: str) -> Any:
        return json.loads(self._path(rel).read_text())

    def _append_jsonl(self, rel: str, obj: dict) -> None:
        with self._path(rel).open("a") as f:
            f.write(json.dumps(obj, default=str) + "\n")

    def _read_jsonl(self, rel: str) -> list[dict]:
        p = self._path(rel)
        if not p.exists():
            return []
        return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]

    # ------------------------------------------------------------------ list-decide-read (A.4)
    def list_items(self) -> list[dict]:
        """Metadata only: path, size, mtime, and (for JSON files) version/author when present."""
        items = []
        for p in sorted(self.root.rglob("*")):
            if p.is_dir() or p.suffix == ".tmp":
                continue
            meta = {"path": str(p.relative_to(self.root)), "bytes": p.stat().st_size,
                    "mtime": round(p.stat().st_mtime, 1)}
            if p.suffix == ".json":
                try:
                    obj = json.loads(p.read_text())
                    for k in ("version", "updated_by", "author"):
                        if isinstance(obj, dict) and k in obj:
                            meta[k] = obj[k]
                except json.JSONDecodeError:
                    pass
            items.append(meta)
        return items

    def read(self, rel: str) -> Any:
        p = self._path(rel)
        if p.suffix == ".json":
            return self._read_json(rel)
        if p.suffix == ".jsonl":
            return self._read_jsonl(rel)
        return p.read_text()

    # ------------------------------------------------------------------ champion p*
    @property
    def champion(self) -> dict:
        return self._read_json("champion.json")

    @property
    def champion_src(self) -> str:
        return (self.root / "champion" / "train.py").read_text()

    def set_baseline(self, metric: float, seed: int) -> None:
        c = self.champion
        c.update(metric=metric, seed=seed, updated_by="baseline")
        self._write_json("champion.json", c)

    def promote(self, src: str, metric: float, seed: int, agent: str, exp_id: str) -> dict:
        c = self.champion
        c["history"].append({"version": c["version"], "metric": c["metric"], "code_hash": c["code_hash"],
                             "exp_id": exp_id, "agent": agent, "t": time.time()})
        c.update(version=c["version"] + 1, metric=metric, seed=seed, code_hash=code_hash(src), updated_by=agent)
        (self.root / "champion" / f"train_v{c['version']}.py").write_text(src)
        (self.root / "champion" / "train.py").write_text(src)
        self._write_json("champion.json", c)
        return c

    # ------------------------------------------------------------------ experiment log L
    def log_experiment(self, exp: Experiment) -> None:
        self._append_jsonl("logs/experiments.jsonl", asdict(exp))

    def experiments(self) -> list[dict]:
        return self._read_jsonl("logs/experiments.jsonl")

    # ------------------------------------------------------------------ forum F
    def post(self, tag: str, author: str, body: str, thread: str | None = None, **meta) -> str:
        assert tag in FORUM_TAGS, f"unknown forum tag {tag}"
        post_id = f"p{uuid.uuid4().hex[:8]}"
        self._append_jsonl("logs/forum.jsonl", {
            "id": post_id, "tag": tag, "author": author, "body": body, "thread": thread,
            "meta": meta, "t": time.time(),
        })
        return post_id

    def forum(self, tag: str | None = None, thread: str | None = None, last: int | None = None) -> list[dict]:
        posts = self._read_jsonl("logs/forum.jsonl")
        if tag:
            posts = [p for p in posts if p["tag"] == tag]
        if thread:
            posts = [p for p in posts if p["thread"] == thread or p["id"] == thread]
        return posts[-last:] if last else posts

    # ------------------------------------------------------------------ roster R + teams
    @property
    def roster(self) -> dict:
        return self._read_json("teams/roster.json")

    def write_roster(self, teams: dict[str, dict], author: str, phase: str = "execute") -> dict:
        r = self.roster
        r.update(version=r["version"] + 1, phase=phase, teams=teams, updated_by=author)
        self._write_json("teams/roster.json", r)
        for team in teams:
            (self.root / "teams" / team).mkdir(exist_ok=True)
            self.queue(team)  # creates queue.json if missing
            de = self.root / "teams" / team / "dead_ends.json"
            if not de.exists():
                self._write_json(f"teams/{team}/dead_ends.json", {"entries": []})
        return r

    def team_of(self, agent: str) -> str | None:
        for name, t in self.roster["teams"].items():
            if agent in t.get("members", []):
                return name
        return None

    def queue(self, team: str) -> TeamQueue:
        (self.root / "teams" / team).mkdir(parents=True, exist_ok=True)
        return TeamQueue(self.root / "teams" / team / "queue.json")

    def dead_ends(self, team: str) -> list[dict]:
        p = f"teams/{team}/dead_ends.json"
        return self._read_json(p)["entries"] if self._path(p).exists() else []

    def add_dead_end(self, team: str, axis: str, direction: str, value: Any, delta: float, reason: str) -> None:
        p = f"teams/{team}/dead_ends.json"
        d = self._read_json(p) if self._path(p).exists() else {"entries": []}
        d["entries"].append({"axis": axis, "direction": direction, "value": value, "delta": delta,
                             "reason": reason, "t": time.time()})
        self._write_json(p, d)

    def all_dead_ends(self) -> list[dict]:
        out = []
        for team in self.roster["teams"]:
            out += [{"team": team, **e} for e in self.dead_ends(team)]
        return out

    # ------------------------------------------------------------------ noise-floor pairs (A.6)
    def noise_pairs(self) -> dict:
        return self._read_json("knowledge/noise_pairs.json")

    def add_noise_pair(self, l1: float, l2: float, chash: str) -> None:
        d = self.noise_pairs()
        d["pairs"].append({"l1": l1, "l2": l2, "code_hash": chash, "t": time.time()})
        self._write_json("knowledge/noise_pairs.json", d)

    def lock_sigma(self, sigma: float) -> None:
        d = self.noise_pairs()
        d["locked_sigma"] = sigma
        self._write_json("knowledge/noise_pairs.json", d)
