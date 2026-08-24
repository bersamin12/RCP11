"""Deterministic claim/evidence consistency checks."""

from rcp.objects import (
    ClaimBundle,
    ExperimentPlan,
    ExperimentResultSet,
    PaperCard,
    ReviewBundle,
    ReviewIssue,
)


def review_claims(
    claims: ClaimBundle,
    plan: ExperimentPlan | None,
    results: ExperimentResultSet | None,
    papers: list[PaperCard],
    annotations: list | None = None,
) -> ReviewBundle:
    issues: list[ReviewIssue] = []
    # A human dispute is surfaced as a warning and travels into report validation
    # and the export, but it never decides validity. A person's assertion must not
    # be able to manufacture a passing study, nor to erase a failing one; only the
    # deterministic checks below do that.
    for annotation in annotations or []:
        if getattr(annotation, "kind", "") == "flag" and not getattr(annotation, "resolved", False):
            issues.append(ReviewIssue(
                severity="warning",
                code=f"human-dispute:{annotation.evidence_id}",
                message=f"{annotation.author} disputed {annotation.evidence_id}: {annotation.body[:160]}",
            ))
    case_ids = {case.id for case in plan.cases} if plan else set()
    comparison_ids = {comparison.id for comparison in results.comparisons} if results else set()
    paper_ids = {paper.id for paper in papers}
    requires_comparisons = bool(comparison_ids)
    if results and results.quality_report:
        has_failed_check = any(
            check.status == "failed" for check in results.quality_report.checks
        )
        if not results.quality_report.valid and not has_failed_check:
            issues.append(ReviewIssue(
                severity="error", code="study-quality:invalid-report",
                message="The study-quality report is invalid without a passing check set.",
            ))
        for check in results.quality_report.checks:
            if check.status == "failed":
                issues.append(ReviewIssue(
                    severity="error", code=f"study-quality:{check.id}", message=check.message,
                ))
            elif check.status == "warning":
                issues.append(ReviewIssue(
                    severity="warning", code=f"study-quality:{check.id}", message=check.message,
                ))
    for index, claim in enumerate(claims.claims):
        unknown_comparisons = sorted(set(claim.comparison_ids) - comparison_ids)
        unknown_cases = sorted(set(claim.case_ids) - case_ids)
        unknown_papers = sorted(set(claim.paper_ids) - paper_ids)
        if unknown_comparisons:
            issues.append(ReviewIssue(
                severity="error", code="unknown-comparison",
                message=f"Unknown comparison IDs: {', '.join(unknown_comparisons)}", claim_index=index,
            ))
        if unknown_cases:
            issues.append(ReviewIssue(
                severity="error", code="unknown-case",
                message=f"Unknown case IDs: {', '.join(unknown_cases)}", claim_index=index,
            ))
        if unknown_papers:
            issues.append(ReviewIssue(
                severity="error", code="unknown-paper",
                message=f"Unknown paper IDs: {', '.join(unknown_papers)}", claim_index=index,
            ))
        if requires_comparisons and not claim.comparison_ids:
            issues.append(ReviewIssue(
                severity="error", code="missing-comparison",
                message="Comparative claims require at least one structured comparison.", claim_index=index,
            ))
        if requires_comparisons and not claim.case_ids:
            issues.append(ReviewIssue(
                severity="error", code="missing-case",
                message="Comparative claims require their source cases.", claim_index=index,
            ))
        if requires_comparisons and papers and not claim.paper_ids:
            issues.append(ReviewIssue(
                severity="error", code="missing-literature-context",
                message="Generated claims require supporting literature context.", claim_index=index,
            ))
        if not claim.evidence_ids and not claim.comparison_ids:
            issues.append(ReviewIssue(
                severity="error", code="missing-evidence",
                message="Claim has no structured evidence.", claim_index=index,
            ))
    return ReviewBundle(valid=not any(issue.severity == "error" for issue in issues), issues=issues)
