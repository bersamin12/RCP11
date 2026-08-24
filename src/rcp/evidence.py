"""Evidence & provenance: hashing, sealed specs, claim consistency (PRD X.3, M6.3)."""

import hashlib
import json
from pathlib import Path

from rcp.objects import Claim, ExperimentSpec


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def spec_digest(spec: ExperimentSpec) -> str:
    """Deterministic, order-independent hash of an ExperimentSpec (the sealed spec)."""
    payload = {
        "id": spec.id,
        "hypothesis_id": spec.hypothesis_id,
        "model_name": spec.model_name,
        "parameters": dict(sorted(spec.parameters.items())),
        "outputs": sorted(spec.outputs),
        "stop_time": spec.stop_time,
        "intervals": spec.intervals,
    }
    return sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def check_claims(claims: list[Claim], metrics: dict[str, float]) -> list[str]:
    """Consistency check (PRD M6.3): every claim must cite metric keys that exist in the
    computed metrics. Returns human-readable violations (empty = consistent)."""
    violations: list[str] = []
    available = set(metrics)
    for i, claim in enumerate(claims):
        if not claim.metric_keys:
            violations.append(f"claim {i + 1} cites no metrics — not traceable to results")
            continue
        for key in claim.metric_keys:
            if key not in available:
                violations.append(
                    f"claim {i + 1} cites missing metric '{key}' — available: {sorted(available)}"
                )
    return violations
