import { useEffect, useMemo, useState } from "react";

import { api } from "../api";
import { useNarrow } from "../hooks";
import type { ReportDocument, ReportRevision, ReportValidation } from "../types";
import { Markdown } from "./Markdown";
import { WarningBanner } from "./Credibility";
import { Button, Dialog } from "./UI";

const actionStyle = { height: 29, border: "1px solid var(--border-strong)", borderRadius: 6, background: "var(--surface)", color: "var(--text-muted)", padding: "0 9px", fontSize: 11, cursor: "pointer" };

export function ReportWorkspace({ runId, warnings = [], onEvidenceSelect }: { runId: string; warnings?: string[]; onEvidenceSelect?: (id: string) => void }) {
  const narrow = useNarrow(900);
  const [document, setDocument] = useState<ReportDocument | null>(null);
  const [activeId, setActiveId] = useState("");
  const [draft, setDraft] = useState("");
  const [saveState, setSaveState] = useState<"saved" | "editing" | "saving" | "error">("saved");
  const [error, setError] = useState("");
  const [validation, setValidation] = useState<ReportValidation | null>(null);
  const [revisions, setRevisions] = useState<ReportRevision[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [newSectionTitle, setNewSectionTitle] = useState("");
  const [confirmation, setConfirmation] = useState<{ kind: "delete" | "regenerate" | "restore"; revision?: ReportRevision } | null>(null);

  const reload = () => {
    setError("");
    Promise.all([api.reportDocument(runId), api.reportValidation(runId)])
      .then(([doc, result]) => {
        setDocument(doc); setValidation(result);
        const nextId = doc.sections.some((section) => section.id === activeId) ? activeId : (doc.sections[0]?.id ?? "");
        setActiveId(nextId);
        setDraft(doc.sections.find((section) => section.id === nextId)?.content ?? "");
      })
      .catch((err) => setError(`Could not load report workspace. ${String(err)}`));
  };

  useEffect(reload, [runId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const section = document?.sections.find((item) => item.id === activeId);
    if (section) { setDraft(section.content); setSaveState("saved"); }
  }, [activeId]); // document updates from autosave must not overwrite newer local text

  const active = document?.sections.find((section) => section.id === activeId) ?? null;
  const dirty = !!active && draft !== active.content;

  const saveCurrent = async (): Promise<ReportDocument | null> => {
    if (!document || !active || draft === active.content) return document;
    setSaveState("saving"); setError("");
    try {
      const next = await api.updateReportSection(runId, active.id, { content: draft, expected_version: document.version });
      setDocument(next); setSaveState("saved");
      api.reportValidation(runId).then(setValidation).catch(() => {});
      return next;
    } catch (err) {
      setSaveState("error"); setError(`Autosave failed. ${String(err)} Reload before retrying if another tab edited this report.`);
      return null;
    }
  };

  useEffect(() => {
    if (!dirty || saveState === "saving") return;
    setSaveState("editing");
    const timer = window.setTimeout(() => { void saveCurrent(); }, 900);
    return () => window.clearTimeout(timer);
  }, [draft]); // eslint-disable-line react-hooks/exhaustive-deps

  const selectSection = async (id: string) => {
    if (id === activeId) return;
    const saved = await saveCurrent();
    if (saved) setActiveId(id);
  };

  const updateSection = async (changes: Record<string, unknown>) => {
    if (!document || !active) return;
    const current = await saveCurrent();
    if (!current) return;
    try {
      const next = await api.updateReportSection(runId, active.id, { ...changes, expected_version: current.version });
      setDocument(next); setSaveState("saved");
    } catch (err) { setError(String(err)); }
  };

  const updateMeta = async (changes: Record<string, unknown>) => {
    if (!document) return;
    const current = await saveCurrent();
    if (!current) return;
    try {
      const next = await api.updateReportMetadata(runId, { ...changes, expected_version: current.version });
      setDocument(next); api.reportValidation(runId).then(setValidation).catch(() => {});
    } catch (err) { setError(String(err)); }
  };

  const move = async (delta: number) => {
    if (!document || !active) return;
    const current = await saveCurrent();
    if (!current) return;
    const ids = current.sections.map((section) => section.id);
    const from = ids.indexOf(active.id); const to = from + delta;
    if (from < 0 || to < 0 || to >= ids.length) return;
    [ids[from], ids[to]] = [ids[to], ids[from]];
    try { setDocument(await api.reorderReport(runId, ids, current.version)); }
    catch (err) { setError(String(err)); }
  };

  const add = async (title: string) => {
    if (!document) return;
    if (!title.trim()) return;
    const current = await saveCurrent();
    if (!current) return;
    try {
      const next = await api.addReportSection(runId, { title: title.trim(), after_id: activeId || null, expected_version: current.version });
      setDocument(next); setActiveId(next.sections.find((section) => !current.sections.some((old) => old.id === section.id))?.id ?? activeId);
      setShowAdd(false); setNewSectionTitle("");
      api.reportValidation(runId).then(setValidation).catch(() => {});
    } catch (err) { setError(String(err)); }
  };

  const remove = async () => {
    if (!document || !active) return;
    const current = await saveCurrent();
    if (!current) return;
    try {
      const next = await api.deleteReportSection(runId, active.id, current.version, active.locked);
      setDocument(next); setActiveId(next.sections[0]?.id ?? "");
      api.reportValidation(runId).then(setValidation).catch(() => {});
    } catch (err) { setError(String(err)); }
  };

  const regenerate = async () => {
    if (!document || !active || active.locked) return;
    const manual = draft !== active.generated_content;
    try {
      const next = await api.regenerateReportSection(runId, active.id, document.version, manual);
      setDocument(next); setDraft(next.sections.find((section) => section.id === active.id)?.content ?? "");
      api.reportValidation(runId).then(setValidation).catch(() => {});
    } catch (err) { setError(String(err)); }
  };

  const openHistory = async () => {
    setShowHistory(!showHistory);
    if (!showHistory) api.reportRevisions(runId).then(setRevisions).catch((err) => setError(String(err)));
  };

  const restore = async (revision: ReportRevision) => {
    if (!document) return;
    try {
      const next = await api.restoreReportRevision(runId, revision.id, document.version);
      const nextId = next.sections[0]?.id ?? "";
      setDocument(next); setActiveId(nextId); setDraft(next.sections[0]?.content ?? ""); setShowHistory(false);
      api.reportValidation(runId).then(setValidation).catch(() => {});
    } catch (err) { setError(String(err)); }
  };

  const exportAs = async (format: "md" | "docx" | "pdf") => {
    try {
      const result = await api.reportValidation(runId); setValidation(result);
      if (!result.valid) { setError("Export blocked: fix the report validation errors shown below."); return; }
      window.location.assign(api.reportExportUrl(runId, format));
    } catch (err) { setError(`Export failed. ${String(err)}`); }
  };

  const preview = useMemo(() => active ? `## ${active.title}\n\n${draft}` : "", [active, draft]);
  if (!document) return <div style={{ padding: 28, textAlign: "center", color: "var(--text-faint)" }}>{error || "Loading structured report…"}</div>;

  return (
    <div>
      {warnings.length > 0 && <div style={{ marginBottom: 12 }}><WarningBanner>{warnings.join(" ")}</WarningBanner></div>}
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 7, marginBottom: 10 }}>
        <span className="mono" aria-live="polite" style={{ fontSize: 10.5, color: saveState === "error" ? "var(--danger)" : saveState === "saved" ? "var(--success)" : "var(--warning)" }}>
          {saveState === "saving" ? "saving…" : saveState === "editing" ? "unsaved changes" : saveState === "error" ? "save error" : `saved · v${document.version}`}
        </span>
        <button onClick={() => void saveCurrent()} disabled={!dirty} style={{ ...actionStyle, opacity: dirty ? 1 : 0.5 }}>Save now</button>
        <button onClick={openHistory} style={actionStyle}>Revision history</button>
        <div style={{ marginLeft: "auto", display: "flex", gap: 5 }}>
          {(["md", "docx", "pdf"] as const).map((format) => <button key={format} onClick={() => exportAs(format)} style={actionStyle}>Export {format.toUpperCase()}</button>)}
        </div>
      </div>
      {error && <div role="alert" style={{ background: "var(--danger-soft)", border: "1px solid color-mix(in srgb, var(--danger) 40%, var(--border))", borderRadius: 7, padding: "9px 11px", marginBottom: 10, color: "var(--danger)", fontSize: 11.5 }}>{error} <button onClick={reload}>Reload</button></div>}
      {validation && validation.issues.length > 0 && (
        <div role="alert" style={{ background: validation.valid ? "var(--warning-soft)" : "var(--danger-soft)", border: "1px solid var(--border)", borderRadius: 7, padding: "9px 11px", marginBottom: 10, fontSize: 11.5, color: validation.valid ? "var(--warning)" : "var(--danger)" }}>
          <b>{validation.errors ? `${validation.errors} export-blocking issue${validation.errors === 1 ? "" : "s"}` : `${validation.warnings} report warning${validation.warnings === 1 ? "" : "s"}`}</b>
          {validation.issues.map((issue, index) => <div key={`${issue.code}-${index}`}>{issue.section_id ? `${issue.section_id}: ` : ""}{issue.message}</div>)}
        </div>
      )}
      {showHistory && (
        <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: 10, marginBottom: 10, maxHeight: 180, overflow: "auto" }}>
          {revisions.length ? revisions.map((revision) => (
            <div key={revision.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 4px", borderBottom: "1px solid #f0f1f2", fontSize: 11 }}>
              <span className="mono">v{revision.version}</span><span style={{ flex: 1, color: "var(--text-muted)" }}>{revision.summary} · {new Date(revision.created_at).toLocaleString()}</span><button onClick={() => setConfirmation({ kind: "restore", revision })} style={actionStyle}>Restore</button>
            </div>
          )) : <div style={{ color: "var(--text-faint)", fontSize: 11.5 }}>No persisted revisions yet.</div>}
        </div>
      )}

      <details style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "9px 11px", marginBottom: 10 }}>
        <summary style={{ cursor: "pointer", fontSize: 11.5, fontWeight: 600, color: "var(--accent)" }}>Report metadata</summary>
        <div style={{ display: "grid", gridTemplateColumns: narrow ? "1fr" : "1fr 1fr", gap: 9, marginTop: 10 }}>
          <label style={{ fontSize: 10.5, color: "var(--text-muted)" }}>Title<input className="field" defaultValue={document.metadata.title} onBlur={(event) => { if (event.target.value.trim() !== document.metadata.title) void updateMeta({ title: event.target.value.trim() }); }} style={{ display: "block", height: 32, marginTop: 4 }} /></label>
          <label style={{ fontSize: 10.5, color: "var(--text-muted)" }}>Authors (comma separated)<input className="field" defaultValue={document.metadata.authors.join(", ")} onBlur={(event) => { const authors = event.target.value.split(",").map((item) => item.trim()).filter(Boolean); if (authors.join("\u0000") !== document.metadata.authors.join("\u0000")) void updateMeta({ authors }); }} style={{ display: "block", height: 32, marginTop: 4 }} /></label>
          <label style={{ gridColumn: narrow ? undefined : "1 / -1", fontSize: 10.5, color: "var(--text-muted)" }}>Abstract<textarea className="field" defaultValue={document.metadata.abstract} onBlur={(event) => { if (event.target.value !== document.metadata.abstract) void updateMeta({ abstract: event.target.value }); }} style={{ display: "block", minHeight: 60, marginTop: 4, resize: "vertical" }} /></label>
        </div>
      </details>

      <div style={{ display: "grid", gridTemplateColumns: narrow ? "1fr" : "220px minmax(0, 1fr)", gap: 12, alignItems: "start" }}>
        <aside style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 9, padding: 8 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "3px 4px 8px" }}><b style={{ fontSize: 11.5 }}>Sections</b><button onClick={() => setShowAdd(true)} aria-label="Add section" style={actionStyle}>+ Add</button></div>
          <div style={{ display: narrow ? "flex" : "block", gap: 6, overflowX: "auto" }}>
            {document.sections.map((section, index) => (
              <button key={section.id} onClick={() => selectSection(section.id)} aria-current={activeId === section.id ? "true" : undefined} style={{ display: "flex", width: narrow ? "auto" : "100%", minWidth: narrow ? 150 : 0, alignItems: "center", gap: 7, textAlign: "left", border: 0, borderRadius: 6, background: activeId === section.id ? "var(--accent-soft)" : "transparent", color: activeId === section.id ? "var(--accent)" : "var(--text-muted)", padding: "8px", cursor: "pointer", marginBottom: narrow ? 0 : 3 }}>
                <span className="mono" style={{ color: "var(--text-faint)", fontSize: 10 }}>{index + 1}</span><span style={{ fontSize: 11.5, fontWeight: activeId === section.id ? 600 : 500, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{section.title}</span><span style={{ marginLeft: "auto", fontSize: 10 }}>{section.locked ? "🔒" : section.stale ? "!" : ""}</span>
              </button>
            ))}
          </div>
        </aside>

        {active && (
          <main style={{ minWidth: 0 }}>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginBottom: 7 }}>
              <button onClick={() => move(-1)} disabled={document.sections[0]?.id === active.id} aria-label="Move section up" style={actionStyle}>↑ Up</button>
              <button onClick={() => move(1)} disabled={document.sections.at(-1)?.id === active.id} aria-label="Move section down" style={actionStyle}>↓ Down</button>
              <button onClick={() => updateSection({ locked: !active.locked })} style={actionStyle}>{active.locked ? "Unlock" : "Lock"}</button>
              <button onClick={() => draft !== active.generated_content ? setConfirmation({ kind: "regenerate" }) : void regenerate()} disabled={active.locked} style={{ ...actionStyle, opacity: active.locked ? 0.45 : 1 }}>Regenerate</button>
              <button onClick={() => setConfirmation({ kind: "delete" })} style={{ ...actionStyle, color: "var(--danger)", marginLeft: "auto" }}>Delete</button>
            </div>
            <input className="field" key={`${active.id}-${active.title}`} aria-label="Section title" defaultValue={active.title} disabled={active.locked} onBlur={(event) => { if (event.target.value.trim() && event.target.value !== active.title) void updateSection({ title: event.target.value.trim() }); }} style={{ height: 36, fontWeight: 600, fontSize: 13, marginBottom: 8, background: active.locked ? "var(--surface-subtle)" : "var(--surface)" }} />
            <div style={{ display: "grid", gridTemplateColumns: narrow ? "1fr" : "1fr 1fr", gap: 10 }}>
              <textarea className="field" aria-label={`Edit ${active.title}`} value={draft} readOnly={active.locked} onChange={(event) => { setDraft(event.target.value); setSaveState("editing"); }} onKeyDown={(event) => { if ((event.ctrlKey || event.metaKey) && event.key === "s") { event.preventDefault(); void saveCurrent(); } }} style={{ minHeight: 420, padding: "12px", fontFamily: '"SFMono-Regular", Consolas, monospace', fontSize: 11.5, lineHeight: 1.55, resize: "vertical", background: active.locked ? "var(--surface-subtle)" : "var(--surface)" }} />
              <div aria-label="Live report preview" style={{ minHeight: 420, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "18px 20px", overflow: "auto" }}><Markdown source={preview} /></div>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginTop: 8 }}>
              {active.citation_ids.map((id) => <span key={id} className="mono" style={{ fontSize: 9.5, padding: "2px 6px", borderRadius: 4, color: "var(--accent)", background: "var(--accent-soft)" }}>citation {id}</span>)}
              {active.evidence_ids.map((id) => onEvidenceSelect ? <button key={id} type="button" className="report-evidence-link mono" onClick={() => onEvidenceSelect(id)}>evidence {id}</button> : <span key={id} className="report-evidence-link mono">evidence {id}</span>)}
            </div>
          </main>
        )}
      </div>
      <Dialog open={showAdd} title="Add report section" onClose={() => setShowAdd(false)} actions={<><Button onClick={() => setShowAdd(false)}>Cancel</Button><Button variant="primary" disabled={!newSectionTitle.trim()} onClick={() => void add(newSectionTitle)}>Add section</Button></>}>
        <label className="field-label" htmlFor="new-report-section">Section title</label>
        <input id="new-report-section" className="field" autoFocus value={newSectionTitle} onChange={(event) => setNewSectionTitle(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && newSectionTitle.trim()) void add(newSectionTitle); }} />
      </Dialog>
      <Dialog open={Boolean(confirmation)} title={confirmation?.kind === "delete" ? "Delete report section?" : confirmation?.kind === "restore" ? "Restore report revision?" : "Regenerate section?"} onClose={() => setConfirmation(null)} actions={<><Button onClick={() => setConfirmation(null)}>Cancel</Button><Button variant={confirmation?.kind === "delete" ? "danger" : "primary"} onClick={() => { const action = confirmation; setConfirmation(null); if (action?.kind === "delete") void remove(); else if (action?.kind === "regenerate") void regenerate(); else if (action?.revision) void restore(action.revision); }}>{confirmation?.kind === "delete" ? "Delete section" : confirmation?.kind === "restore" ? "Restore revision" : "Overwrite edits"}</Button></>}>
        <p>{confirmation?.kind === "delete" ? `“${active?.title ?? "This section"}” will be removed. A restorable report revision will be retained.` : confirmation?.kind === "restore" ? `The report will return to version ${confirmation.revision?.version}. Current content remains in revision history.` : "Regeneration will overwrite manual edits in this section."}</p>
      </Dialog>
    </div>
  );
}
