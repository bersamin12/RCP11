import { useEffect, useState } from "react";

import { api, errorMessage } from "../api";
import type { AnalysisProtocol, ProtocolChanges, ResearchLineage, ResearchReviewDecision, RunRecord } from "../types";
import { Alert, Button, Dialog } from "./UI";

const DECISIONS: { id: ResearchReviewDecision; title: string; description: string }[] = [
  { id: "accept", title: "Accept this cycle", description: "Finalize the reviewed evidence package without creating another run." },
  { id: "reanalyse", title: "Reanalyse raw data", description: "Change approved numeric thresholds and recompute without rerunning Modelica." },
  { id: "revise_plan", title: "Revise experiment plan", description: "Create a human-gated successor at scientific compilation." },
  { id: "refine_hypothesis", title: "Refine hypothesis", description: "Create a successor that reuses the frozen literature and generates new hypotheses." },
];

const PROTOCOL_FIELDS: { key: keyof ProtocolChanges; label: string }[] = [
  { key: "thermal_threshold_degC", label: "Thermal threshold (°C)" },
  { key: "hvac_power_screen_min_W", label: "HVAC screen minimum (W)" },
  { key: "hvac_power_screen_max_W", label: "HVAC screen maximum (W)" },
  { key: "max_power_screen_fraction", label: "Maximum screened fraction" },
  { key: "pue_min", label: "PUE minimum" },
  { key: "pue_max", label: "PUE maximum" },
  { key: "mode_hours_tolerance", label: "Mode-hours tolerance" },
  { key: "comparison_absolute_tolerance", label: "Comparison absolute tolerance" },
  { key: "comparison_relative_tolerance", label: "Comparison relative tolerance" },
];

export function LineageBreadcrumb({ runId, openRun }: { runId: string; openRun: (id: string) => void }) {
  const [lineage, setLineage] = useState<ResearchLineage | null>(null);
  useEffect(() => { let active = true; api.runLineage(runId).then((value) => active && setLineage(value)).catch(() => {}); return () => { active = false; }; }, [runId]);
  if (!lineage || lineage.runs.length < 2) return null;
  return <nav className="lineage-breadcrumb" aria-label="Research cycle lineage">{lineage.runs.map((item, index) => <span key={item.run_id}>{index > 0 && <i aria-hidden="true">›</i>}<button aria-current={item.run_id === runId ? "page" : undefined} disabled={item.run_id === runId} onClick={() => openRun(item.run_id)}>Cycle {item.iteration + 1}<small>{item.revision_decision?.replaceAll("_", " ") || "original"}</small></button></span>)}</nav>;
}

export function ResearchReviewPanel({ record, protocol, refresh, openRun }: { record: RunRecord; protocol?: AnalysisProtocol; refresh: () => Promise<RunRecord | null>; openRun: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const [decision, setDecision] = useState<ResearchReviewDecision>("accept");
  const [feedback, setFeedback] = useState("");
  const [changes, setChanges] = useState<ProtocolChanges>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const close = () => { if (!busy) { setOpen(false); setError(""); } };
  const submit = async () => {
    setBusy(true); setError("");
    try {
      const review = await api.reviewRun(record.run_id, {
        decision, feedback: feedback.trim(), expected_version: record.version,
        protocol_changes: decision === "reanalyse" ? changes : undefined,
      });
      setOpen(false);
      if (review.successor_run_id) openRun(review.successor_run_id);
      else await refresh();
    } catch (err) { setError(errorMessage(err)); }
    finally { setBusy(false); }
  };
  const disabled = busy || (decision !== "accept" && !feedback.trim()) || (decision === "reanalyse" && !Object.keys(changes).length);

  if (record.review) return <Alert tone="info" title={record.review.decision === "accept" ? "Research cycle accepted" : "Successor cycle created"}>{record.review.feedback || "The supervisor accepted this evidence package."}{record.review.successor_run_id && <span> <button className="inline-link" onClick={() => openRun(record.review!.successor_run_id!)}>Open successor cycle</button></span>}</Alert>;
  if (record.status !== "done") return null;
  return <>
    <section className="card review-callout"><div><span className="outcome-eyebrow">Supervisor checkpoint</span><h2>Decide what happens after this research cycle</h2><p>Acceptance finalizes this package. Every revision creates an immutable, linked successor.</p></div><Button variant="primary" onClick={() => setOpen(true)}>Review research cycle</Button></section>
    <Dialog open={open} title="Review research cycle" onClose={close} actions={<><Button onClick={close} disabled={busy}>Cancel</Button><Button variant="primary" disabled={disabled} onClick={() => void submit()}>{busy ? "Creating decision…" : decision === "accept" ? "Accept cycle" : "Create successor"}</Button></>}>
      <fieldset className="review-decisions"><legend className="sr-only">Supervisor decision</legend>{DECISIONS.map((item) => <label key={item.id} className={decision === item.id ? "selected" : ""}><input type="radio" name="review-decision" value={item.id} checked={decision === item.id} onChange={() => { setDecision(item.id); setError(""); }} /><span><b>{item.title}</b><small>{item.description}</small></span></label>)}</fieldset>
      {decision !== "accept" && <label className="review-feedback"><span className="field-label">Supervisor feedback</span><textarea className="field" rows={4} value={feedback} onChange={(event) => setFeedback(event.target.value)} placeholder="State the scientific reason and the change required." /></label>}
      {decision === "reanalyse" && <div className="protocol-editor"><Alert tone="warning" title="Raw-data-only successor">Modelica will not rerun. The successor is blocked unless every copied CSV passes its recorded SHA-256 check.</Alert><div className="protocol-field-grid">{PROTOCOL_FIELDS.map((field) => { const before = protocol?.[field.key as keyof AnalysisProtocol] as number | undefined; return <label key={field.key}><span>{field.label}</span><small>Current: {before ?? "unavailable"}</small><input className="field mono" type="number" step="any" placeholder={String(before ?? "")} onChange={(event) => setChanges((current) => { const next = { ...current }; if (event.target.value === "" || Number(event.target.value) === before) delete next[field.key]; else next[field.key] = Number(event.target.value); return next; })} /></label>; })}</div></div>}
      {error && <Alert tone="danger" title="Review could not be saved">{error}</Alert>}
    </Dialog>
  </>;
}
