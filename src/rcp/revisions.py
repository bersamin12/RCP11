"""Immutable successor-run preparation for protocol-only reanalysis."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from rcp.config import data_dir, get_settings
from rcp.objects import ExperimentPlan, ExperimentResultSet, ProtocolChanges
from rcp.simulation.batch import run_plan, validate_plan
from rcp.simulation.collector import file_fingerprint


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2))
    temporary.replace(path)


def prepare_reanalysis_successor(
    parent_run_id: str,
    child_run_id: str,
    parent_plan: ExperimentPlan,
    parent_results: ExperimentResultSet,
    changes: ProtocolChanges,
    iteration: int,
) -> tuple[ExperimentPlan, ExperimentResultSet]:
    """Copy verified raw inputs and reanalyse them without invoking a simulator."""
    if parent_results.status != "ok" or not parent_results.cases:
        raise ValueError("reanalysis requires a complete successful result set")
    updates = changes.model_dump(exclude_none=True)
    if not updates:
        raise ValueError("reanalysis requires at least one protocol change")
    changed = {
        name: value for name, value in updates.items()
        if getattr(parent_plan.analysis_protocol, name) != value
    }
    if not changed:
        raise ValueError("the proposed protocol values are unchanged")

    plan = parent_plan.model_copy(deep=True)
    plan.id = f"plan-{child_run_id}-reanalysis"
    protocol = plan.analysis_protocol.model_copy(update=changed)
    protocol.id = f"{parent_plan.analysis_protocol.id}-r{iteration}"
    protocol.version = f"{parent_plan.analysis_protocol.version}.r{iteration}"
    plan.analysis_protocol = protocol
    plan.validation_issues = validate_plan(plan, max_cases=get_settings().rcp_max_batch_cases)
    if plan.validation_issues:
        raise ValueError("invalid revised analysis protocol: " + "; ".join(plan.validation_issues))

    child_sim = data_dir() / "runs" / child_run_id / "sim"
    copied_cases = []
    for result in parent_results.cases:
        if result.status != "ok" or result.result_file_integrity != "verified" or not result.result_file_sha256:
            raise ValueError(f"case {result.case_id or result.spec_id} has no verified raw series")
        source = Path(result.result_file or "")
        if not source.exists():
            raise ValueError(f"case {result.case_id or result.spec_id} raw series is missing")
        observed_sha, observed_bytes = file_fingerprint(source)
        if observed_sha != result.result_file_sha256:
            raise ValueError(f"case {result.case_id or result.spec_id} raw series failed SHA-256 verification")
        case_id = result.case_id or result.spec_id
        destination = child_sim / "imported_raw" / case_id / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied_sha, copied_bytes = file_fingerprint(destination)
        if copied_sha != observed_sha or copied_bytes != observed_bytes:
            raise ValueError(f"case {case_id} raw-series copy failed integrity verification")
        copied_cases.append(result.model_copy(update={
            "workdir": str(destination.parent), "result_file": str(destination),
            "observed_result_file_sha256": copied_sha, "result_file_bytes": copied_bytes,
            "result_file_integrity": "verified",
        }))

    seeded = parent_results.model_copy(deep=True, update={"plan_id": plan.id, "cases": copied_cases})
    _atomic_json(child_sim / "experiment_results.json", seeded.model_dump(mode="json"))
    _atomic_json(data_dir() / "runs" / child_run_id / "experiment_plan.json", plan.model_dump(mode="json"))

    def simulation_forbidden(*_args, **_kwargs):
        raise AssertionError("protocol-only reanalysis attempted to invoke Modelica")

    reanalysed = run_plan(plan, child_sim, runner=simulation_forbidden)
    if reanalysed.raw_dataset_sha256 != parent_results.raw_dataset_sha256:
        raise ValueError("reanalysis changed the raw dataset identity")
    return plan, reanalysed
