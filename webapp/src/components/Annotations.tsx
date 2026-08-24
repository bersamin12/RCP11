import { useState } from "react";

import type { AnnotationDraft, AnnotationKind, AnnotationSeverity, EvidenceAnnotation } from "../types";
import { Alert, Button } from "./UI";

/** Annotations carry an ISO timestamp, unlike the epoch seconds fmtAgo expects. */
function whenLabel(created_at: string): string {
  const at = new Date(created_at);
  return Number.isNaN(at.valueOf()) ? created_at : at.toLocaleString();
}

const KINDS: { id: AnnotationKind; label: string; hint: string }[] = [
  { id: "comment", label: "Comment", hint: "A remark for whoever reads this next." },
  { id: "flag", label: "Dispute", hint: "You believe this object is wrong or overstated." },
  { id: "correction", label: "Correction", hint: "Propose a specific replacement value." },
];

const SEVERITIES: { id: AnnotationSeverity; label: string }[] = [
  { id: "info", label: "For information" },
  { id: "concern", label: "Concern" },
  { id: "blocker", label: "Blocks acceptance" },
];

export function AnnotationThread({ annotations, onResolve, onOpenPdf, busy }: {
  annotations: EvidenceAnnotation[];
  onResolve?: (id: string) => void;
  onOpenPdf?: (paperId: string, page: number) => void;
  busy?: boolean;
}) {
  if (!annotations.length) return null;
  return <div className="annotation-thread">
    <h4>Reviewer annotations</h4>
    {annotations.map((item) => <article className={`annotation-item ${item.kind}`} key={item.id}>
      <div className="annotation-head">
        <span className={`annotation-kind ${item.kind}`}>
          {item.kind === "flag" ? "dispute" : item.kind}
        </span>
        {item.severity === "blocker" && !item.resolved && <span className="annotation-kind blocker">blocks acceptance</span>}
        {item.resolved && <span className="annotation-kind resolved">resolved</span>}
        <small className="mono">{item.author} · {whenLabel(item.created_at)}</small>
      </div>
      <p>{item.body}</p>
      {item.kind === "correction" && item.proposed_value && <p className="annotation-proposal">
        <b>Proposed</b> <span className="mono">{item.proposed_value}</span>
        {/* A correction is never applied automatically; only a gate or the report
            editor may change a value. */}
        <small> — recorded as a proposal, not applied.</small>
      </p>}
      {item.anchor && onOpenPdf && <Button variant="ghost" onClick={() => onOpenPdf(item.anchor!.paper_id, item.anchor!.page)}>
        Page {item.anchor.page}: “{item.anchor.quote.slice(0, 60)}{item.anchor.quote.length > 60 ? "…" : ""}”
      </Button>}
      {item.resolved && item.resolution_note && <p className="annotation-resolution">{item.resolution_note}</p>}
      {!item.resolved && onResolve && <Button disabled={busy} onClick={() => onResolve(item.id)}>Mark resolved</Button>}
    </article>)}
  </div>;
}

export function AnnotationComposer({ evidenceId, onSave, busy }: {
  evidenceId: string;
  onSave: (draft: AnnotationDraft) => Promise<void>;
  busy?: boolean;
}) {
  // An inline disclosure rather than a dialog: the host is already a dialog, and
  // two of them would collide on the shared title id and fight over focus.
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<AnnotationKind>("comment");
  const [severity, setSeverity] = useState<AnnotationSeverity>("info");
  const [body, setBody] = useState("");
  const [author, setAuthor] = useState("");
  const [proposed, setProposed] = useState("");
  const [error, setError] = useState("");

  const submit = async () => {
    setError("");
    try {
      await onSave({
        evidence_id: evidenceId, kind, severity, body: body.trim(),
        author: author.trim() || "human",
        proposed_value: kind === "correction" ? proposed.trim() : "",
      });
      setBody(""); setProposed(""); setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  if (!open) {
    return <div className="annotation-composer">
      <Button onClick={() => setOpen(true)}>Add comment, dispute or correction</Button>
    </div>;
  }

  return <div className="annotation-composer">
    <fieldset className="annotation-kinds">
      <legend className="field-label">What kind of remark is this?</legend>
      {KINDS.map((item) => <label key={item.id} className={kind === item.id ? "selected" : ""}>
        <input type="radio" name="annotation-kind" value={item.id} checked={kind === item.id}
               onChange={() => setKind(item.id)} />
        <span><b>{item.label}</b><small>{item.hint}</small></span>
      </label>)}
    </fieldset>

    {kind === "flag" && <label>
      <span className="field-label">How strongly?</span>
      <select className="field" value={severity} aria-label="Dispute severity"
              onChange={(event) => setSeverity(event.target.value as AnnotationSeverity)}>
        {SEVERITIES.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select>
    </label>}

    <label>
      <span className="field-label">Remark</span>
      <textarea className="field" rows={3} value={body}
                onChange={(event) => setBody(event.target.value)}
                placeholder="State what is wrong, or what a later reader should know." />
    </label>

    {kind === "correction" && <label>
      <span className="field-label">Proposed value</span>
      <input className="field" value={proposed} onChange={(event) => setProposed(event.target.value)} />
    </label>}

    <label>
      <span className="field-label">Your name</span>
      <input className="field" value={author} onChange={(event) => setAuthor(event.target.value)} />
    </label>

    <Alert tone="info">
      Annotations are advisory and append-only. A dispute is recorded and shown with the
      evidence, but it never changes the deterministic checks; a blocking dispute holds up
      acceptance of the cycle until it is resolved.
    </Alert>

    {error && <Alert tone="danger" title="The annotation was not saved">{error}</Alert>}

    <div className="toolbar">
      <Button onClick={() => setOpen(false)} disabled={busy}>Cancel</Button>
      <Button variant="primary" disabled={busy || !body.trim()} onClick={() => void submit()}>
        {busy ? "Saving…" : "Save annotation"}
      </Button>
    </div>
  </div>;
}
