import { useState } from "react";

import type { TriageEntry, TriagePaper } from "../types";
import { CredibilityBadge } from "./Credibility";
import { Alert, Button } from "./UI";

export interface LiteratureTriageProps {
  papers: TriagePaper[];
  entries: Record<string, TriageEntry>;
  busy: boolean;
  readingPaperId?: string;
  onEntryChange: (paperId: string, changes: Partial<TriageEntry>) => void;
  onOpenPdf: (paperId: string) => void;
  onSubmit: (reviewer: string) => void;
}

export function LiteratureTriage({
  papers, entries, busy, readingPaperId, onEntryChange, onOpenPdf, onSubmit,
}: LiteratureTriageProps) {
  const [reviewer, setReviewer] = useState("");

  const entryFor = (id: string): TriageEntry =>
    entries[id] ?? { paper_id: id, decision: "include", reason: "", note: "" };
  const included = papers.filter((paper) => entryFor(paper.id).decision === "include");
  const excluded = papers.filter((paper) => entryFor(paper.id).decision === "exclude");
  // An exclusion without a reason is indistinguishable from discarding an
  // inconvenient result, so the backend refuses it and so does the form.
  const unexplained = excluded.filter((paper) => !entryFor(paper.id).reason.trim());
  const blocked = busy || !included.length || unexplained.length > 0;

  return <div className="triage-layout">
    <Alert tone="info">
      Excluded papers contribute no findings, gaps, conflicts or claims. Every exclusion is
      recorded with its reason and hashed into the run manifest.
    </Alert>

    {papers.map((paper) => {
      const entry = entryFor(paper.id);
      const excludedHere = entry.decision === "exclude";
      const name = `triage-${paper.id}`;
      return <article className={`card triage-row${excludedHere ? " excluded" : ""}`} key={paper.id}>
        <div className="triage-main">
          <div className="triage-meta">
            <CredibilityBadge status={paper.peer_review_confidence} />
            <span className="mono">{paper.year ?? "n.d."}</span>
            <span className="mono">{paper.selection_score.toFixed(1)}</span>
            <span className="mono">extraction from {paper.extraction_basis}</span>
            <span className="mono">{paper.finding_count} findings</span>
          </div>
          <h3>{paper.title}</h3>
          <p className="paper-source">{paper.venue ?? "Unknown venue"}</p>
          {paper.insufficient_evidence.length > 0 && <p className="mono triage-insufficient">
            not established from the source: {paper.insufficient_evidence.join(", ")}
          </p>}
        </div>

        <div className="triage-controls">
          {/* A radiogroup, not toggle buttons: the choice is mutually exclusive and
              assistive technology should be told so. */}
          <fieldset className="triage-decision">
            <legend className="sr-only">Decision for {paper.title}</legend>
            <label>
              <input type="radio" name={name} value="include" checked={!excludedHere}
                     onChange={() => onEntryChange(paper.id, { decision: "include", reason: "" })} />
              <span>Include</span>
            </label>
            <label>
              <input type="radio" name={name} value="exclude" checked={excludedHere}
                     onChange={() => onEntryChange(paper.id, { decision: "exclude" })} />
              <span>Exclude</span>
            </label>
          </fieldset>
          {paper.pdf_href
            ? <Button onClick={() => onOpenPdf(paper.id)}>
                {paper.id === readingPaperId ? "Close full text" : "Read full text"}
              </Button>
            : <span className="mono paper-no-fulltext">no open-access full text</span>}
        </div>

        {excludedHere && <label className="triage-reason">
          <span className="field-label">Why is this paper excluded?</span>
          <input className="field" value={entry.reason} required
                 placeholder="e.g. off-topic: astrophysics, not data-centre cooling"
                 onChange={(event) => onEntryChange(paper.id, { reason: event.target.value })} />
        </label>}

        <details className="triage-note">
          <summary>Add a note</summary>
          <label>
            <span className="sr-only">Reviewer note for {paper.title}</span>
            <textarea className="field" rows={2} value={entry.note}
                      placeholder="Anything a later reader should know about this record."
                      onChange={(event) => onEntryChange(paper.id, { note: event.target.value })} />
          </label>
        </details>
      </article>;
    })}

    <div className="triage-summary-bar">
      <span className="mono" aria-live="polite">
        {included.length} included · {excluded.length} excluded
      </span>
      <label className="triage-reviewer">
        <span className="sr-only">Reviewer name</span>
        <input className="field" value={reviewer} placeholder="Reviewer"
               onChange={(event) => setReviewer(event.target.value)} />
      </label>
      <Button variant="primary" disabled={blocked} onClick={() => onSubmit(reviewer.trim())}>
        {busy ? "Submitting…" : "Confirm literature set"}
      </Button>
    </div>

    {!included.length && <Alert tone="danger">At least one paper must be retained.</Alert>}
    {unexplained.length > 0 && <Alert tone="warning">
      State a reason for {unexplained.length} excluded paper{unexplained.length === 1 ? "" : "s"} before continuing.
    </Alert>}
  </div>;
}
