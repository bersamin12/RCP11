import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api, errorMessage, fmtElapsed, useRunRecord } from "../api";
import { ConfidenceBadge } from "../components/Badges";
import { ComparisonVisuals } from "../components/ComparisonVisuals";
import { CredibilityBadge } from "../components/Credibility";
import { EvidenceInspector } from "../components/EvidenceInspector";
import { LiteratureTriage } from "../components/LiteratureTriage";
import { PdfReaderPane } from "../components/PdfReaderPane";
import { ReportWorkspace } from "../components/ReportWorkspace";
import { HypothesisRanking, ResearchIntelligence } from "../components/ResearchIntelligence";
import { LineageBreadcrumb, ResearchReviewPanel } from "../components/ResearchReview";
import { RunOutcome } from "../components/RunOutcome";
import { ScientificChart } from "../components/ScientificChart";
import { useToast } from "../components/Toast";
import { Alert, Button, EmptyState, LoadingBlock } from "../components/UI";
import { WorkflowPhases } from "../components/WorkflowPhases";
import { METRIC_DISPLAY, NODE_DEFS, fmtMetric } from "../theme";
import type { AnalysisRevision, AnnotationDraft, EvidenceAnnotation, ExperimentResultSet, MetricComparison, Series, TriageEntry } from "../types";

type TabKey = "overview" | "literature" | "intelligence" | "experiment" | "results" | "report" | "claims";
const TABS: { key: TabKey; label: string }[] = [
  { key: "overview", label: "Overview" }, { key: "literature", label: "Literature" },
  { key: "intelligence", label: "Intelligence" },
  { key: "experiment", label: "Experiment" }, { key: "results", label: "Results" },
  { key: "report", label: "Report" }, { key: "claims", label: "Claims" },
];

function ComparisonTable({ comparisons, onEvidence }: { comparisons: MetricComparison[]; onEvidence: (id: string) => void }) {
  if (!comparisons.length) return <EmptyState>No matched comparisons are available for this revision.</EmptyState>;
  return <div className="card table-wrap"><table className="data-table"><thead><tr><th>Pair</th><th>Metric</th><th>Baseline</th><th>Candidate</th><th>Change</th><th>Assessment</th></tr></thead><tbody>{comparisons.map((item) => <tr key={item.id} className="clickable-row"><td><button className="evidence-table-link mono" onClick={() => onEvidence(item.id)} aria-label={`Inspect evidence ${item.id}`}>{item.pair_id.replace("pair-", "")}</button></td><td>{item.metric}</td><td className="mono">{fmtMetric(item.metric, item.baseline_value)} {item.unit}</td><td className="mono">{fmtMetric(item.metric, item.candidate_value)} {item.unit}</td><td className="mono">{item.percent_delta == null ? "—" : `${item.percent_delta >= 0 ? "+" : ""}${item.percent_delta.toFixed(2)}%`}</td><td><span className={`comparison-result ${item.candidate_better === true ? "better" : item.candidate_better === false ? "worse" : "tie"}`}>{item.candidate_better === true ? "candidate better" : item.candidate_better === false ? "candidate worse" : "tie / neutral"}</span></td></tr>)}</tbody></table></div>;
}

