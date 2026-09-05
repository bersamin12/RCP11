"""Team queue Q_k with the optimistic-locking claim protocol (paper App. A.5).

"Concurrent reads and writes are serialized by optimistic locking on a version token: a
write that arrives stale is rejected and the agent retries against the latest version, so
each queue update is atomic and no experiment is claimed twice."

The queue is one JSON file ``{version, pending, claims, completed}``. Every mutation is a
compare-and-swap: read (data, version) -> mutate -> ``save(data, expected_version)``, which
raises ``StaleWrite`` when the on-disk version moved. A file lock makes the CAS itself atomic
across threads and processes.
"""
from __future__ import annotations

import fcntl
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class StaleWrite(Exception):
    """Raised when a write is based on an outdated version token."""


class TeamQueue:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(".lock")
        if not self.path.exists():
            self._write({"version": 0, "pending": [], "claims": {}, "completed": []})

    # ---- low level -----------------------------------------------------------------
    @contextmanager
    def _locked(self):
        with open(self.lock_path, "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)

    def _write(self, data: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, self.path)

    def load(self) -> tuple[dict, int]:
        data = json.loads(self.path.read_text())
        return data, data["version"]

    def save(self, data: dict, expected_version: int) -> int:
        """Compare-and-swap write. Returns the new version or raises StaleWrite."""
        with self._locked():
            current = json.loads(self.path.read_text())["version"]
            if current != expected_version:
                raise StaleWrite(f"queue moved from v{expected_version} to v{current}; re-read and retry")
            data["version"] = expected_version + 1
            self._write(data)
            return data["version"]

    def _cas(self, mutate, retries: int = 20) -> Any:
        """Read-mutate-save loop that retries on StaleWrite (what an agent does on rejection)."""
        for attempt in range(retries):
            data, version = self.load()
            result = mutate(data)
            try:
                self.save(data, version)
                return result
            except StaleWrite:
                time.sleep(0.005 * (attempt + 1))
        raise StaleWrite("gave up after repeated stale writes")

    # ---- queue operations -----------------------------------------------------------
    def append(self, items: list[dict]) -> int:
        def mutate(d):
            existing = {i["exp_id"] for i in d["pending"]}
            for it in items:
                if it["exp_id"] not in existing:
                    d["pending"].append(it)
            return len(d["pending"])
        return self._cas(mutate)

    def reorder(self, exp_ids_in_order: list[str]) -> None:
        def mutate(d):
            rank = {e: i for i, e in enumerate(exp_ids_in_order)}
            d["pending"].sort(key=lambda it: rank.get(it["exp_id"], len(rank)))
        self._cas(mutate)

    def claim(self, agent: str) -> dict | None:
        """Claim the first unclaimed pending experiment (Alg. 3 line 1)."""
        def mutate(d):
            for it in d["pending"]:
                if it["exp_id"] not in d["claims"]:
                    d["claims"][it["exp_id"]] = {"agent": agent, "t": time.time()}
                    return it
            return None
        return self._cas(mutate)

    def try_claim_specific(self, exp_id: str, agent: str, data: dict, version: int) -> int:
        """Single-shot claim using a caller-supplied snapshot (used to demonstrate the race)."""
        if exp_id in data["claims"]:
            raise StaleWrite(f"{exp_id} already claimed by {data['claims'][exp_id]['agent']}")
        data["claims"][exp_id] = {"agent": agent, "t": time.time()}
        return self.save(data, version)

    def release(self, exp_id: str, agent: str, outcome: str) -> None:
        """Release the claim and move the item to completed (Alg. 3 line 10)."""
        def mutate(d):
            claim = d["claims"].pop(exp_id, None)
            if claim is not None and claim["agent"] != agent:
                raise RuntimeError(f"{agent} tried to release a claim held by {claim['agent']}")
            for i, it in enumerate(d["pending"]):
                if it["exp_id"] == exp_id:
                    d["completed"].append({**d["pending"].pop(i), "outcome": outcome, "by": agent})
                    break
        self._cas(mutate)

    def snapshot(self) -> dict:
        return self.load()[0]
