import { AnnotationComposer, AnnotationThread } from "./Annotations";
import { Button, Dialog } from "./UI";
import type { AnnotationDraft, ClaimBundle, EvidenceAnnotation, ExperimentPlan, ExperimentResultSet, PaperCard, ResearchSynthesis } from "../types";

interface EvidenceInspectorProps {
  evidenceId: string;
  results: ExperimentResultSet | null;
  plan: ExperimentPlan | null;
  papers: PaperCard[];
  claims: ClaimBundle | null;
  synthesis?: ResearchSynthesis | null;
  onSelectCase?: (caseId: string) => void;
  onNavigate?: (evidenceId: string) => void;
  onClose: () => void;
  annotations?: EvidenceAnnotation[];
  onAnnotate?: (draft: AnnotationDraft) => Promise<void>;
  onResolveAnnotation?: (id: string) => void;
  onOpenPdf?: (paperId: string, page?: number) => void;
  annotationBusy?: boolean;
}

export function EvidenceInspector({ evidenceId, results, plan, papers, claims, synthesis, onSelectCase, onNavigate, onClose, annotations, onAnnotate, onResolveAnnotation, onOpenPdf, annotationBusy }: EvidenceInspectorProps) {
  const comparison = results?.comparisons.find((item) => item.id === evidenceId);
  const caseId = evidenceId.replace(/^(case:|raw-series:)/, "");
  const resultCase = results?.cases.find((item) => (item.case_id || item.spec_id) === caseId);
  const plannedCase = plan?.cases.find((item) => item.id === caseId);
  const qualityId = evidenceId.replace(/^quality:/, "");
  const quality = results?.quality_report?.checks.find((item) => item.id === qualityId);
  const paperId = evidenceId.replace(/^paper:/, "");
  const paper = papers.find((item) => item.id === paperId);
  const claimIndex = evidenceId.startsWith("claim:") ? Number(evidenceId.split(":")[1]) - 1 : -1;
  const claim = claimIndex >= 0 ? claims?.claims[claimIndex] : null;
  const metric = evidenceId.startsWith("metric:") ? evidenceId.slice(7) : "";
  const protocol = evidenceId.startsWith("protocol:") ? results?.analysis_protocol_snapshot ?? plan?.analysis_protocol : null;
  const finding = papers.flatMap((item) => item.findings ?? []).find((item) => item.id === evidenceId);
  const gap = synthesis?.gaps.find((item) => item.id === evidenceId);
  const conflict = synthesis?.conflicts.find((item) => item.id === evidenceId);

  let content = <p className="muted">This evidence identifier is retained in the report, but no structured object is available in the selected analysis revision.</p>;
  if (comparison) content = <div className="evidence-detail"><span className="evidence-kind">Matched comparison</span><h3>{comparison.metric}</h3><dl><dt>Baseline</dt><dd className="mono">{comparison.baseline_value} {comparison.unit}</dd><dt>Candidate</dt><dd className="mono">{comparison.candidate_value} {comparison.unit}</dd><dt>Change</dt><dd className="mono">{comparison.absolute_delta >= 0 ? "+" : ""}{comparison.absolute_delta} {comparison.unit} · {comparison.percent_delta?.toFixed(2) ?? "—"}%</dd><dt>Direction</dt><dd>{comparison.direction.replaceAll("_", " ")}</dd></dl>{onSelectCase && <div className="evidence-links"><Button onClick={() => onSelectCase(comparison.baseline_case_id)}>Baseline case</Button><Button onClick={() => onSelectCase(comparison.candidate_case_id)}>Candidate case</Button></div>}</div>;
  else if (resultCase || plannedCase) content = <div className="evidence-detail"><span className="evidence-kind">Experiment case</span><h3>{caseId}</h3><dl><dt>Model</dt><dd>{resultCase?.model_name ?? plannedCase?.model_name}</dd><dt>Status</dt><dd>{resultCase?.status ?? "planned"}</dd><dt>Raw integrity</dt><dd>{resultCase?.result_file_integrity ?? "not collected"}</dd><dt>SHA-256</dt><dd className="mono hash-wrap">{resultCase?.result_file_sha256 || "unavailable"}</dd></dl><h4>Parameters</h4><pre>{JSON.stringify(resultCase?.parameters ?? plannedCase?.parameters ?? {}, null, 2)}</pre><h4>Metrics</h4><pre>{JSON.stringify(resultCase?.metrics ?? {}, null, 2)}</pre></div>;
  else if (quality) content = <div className="evidence-detail"><span className="evidence-kind">Study-quality check</span><h3>{quality.id}</h3><p>{quality.message}</p><dl><dt>Status</dt><dd>{quality.status}</dd><dt>Observed</dt><dd>{quality.observed}</dd><dt>Expected</dt><dd>{quality.expected}</dd><dt>Cases</dt><dd>{quality.case_ids.join(", ") || "all"}</dd></dl></div>;
  else if (paper) content = <div className="evidence-detail"><span className="evidence-kind">Literature source</span><h3>{paper.title}</h3><p>{paper.abstract || "No abstract was available."}</p><dl><dt>Credibility</dt><dd>{paper.peer_review_confidence}</dd><dt>Extraction basis</dt><dd>{paper.extraction_basis}</dd><dt>Provenance</dt><dd>{paper.provenance.join(", ") || "unavailable"}</dd><dt>Conditions</dt><dd>{paper.study_conditions?.join("; ") || "not stated"}</dd><dt>Limitations</dt><dd>{paper.limitations.join("; ") || "not stated"}</dd><dt>Findings</dt><dd>{paper.findings?.length ?? 0}</dd></dl>{paper.url && <a href={paper.url} target="_blank" rel="noreferrer">Open source ↗</a>}</div>;
  else if (finding) content = <div className="evidence-detail"><span className="evidence-kind">Abstract-grounded finding</span><h3>{finding.statement}</h3><dl><dt>Direction</dt><dd>{finding.direction.replaceAll("_", " ")}</dd><dt>Intervention</dt><dd>{finding.intervention || "not stated"}</dd><dt>Outcome</dt><dd>{finding.outcome || "not stated"}</dd><dt>Conditions</dt><dd>{finding.conditions.join("; ") || "not stated"}</dd><dt>Metrics</dt><dd>{finding.metrics.join(", ") || "not stated"}</dd><dt>Extraction</dt><dd>{finding.extraction_basis.replace("_", " ")}</dd></dl>{onNavigate && <Button onClick={() => onNavigate(`paper:${finding.paper_id}`)}>Inspect source paper</Button>}</div>;
  else if (gap) content = <div className="evidence-detail"><span className="evidence-kind">Validated research gap</span><h3>{gap.statement}</h3><dl><dt>Category</dt><dd>{gap.category}</dd><dt>Confidence</dt><dd>{gap.confidence}</dd><dt>Testability</dt><dd>{gap.testability_note || "not stated"}</dd><dt>Models</dt><dd>{gap.model_names.join(", ") || "not mapped"}</dd></dl>{onNavigate && <div className="evidence-links">{gap.finding_ids.map((id) => <Button key={id} onClick={() => onNavigate(id)}>{id}</Button>)}{gap.paper_ids.map((id) => <Button key={id} onClick={() => onNavigate(`paper:${id}`)}>paper:{id}</Button>)}</div>}</div>;
  else if (conflict) content = <div className="evidence-detail"><span className="evidence-kind">Research {conflict.kind}</span><h3>{conflict.statement}</h3><dl><dt>Classification</dt><dd>{conflict.kind}</dd><dt>Confidence</dt><dd>{conflict.confidence}</dd><dt>Possible explanations</dt><dd>{conflict.explanatory_factors.join("; ") || "not stated"}</dd></dl>{onNavigate && <div className="evidence-links">{conflict.finding_ids.map((id) => <Button key={id} onClick={() => onNavigate(id)}>{id}</Button>)}</div>}</div>;
  else if (claim) content = <div className="evidence-detail"><span className="evidence-kind">Generated claim</span><h3>{claim.statement}</h3><p>{claim.evidence}</p><dl><dt>Confidence</dt><dd>{claim.confidence}</dd><dt>Comparisons</dt><dd className="mono">{claim.comparison_ids.join(", ") || "none"}</dd><dt>Papers</dt><dd className="mono">{claim.paper_ids.join(", ") || "none"}</dd></dl></div>;
  else if (metric) { const source = results?.cases.find((item) => metric in item.metrics); content = <div className="evidence-detail"><span className="evidence-kind">Computed metric</span><h3>{metric}</h3><p>{source?.metric_methods?.[metric] ?? "Deterministic calculation from the stored result series."}</p><dl><dt>Selected value</dt><dd className="mono">{source?.metrics[metric] ?? "unavailable"}</dd></dl></div>; }
  else if (protocol) content = <div className="evidence-detail"><span className="evidence-kind">Analysis protocol</span><h3>{protocol.id} · v{protocol.version}</h3><dl><dt>Thermal threshold</dt><dd>{protocol.thermal_threshold_degC} °C</dd><dt>HVAC screen</dt><dd>{protocol.hvac_power_screen_min_W}–{protocol.hvac_power_screen_max_W} W</dd><dt>Max screened</dt><dd>{(protocol.max_power_screen_fraction * 100).toFixed(2)}%</dd></dl><pre>{JSON.stringify(protocol.metric_methods, null, 2)}</pre></div>;

  const mine = (annotations ?? []).filter((item) => item.evidence_id === evidenceId);
  const readable = paper?.pdf?.status === "available";

  return <Dialog open={Boolean(evidenceId)} title="Evidence inspector" onClose={onClose} actions={<Button onClick={onClose}>Close</Button>}>
    <div className="mono evidence-id">{evidenceId}</div>
    {content}
    {paper && readable && onOpenPdf && <div className="evidence-links"><Button onClick={() => onOpenPdf(paper.id)}>Read the full text</Button></div>}
    <AnnotationThread annotations={mine} onResolve={onResolveAnnotation} onOpenPdf={onOpenPdf ? (id, page) => onOpenPdf(id, page) : undefined} busy={annotationBusy} />
    {onAnnotate && <AnnotationComposer evidenceId={evidenceId} onSave={onAnnotate} busy={annotationBusy} />}
  </Dialog>;
}
