"""Deterministic, decision-oriented summaries for run-detail consumers."""

from __future__ import annotations

import statistics
from typing import Any

from rcp.objects import ExperimentResultSet, MetricOutcome, RunOutcome


def _next_action(record: dict[str, Any]) -> str:
    status = record.get("status")
    review = record.get("review") or {}
    if review.get("decision") == "accept":
        return "This evidence package has been accepted; no further cycle is required."
    if review.get("successor_run_id"):
        return f"Continue the research in successor cycle {review['successor_run_id']}."
    if status == "waiting_gate":
        return "Complete the pending human decision to continue the research cycle."
    if status in {"running", "resuming"}:
        return "Monitor the active stage; no researcher action is required yet."
    if status == "failed":
        return (
            "Retry from the latest checkpoint after reviewing the failure."
            if record.get("retryable") else
            "Review the failure and start a revised run; this checkpoint cannot be resumed safely."
        )
    if status == "done":
        return "Review the supported claims, limitations, and evidence package."
    return "Review the available run artifacts."


def derive_run_outcome(record: dict[str, Any], state: dict[str, Any]) -> RunOutcome:
    """Summarize only persisted claims, quality checks, and numeric comparisons."""
    claim_bundle = state.get("claim_bundle") or {}
    claims = claim_bundle.get("claims") or []
    results_data = state.get("experiment_results")
    results = ExperimentResultSet.model_validate(results_data) if results_data else None

    if claims:
        primary = str(claims[0].get("statement") or "Reviewed claims are available.")
    elif record.get("status") == "failed":
        primary = "The research cycle stopped before a reviewed finding was produced."
    elif record.get("status") == "done":
        primary = "The cycle completed, but no supported comparative claim was produced."
    else:
        primary = "A reviewed finding will appear after analysis and evidence review."

    qualifications = list(dict.fromkeys([
        *(str(item) for item in claim_bundle.get("credibility_warnings", []) if item),
        *(str(item) for item in (results.warnings if results else []) if item),
    ]))
    quality_status = "pending"
    quality = results.quality_report if results else None
    if quality:
        if not quality.valid:
            quality_status = "failed"
        elif qualifications or any(check.status == "warning" for check in quality.checks):
            quality_status = "qualified"
        else:
            quality_status = "passed"

    by_metric: dict[str, list] = {}
    for comparison in results.comparisons if results else []:
        by_metric.setdefault(comparison.metric, []).append(comparison)
    metric_outcomes = []
    for metric, comparisons in by_metric.items():
        deltas = [item.percent_delta for item in comparisons if item.percent_delta is not None]
        metric_outcomes.append(MetricOutcome(
            metric=metric,
            wins=sum(item.candidate_better is True for item in comparisons),
            losses=sum(item.candidate_better is False for item in comparisons),
            ties=sum(item.candidate_better is None for item in comparisons),
            median_percent_delta=statistics.median(deltas) if deltas else None,
            direction=comparisons[0].direction,
            unit=comparisons[0].unit,
        ))

    started = record.get("started_at")
    ended = record.get("ended_at")
    elapsed = max(0.0, float(ended) - float(started)) if started and ended else None
    return RunOutcome(
        primary_finding=primary,
        quality_status=quality_status,
        qualifications=qualifications,
        metrics=metric_outcomes,
        next_action=_next_action(record),
        elapsed_seconds=elapsed,
        token_usage=record.get("token_usage") or {},
    )