export function RunDetail({ runId, goDashboard, openRun }: { runId: string; goDashboard: () => void; openRun: (id: string) => void }) {
  const { record, error: recordError, refresh } = useRunRecord(runId);
  const notify = useToast();
  const [params, setParams] = useSearchParams();
  const requestedTab = params.get("tab") as TabKey | null;
  const tab: TabKey = TABS.some((item) => item.key === requestedTab) ? requestedTab! : "overview";
  const [analysisRevisions, setAnalysisRevisions] = useState<AnalysisRevision[]>([]);
  const [results, setResults] = useState<ExperimentResultSet | null>(null);
  const [series, setSeries] = useState<Series | null>(null);
  const [seriesError, setSeriesError] = useState("");
  const [gateBusy, setGateBusy] = useState(false);
  const [gateError, setGateError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [showRawPower, setShowRawPower] = useState(false);
  const [triageEntries, setTriageEntries] = useState<Record<string, TriageEntry>>({});
  const [annotations, setAnnotations] = useState<EvidenceAnnotation[]>([]);
  const [annotationBusy, setAnnotationBusy] = useState(false);

  const state = record?.state ?? {};
  const triagePapers = record?.status === "waiting_gate" && record.gate?.gate === "literature_triage"
    ? record.gate.papers ?? [] : [];
  const liveResults = state.experiment_results ?? null;
  const currentRevisionId = liveResults?.analysis_revision_id ?? "";
  const selectedRevisionId = params.get("revision") || currentRevisionId;
  const evidenceId = params.get("evidence") || "";

  const updateParams = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    Object.entries(changes).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key));
    setParams(next, { replace: true });
  };

  useEffect(() => {
    if (!liveResults || liveResults.status === "pending") { setResults(liveResults); return; }
    let active = true;
    const request = selectedRevisionId && selectedRevisionId !== currentRevisionId
      ? api.analysisRevision(runId, selectedRevisionId) : api.results(runId);
    request.then((value) => active && setResults(value)).catch((err) => { if (active) { setResults(liveResults); notify(errorMessage(err)); } });
    api.analysisRevisions(runId).then((value) => active && setAnalysisRevisions(value)).catch((err) => active && notify(errorMessage(err)));
    return () => { active = false; };
  }, [runId, currentRevisionId, liveResults?.status, selectedRevisionId]); // eslint-disable-line react-hooks/exhaustive-deps

  const successfulCases = results?.cases.filter((item) => item.status === "ok") ?? [];
  const selectedCaseId = params.get("case") || successfulCases[0]?.case_id || "";
  const selectedResult = successfulCases.find((item) => (item.case_id || item.spec_id) === selectedCaseId) ?? successfulCases[0] ?? state.result_bundle ?? null;

  useEffect(() => {
    if (!selectedResult || selectedResult.status !== "ok") { setSeries(null); return; }
    let active = true;
    setSeries(null); setSeriesError("");
    api.series(runId, selectedResult.case_id || selectedResult.spec_id, selectedRevisionId || undefined)
      .then((value) => active && setSeries(value))
      .catch((err) => { if (active) setSeriesError(errorMessage(err)); });
    return () => { active = false; };
  }, [runId, selectedResult?.case_id, selectedResult?.spec_id, selectedRevisionId]);

  // Seed the triage form from the paper-id set, never from `record` identity: the
  // SSE stream replaces the whole record roughly every 0.7s while a run is waiting
  // at a gate, which would otherwise wipe a half-typed exclusion reason.
  const triagePaperKey = triagePapers.map((paper) => paper.id).join(",");
  useEffect(() => {
    if (!triagePaperKey) return;
    setTriageEntries((current) => {
      const next = { ...current };
      for (const id of triagePaperKey.split(",")) {
        if (!next[id]) next[id] = { paper_id: id, decision: "include", reason: "", note: "" };
      }
      return next;
    });
  }, [triagePaperKey]);

  useEffect(() => {
    let active = true;
    api.annotations(runId)
      .then((value) => { if (active) setAnnotations(value); })
      .catch(() => { if (active) setAnnotations([]); });
    return () => { active = false; };
  }, [runId]);

  const saveAnnotation = async (draft: AnnotationDraft) => {
    setAnnotationBusy(true);
    try {
      const created = await api.createAnnotation(runId, draft);
      setAnnotations((current) => [...current, created]);
      notify("Annotation saved.", "success");
    } finally { setAnnotationBusy(false); }
  };

  const resolveAnnotationById = async (annotationId: string) => {
    setAnnotationBusy(true);
    try {
      await api.resolveAnnotation(runId, annotationId, "Resolved by the supervisor.", "supervisor");
      setAnnotations(await api.annotations(runId));
      notify("Annotation resolved.", "success");
    } catch (err) { notify(errorMessage(err)); }
    finally { setAnnotationBusy(false); }
  };

  const answerGate = async (answer: string | Record<string, unknown>) => {
    setGateBusy(true); setGateError("");
    try { await api.answerGate(runId, answer); setFeedback(""); }
    catch (err) { setGateError(errorMessage(err)); }
    finally { setGateBusy(false); }
  };

  const submitTriage = async (reviewer: string) => {
    const entries = triagePapers.map((paper) =>
      triageEntries[paper.id] ?? { paper_id: paper.id, decision: "include" as const, reason: "", note: "" });
    await answerGate({
      reviewer,
      included_paper_ids: entries.filter((e) => e.decision === "include").map((e) => e.paper_id),
      exclusions: entries.filter((e) => e.decision === "exclude")
        .map((e) => ({ paper_id: e.paper_id, reason: e.reason })),
      notes: entries.filter((e) => e.note.trim())
        .map((e) => ({ paper_id: e.paper_id, note: e.note.trim() })),
    });
  };

  const archive = async () => {
    if (!record) return;
    try { await api.setRunArchived(runId, !record.archived_at); await refresh(); notify(record.archived_at ? "Run restored." : "Run archived.", "success"); }
    catch (err) { notify(errorMessage(err)); }
  };
  const retry = async () => {
    try { await api.retryRun(runId); await refresh(); notify("Run resumed from its checkpoint.", "success"); }
    catch (err) { notify(errorMessage(err)); }
  };

  const selectedRevision = analysisRevisions.find((item) => item.id === selectedRevisionId);
  const isCurrentRevision = !selectedRevisionId || selectedRevisionId === currentRevisionId || selectedRevision?.current;
  const benchmark = selectedResult?.model_name.startsWith("ChillerCooled");
  const tempKey = benchmark ? "T_room_K" : "T";
  const powerKey = benchmark ? (showRawPower ? "P_HVAC_W" : "P_HVAC_screened_W") : "P_cool";
  const tabCounts = { literature: state.paper_cards?.length ?? 0, intelligence: (state.research_synthesis?.gaps.length ?? state.gaps?.length ?? 0) + (state.research_synthesis?.conflicts.length ?? 0), experiment: state.experiment_plan?.cases.length ?? (state.experiment_spec ? 1 : 0), results: results?.cases.length ?? 0, claims: state.claim_bundle?.claims.length ?? 0 };

  if (!record) return recordError
    ? <Alert tone="danger" title="Run unavailable"><p>{recordError}</p><Button onClick={goDashboard}>Return to all runs</Button></Alert>
    : <LoadingBlock label="Connecting to the run…" />;
  const gate = record.status === "waiting_gate" ? record.gate : null;
  const readerPaperId = params.get("pdf") ?? "";
  const readerPage = Math.max(1, Number(params.get("page") || 1));
  const readerView = params.get("pdfview") === "text" ? "text" : "page";
  const readerDim = params.get("pdfdim") === "1";
  const readerPaper = (state.paper_cards ?? []).find((paper) => paper.id === readerPaperId) ?? null;
  const closeReader = () => updateParams({ pdf: null, page: null, pdfview: null, pdfdim: null });

  return <section>
    <Button variant="ghost" onClick={goDashboard}>← All runs</Button>
    <LineageBreadcrumb runId={runId} openRun={openRun} />
    <div className="run-header">
      <div><div className="run-title-row"><h1>{record.topic}</h1><span className={`status-pill status-${record.status}`}>{record.status.replace("_", " ")}</span>{record.archived_at && <span className="status-pill status-stale">archived</span>}</div><div className="run-meta mono"><span>{record.run_id}</span><span>{fmtElapsed(record)}</span><span>{record.auto ? "automatic gates" : "human approval"}</span>{record.retry_count ? <span>retry {record.retry_count}</span> : null}</div></div>
      <div className="run-actions">{record.status === "failed" && record.retryable && <Button variant="primary" onClick={() => void retry()}>Retry checkpoint</Button>}{["done", "failed", "stale"].includes(record.status) && <Button onClick={() => void archive()}>{record.archived_at ? "Restore" : "Archive"}</Button>}<a className="btn" href={api.artifactExportUrl(runId)}>Download artifacts</a></div>
    </div>
    {record.error && <Alert tone="danger" title="Run failed"><div>{record.error}</div>{record.retryable ? <p>This failure has a resumable checkpoint.</p> : <p>This failure cannot be safely retried in place.</p>}</Alert>}
    {record.checkpoint_health && ["missing", "incompatible", "corrupt"].includes(record.checkpoint_health.status) && <Alert tone={record.checkpoint_health.status === "missing" && ["done", "stale"].includes(record.status) ? "warning" : "danger"} title={record.checkpoint_health.status === "missing" ? "Legacy artifacts only" : "Checkpoint unavailable"}><p>{record.checkpoint_health.detail}</p>{record.checkpoint_health.status === "missing" && ["done", "stale"].includes(record.status) && <p>The preserved report and artifacts remain readable, but this cycle cannot resume from workflow state.</p>}</Alert>}

    <div className="card workflow-card"><WorkflowPhases current={record.current_node} history={record.node_history} status={record.status} entryPoint={record.entry_point} /></div>

    {gate && <section className="card gate-panel" aria-labelledby="gate-heading"><div className="gate-heading"><span className="evidence-kind">Action required</span><h2 id="gate-heading">{gate.question}</h2></div>
      {gate.gate === "literature_triage" && <div className={readerPaper ? "reader-layout" : undefined}><LiteratureTriage papers={triagePapers} entries={triageEntries} busy={gateBusy} readingPaperId={readerPaperId} onEntryChange={(id, changes) => setTriageEntries((current) => ({ ...current, [id]: { ...(current[id] ?? { paper_id: id, decision: "include", reason: "", note: "" }), ...changes } }))} onOpenPdf={(id) => id === readerPaperId ? closeReader() : updateParams({ pdf: id, page: "1", evidence: null })} onSubmit={(reviewer) => void submitTriage(reviewer)} />{readerPaper && <PdfReaderPane paper={readerPaper} page={readerPage} view={readerView} dim={readerDim} onParams={updateParams} onClose={closeReader} />}</div>}
      {gate.gate === "hypothesis_selection" && <HypothesisRanking hypotheses={state.hypotheses ?? []} busy={gateBusy} onEvidence={(id) => updateParams({ evidence: id })} onSelect={(id) => void answerGate({ selected_id: id })} />}
      {gate.gate === "spec_approval" && <div className="gate-approval"><div><h3>Approve {gate.plan?.cases.length ?? 1} executable case{gate.plan?.cases.length === 1 ? "" : "s"}</h3><p>{gate.plan?.description || gate.spec?.description}</p><dl><dt>Model</dt><dd className="mono">{gate.spec?.model_name}</dd><dt>Cases</dt><dd>{gate.plan?.cases.length ?? 1}</dd><dt>Matched pairs</dt><dd>{gate.plan?.comparison_pairs.length ?? 0}</dd><dt>Protocol</dt><dd className="mono">{gate.plan?.analysis_protocol?.id ?? "generic"}</dd></dl><Button variant="primary" disabled={gateBusy || Boolean(gate.plan?.validation_issues.length)} onClick={() => void answerGate({ decision: "approve" })}>{gateBusy ? "Submitting…" : "Approve and execute"}</Button></div><div><label className="field-label" htmlFor="gate-feedback">Request a revision</label><textarea id="gate-feedback" className="field" rows={6} value={feedback} onChange={(event) => setFeedback(event.target.value)} placeholder="Describe the scientific or execution change required." /><Button disabled={gateBusy || !feedback.trim()} onClick={() => void answerGate({ decision: "revise", feedback: feedback.trim() })}>Return for revision</Button></div></div>}
      {gate.gate === "rollback_decision" && <div className="toolbar"><Button variant="primary" disabled={gateBusy} onClick={() => void answerGate({ decision: "revise", feedback: "Revise failed experiment cases" })}>Revise plan</Button><Button disabled={gateBusy} onClick={() => void answerGate({ decision: "continue_partial" })}>Continue with qualified partial evidence</Button><Button variant="danger" disabled={gateBusy} onClick={() => void answerGate({ decision: "abort" })}>Abort</Button></div>}
      {!["literature_triage", "hypothesis_selection", "spec_approval", "rollback_decision"].includes(gate.gate) && <div className="gate-fallback"><Alert tone="warning" title="This gate has no dedicated form yet"><p>Answer it directly so the run is never left unresumable.</p></Alert><label><span className="field-label">Raw gate answer</span><textarea id="gate-raw" className="field mono" rows={4} value={feedback} onChange={(event) => setFeedback(event.target.value)} placeholder="A plain answer, or JSON for a structured decision." /></label><Button variant="primary" disabled={gateBusy || !feedback.trim()} onClick={() => { let parsed: string | Record<string, unknown> = feedback.trim(); try { parsed = JSON.parse(feedback) as Record<string, unknown>; } catch { /* plain text answer */ } void answerGate(parsed); }}>Submit answer</Button></div>}
      {gateError && <Alert tone="danger">{gateError}</Alert>}
    </section>}

    <ResearchReviewPanel record={record} protocol={state.experiment_plan?.analysis_protocol} refresh={refresh} openRun={openRun} />

    <nav className="run-tabs" aria-label="Run workspace">{TABS.map((item) => <button key={item.key} aria-current={tab === item.key ? "page" : undefined} onClick={() => updateParams({ tab: item.key })}>{item.label}{item.key in tabCounts && <span>{tabCounts[item.key as keyof typeof tabCounts]}</span>}</button>)}</nav>

    {tab === "overview" && <div className="overview-workspace">
      {record.outcome ? <RunOutcome outcome={record.outcome} claims={state.claim_bundle?.claims.length ?? 0} /> : <LoadingBlock label="Preparing the decision summary…" />}
      <div className="overview-grid"><section className="card overview-main"><h2>Research question</h2><p className="lead">{state.selected_hypothesis?.statement ?? record.thesis_idea?.research_question ?? "The research question will appear after hypothesis selection."}</p>{state.review_bundle && <Alert tone={state.review_bundle.valid ? "info" : "danger"} title={state.review_bundle.valid ? "Evidence review passed" : "Evidence review failed"}>{state.review_bundle.issues.length ? state.review_bundle.issues.map((issue) => issue.message).join(" ") : "All structured claim links were accepted."}</Alert>}</section><aside className="card overview-side"><h2>Evidence inventory</h2><dl><dt>Literature cards</dt><dd>{state.paper_cards?.length ?? 0}</dd><dt>Hypotheses</dt><dd>{state.hypotheses?.length ?? 0}</dd><dt>Experiment cases</dt><dd>{results?.cases.length ?? 0}</dd><dt>Comparisons</dt><dd>{results?.comparisons.length ?? 0}</dd><dt>Claims</dt><dd>{state.claim_bundle?.claims.length ?? 0}</dd></dl></aside></div>
    </div>}

    {tab === "literature" && (state.paper_cards?.length ? <div className="paper-grid">{state.paper_cards.map((paper) => <article className="card paper-card" key={paper.id}><div className="toolbar"><CredibilityBadge status={paper.peer_review_confidence} /><span className="mono score">{paper.selection_score.toFixed(1)}</span></div><button className="paper-title" onClick={() => updateParams({ evidence: `paper:${paper.id}` })}>{paper.title}</button><p>{paper.problem || "Problem statement unavailable."}</p><small>{paper.year ?? "n.d."} · {paper.venue ?? "unknown venue"} · extraction from {paper.extraction_basis} · {paper.findings?.length ?? 0} findings</small>{paper.findings?.length ? <details><summary>Extracted findings</summary><ul>{paper.findings.map((finding) => <li key={finding.id}><button className="evidence-table-link" onClick={() => updateParams({ evidence: finding.id })}>{finding.statement}</button></li>)}</ul></details> : null}<div className="tag-row">{paper.tags.map((tag) => <span key={tag}>{tag}</span>)}</div></article>)}</div> : <EmptyState>Literature cards will appear after research-memory construction.</EmptyState>)}

    {tab === "intelligence" && <ResearchIntelligence synthesis={state.research_synthesis} legacyGaps={state.gaps ?? []} hypotheses={state.hypotheses ?? []} selectedId={state.selected_hypothesis?.id} onEvidence={(id) => updateParams({ evidence: id })} />}

    {tab === "experiment" && (state.experiment_plan ? <div className="experiment-layout"><section className="card"><div className="section-heading"><h2>Approved case matrix</h2><span className="mono">{state.experiment_plan.cases.length} cases</span></div><div className="case-grid">{state.experiment_plan.cases.map((item) => { const result = results?.cases.find((row) => row.case_id === item.id); return <button key={item.id} onClick={() => updateParams({ tab: "results", case: item.id, evidence: null })}><span className="mono">{item.id}</span><b>{item.label}</b><small>{item.model_name}</small><span className={`status-pill status-${result?.status === "ok" ? "done" : result?.status ?? "stale"}`}>{result?.status ?? "planned"}</span></button>; })}</div></section><aside className="card protocol-card"><h2>Frozen protocol</h2><button className="protocol-link" onClick={() => updateParams({ evidence: `protocol:${state.experiment_plan?.analysis_protocol?.id}` })}>{state.experiment_plan.analysis_protocol?.id}</button><dl><dt>Threshold</dt><dd>{state.experiment_plan.analysis_protocol?.thermal_threshold_degC} °C</dd><dt>HVAC screen</dt><dd>{state.experiment_plan.analysis_protocol?.hvac_power_screen_min_W}–{state.experiment_plan.analysis_protocol?.hvac_power_screen_max_W} W</dd><dt>Primary metrics</dt><dd>{state.experiment_plan.primary_metrics.length}</dd></dl><div className="mono hash-wrap">{results?.experiment_plan_sha256}</div></aside></div> : <EmptyState>The experiment plan will appear after specification compilation.</EmptyState>)}

    {tab === "results" && (results && selectedResult ? <div className="results-workspace">
      <div className="card results-toolbar"><label><span>Analysis revision</span><select className="field" value={selectedRevisionId} onChange={(event) => updateParams({ revision: event.target.value, case: null, evidence: null })}>{analysisRevisions.map((revision) => <option key={revision.id} value={revision.id}>{revision.current ? "Current" : "Archived"} · {revision.protocol_id || "legacy"} · {revision.id.slice(0, 10)}</option>)}</select></label><label><span>Displayed case</span><select className="field" value={selectedResult.case_id || selectedResult.spec_id} onChange={(event) => updateParams({ case: event.target.value, evidence: null })}>{successfulCases.map((item) => <option key={item.case_id || item.spec_id} value={item.case_id || item.spec_id}>{item.case_id || item.spec_id} · {item.model_name}</option>)}</select></label><div className="revision-state"><span className={`status-pill ${isCurrentRevision ? "status-done" : "status-stale"}`}>{isCurrentRevision ? "current analysis" : "archived read-only"}</span><span className="mono">{results.analysis_revision_id?.slice(0, 12)}</span></div></div>
      {results.warnings.length > 0 && <Alert tone="warning" title="Qualified result">{results.warnings.join(" ")}</Alert>}
      {results.quality_report && <section className={`card quality-panel ${results.quality_report.valid ? "valid" : "invalid"}`}><div className="section-heading"><h2>{results.quality_report.valid ? "Study quality accepted" : "Study quality failed"}</h2><span className="mono">{results.quality_report.protocol_sha256.slice(0, 12)}</span></div><div className="quality-grid">{results.quality_report.checks.map((check) => <button key={check.id} onClick={() => updateParams({ evidence: `quality:${check.id}` })}><span className={`check-state ${check.status}`}>{check.status}</span><b>{check.id.replaceAll("-", " ")}</b><small>{check.message}</small></button>)}</div></section>}
      <section><div className="section-heading"><h2>Matched comparisons</h2><span>{results.comparisons.length} evidence records</span></div><ComparisonTable comparisons={results.comparisons} onEvidence={(id) => updateParams({ evidence: id })} /></section>
      {state.experiment_plan && <ComparisonVisuals runId={runId} revisionId={selectedRevisionId || undefined} plan={state.experiment_plan} results={results} />}
      <div className="case-evidence-bar card"><Button onClick={() => updateParams({ evidence: `case:${selectedResult.case_id || selectedResult.spec_id}` })}>Inspect case provenance</Button><span className={`integrity ${selectedResult.result_file_integrity}`}>{selectedResult.result_file_integrity ?? "unverified"}</span><span className="mono hash-wrap">raw {selectedResult.result_file_sha256?.slice(0, 16) || "unavailable"}</span><span className="mono hash-wrap">dataset {results.raw_dataset_sha256?.slice(0, 16)}</span></div>
      <div className="metric-grid">{Object.entries(selectedResult.metrics).map(([key, value]) => { const display = METRIC_DISPLAY[key] ?? { label: key, unit: "", color: "var(--text)" }; return <button className="card metric-card" key={key} onClick={() => updateParams({ evidence: `metric:${key}` })}><span className="mono">{key}</span><strong style={{ color: display.color }}>{fmtMetric(key, value)} <small>{display.unit}</small></strong><small>{display.label}</small></button>; })}</div>
      {seriesError && <Alert tone="danger" title="Series unavailable">{seriesError}</Alert>}
      <div className="chart-grid"><ScientificChart title="Room temperature" unit={benchmark ? "K" : "°C"} series={series} lines={[{ key: tempKey, label: benchmark ? "Room temperature" : "Temperature", color: "#dc4c4c" }]} /><div><div className="chart-toggle">{benchmark && series?.P_HVAC_screened_W && <Button onClick={() => setShowRawPower(!showRawPower)}>{showRawPower ? "Use approved screened power" : "Inspect raw upstream power"}</Button>}</div><ScientificChart title={showRawPower && benchmark ? "Raw HVAC power · diagnostic" : "Cooling power"} unit="W" series={series} lines={[{ key: powerKey, label: showRawPower && benchmark ? "Raw HVAC" : "Approved power", color: showRawPower ? "#c77b17" : "#087f95" }]} /></div></div>
    </div> : <EmptyState>Results will appear after a successful simulation.</EmptyState>)}

    {tab === "claims" && (state.claim_bundle?.claims.length ? <div className="claim-list">{state.claim_bundle.claims.map((claim, index) => <article className="card claim-card" key={`${claim.statement}-${index}`}><div><ConfidenceBadge level={claim.confidence} /><span className="mono">claim {index + 1}</span></div><h2>{claim.statement}</h2><p>{claim.evidence}</p><div className="evidence-chip-row">{claim.comparison_ids.map((id) => <button key={id} onClick={() => updateParams({ evidence: id })}>{id}</button>)}{claim.case_ids.map((id) => <button key={id} onClick={() => updateParams({ evidence: `case:${id}` })}>case:{id}</button>)}{claim.paper_ids.map((id) => <button key={id} onClick={() => updateParams({ evidence: `paper:${id}` })}>paper:{id}</button>)}</div></article>)}</div> : <EmptyState>Supported claims will appear after deterministic evidence review.</EmptyState>)}

    {tab === "report" && (state.report_path ? <ReportWorkspace runId={runId} warnings={state.claim_bundle?.credibility_warnings ?? []} onEvidenceSelect={(id) => updateParams({ evidence: id })} /> : <EmptyState>The structured report will appear after evidence review.</EmptyState>)}

    <EvidenceInspector evidenceId={evidenceId} results={results} plan={state.experiment_plan ?? null} papers={state.paper_cards ?? []} claims={state.claim_bundle ?? null} synthesis={state.research_synthesis ?? null} onNavigate={(id) => updateParams({ evidence: id })} onSelectCase={(caseId) => updateParams({ tab: "results", case: caseId, evidence: null })} onClose={() => updateParams({ evidence: null })} annotations={annotations} onAnnotate={saveAnnotation} onResolveAnnotation={(id) => void resolveAnnotationById(id)} onOpenPdf={(paperId, page) => updateParams({ pdf: paperId, page: String(page ?? 1), evidence: null })} annotationBusy={annotationBusy} />
  </section>;
}
