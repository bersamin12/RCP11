"""Run manager: executes workflow runs in background threads, tracks progress,
surfaces gate payloads, and accepts gate answers."""

import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from langgraph.types import Command

from rcp.config import data_dir
from rcp.graph.build import build_graph
from rcp.graph.state import RCPState
from rcp.objects import ResearchTopic

NODE_ORDER = [
    "research_memory_build", "gap_mining", "hypothesis_gen", "select_hypothesis",
    "spec_compile", "approve_spec", "run_modelica", "analyze_results", "draft_report",
]
GATE_NODES = {"hypothesis_selection": "select_hypothesis", "spec_approval": "approve_spec"}


class RunManager:
    def __init__(self):
        self.graph = build_graph()
        self.pool = ThreadPoolExecutor(max_workers=4)
        self.lock = threading.Lock()
        self.runs: dict[str, dict[str, Any]] = {}
        self._load_existing()

    # ---------- lifecycle ----------

    def _run_dir(self, run_id: str):
        return data_dir() / "runs" / run_id

    def _load_existing(self) -> None:
        runs_root = data_dir() / "runs"
        if not runs_root.exists():
            return
        for d in sorted(runs_root.iterdir()):
            meta = d / "meta.json"
            if not meta.exists():
                continue
            rec = json.loads(meta.read_text())
            rec.update(
                status="done" if (d / "report.md").exists() else "stale",
                current_node=None, node_history=rec.get("node_history", []),
                gate=None, error="", version=0,
            )
            self.runs[rec["run_id"]] = rec

    def create(self, topic: str, constraints: list[str], auto: bool) -> str:
        run_id = uuid.uuid4().hex[:8]
        rec = {
            "run_id": run_id, "topic": topic, "constraints": constraints, "auto": auto,
            "status": "running", "current_node": NODE_ORDER[0], "node_history": [],
            "gate": None, "error": "", "created_at": time.time(),
            "started_at": time.time(), "ended_at": None, "version": 0,
        }
        with self.lock:
            self.runs[run_id] = rec
        d = self._run_dir(run_id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "meta.json").write_text(json.dumps(
            {k: rec[k] for k in ("run_id", "topic", "constraints", "auto", "created_at")}
        ))
        state = RCPState(
            run_id=run_id,
            topic=ResearchTopic(title=topic, constraints=constraints),
            auto=auto,
        )
        self.pool.submit(self._worker, run_id, state)
        return run_id

    def answer_gate(self, run_id: str, answer: str) -> None:
        with self.lock:
            rec = self.runs[run_id]
            if rec["status"] != "waiting_gate":
                raise ValueError(f"run {run_id} is not waiting at a gate")
            rec["gate"] = None
            rec["status"] = "running"
            rec["version"] += 1
        self.pool.submit(self._worker, run_id, Command(resume=answer))

    # ---------- worker ----------

    def _bump(self, run_id: str, **updates) -> None:
        with self.lock:
            rec = self.runs[run_id]
            rec.update(updates)
            rec["version"] += 1

    def _worker(self, run_id: str, graph_input) -> None:
        config = {"configurable": {"thread_id": run_id}}
        try:
            for update in self.graph.stream(graph_input, config, stream_mode="updates"):
                if "__interrupt__" in update:
                    payload = update["__interrupt__"][0].value
                    node = GATE_NODES.get(payload.get("gate", ""), "select_hypothesis")
                    self._bump(run_id, status="waiting_gate", gate=payload, current_node=node)
                    continue
                node = next(iter(update))
                with self.lock:
                    rec = self.runs[run_id]
                    rec["node_history"].append({"node": node, "at": time.time()})
                    done_idx = NODE_ORDER.index(node) if node in NODE_ORDER else -1
                    rec["current_node"] = (
                        NODE_ORDER[done_idx + 1] if 0 <= done_idx < len(NODE_ORDER) - 1 else node
                    )
                    rec["version"] += 1
            snapshot = self.graph.get_state(config)
            if not snapshot.next:  # finished (not paused at a gate)
                self._bump(run_id, status="done", ended_at=time.time(), current_node=None)
        except Exception as err:  # surface anything to the UI
            self._bump(run_id, status="failed", error=str(err)[:2000], ended_at=time.time())

    # ---------- queries ----------

    def list_runs(self) -> list[dict]:
        with self.lock:
            rows = [dict(r) for r in self.runs.values()]
        return sorted(rows, key=lambda r: r.get("created_at") or 0, reverse=True)

    def get(self, run_id: str) -> dict:
        with self.lock:
            if run_id not in self.runs:
                raise KeyError(run_id)
            return dict(self.runs[run_id])

    def state_snapshot(self, run_id: str) -> dict:
        """Latest checkpointed workflow state, JSON-safe (may be {} early in a run)."""
        config = {"configurable": {"thread_id": run_id}}
        try:
            values = self.graph.get_state(config).values
            if not values:
                return {}
            return RCPState.model_validate(values).model_dump(mode="json")
        except Exception:
            return {}
