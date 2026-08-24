import { useCallback, useEffect, useRef, useState } from "react";

import type {
  MemoryDetail, MemoryTopic, ModelValidationReport, Registry, ReportDocument, ReportRevision,
  AnalysisRevision, AnnotationDraft, EvaluationScorecard, EvaluationView, EvidenceAnnotation,
  ExperimentResultSet, FullTextExtraction, PdfAsset, ProtocolChanges, ReportValidation, ResearchLineage, ResearchReview, ResearchReviewDecision, ResearchSynthesis, ResultBundle, RunManifest, RunRecord, Series, ThesisIdea, ThesisProfile,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); this.name = "ApiError"; }
}

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    const text = await resp.text();
    let message = text || resp.statusText;
    try { message = JSON.parse(text).detail ?? message; } catch { /* plain-text response */ }
    throw new ApiError(resp.status, message);
  }
  return resp.json();
}

export const errorMessage = (error: unknown) => error instanceof Error ? error.message : String(error);

export const api = {
  health: () => fetch("/api/health").then((r) => json<{ ok: boolean }>(r)),
  listRuns: () => fetch("/api/runs").then((r) => json<RunRecord[]>(r)),
  thesisIdeas: (profile: ThesisProfile, regenerate = false) =>
    fetch("/api/thesis-ideas", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...profile, regenerate }),
    }).then((r) => json<ThesisIdea[]>(r)),
  createRun: (topic: string, constraints: string[], auto: boolean, thesis_idea?: ThesisIdea | null, thesis_profile?: ThesisProfile | null) =>
    fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic, constraints, auto, thesis_idea, thesis_profile }),
    }).then((r) => json<{ run_id: string }>(r)),
  runDetail: (id: string) => fetch(`/api/runs/${id}`).then((r) => json<RunRecord>(r)),
  setRunArchived: (id: string, archived: boolean) =>
    fetch(`/api/runs/${id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ archived }),
    }).then((r) => json<RunRecord>(r)),
  retryRun: (id: string) => fetch(`/api/runs/${id}/retry`, { method: "POST" }).then((r) => json<RunRecord>(r)),
  reviewRun: (id: string, body: { decision: ResearchReviewDecision; feedback: string; expected_version: number; protocol_changes?: ProtocolChanges }) =>
    fetch(`/api/runs/${id}/review`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }).then((r) => json<ResearchReview>(r)),
  runLineage: (id: string) => fetch(`/api/runs/${id}/lineage`).then((r) => json<ResearchLineage>(r)),
  runSynthesis: (id: string) => fetch(`/api/runs/${id}/synthesis`).then((r) => json<ResearchSynthesis>(r)),
  answerGate: (id: string, answer: string | Record<string, unknown>) =>
    fetch(`/api/runs/${id}/gate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(typeof answer === "string" ? { answer } : answer),
    }).then((r) => json<{ ok: boolean }>(r)),
  report: (id: string) =>
    fetch(`/api/runs/${id}/report`).then((r) => (r.ok ? r.text() : Promise.resolve(""))),
  reportDocument: (id: string) => fetch(`/api/runs/${id}/report/document`).then((r) => json<ReportDocument>(r)),
  updateReportSection: (id: string, sectionId: string, changes: Record<string, unknown>) =>
    fetch(`/api/runs/${id}/report/sections/${sectionId}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(changes),
    }).then((r) => json<ReportDocument>(r)),
  addReportSection: (id: string, body: Record<string, unknown>) =>
    fetch(`/api/runs/${id}/report/sections`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }).then((r) => json<ReportDocument>(r)),
  deleteReportSection: (id: string, sectionId: string, version: number, force = false) =>
    fetch(`/api/runs/${id}/report/sections/${sectionId}?expected_version=${version}&force=${force}`, { method: "DELETE" })
      .then((r) => json<ReportDocument>(r)),
  reorderReport: (id: string, section_ids: string[], expected_version: number) =>
    fetch(`/api/runs/${id}/report/reorder`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ section_ids, expected_version }),
    }).then((r) => json<ReportDocument>(r)),
  regenerateReportSection: (id: string, sectionId: string, expected_version: number, force = false) =>
    fetch(`/api/runs/${id}/report/sections/${sectionId}/regenerate`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_version, force }),
    }).then((r) => json<ReportDocument>(r)),
  updateReportMetadata: (id: string, changes: Record<string, unknown>) =>
    fetch(`/api/runs/${id}/report/metadata`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(changes),
    }).then((r) => json<ReportDocument>(r)),
  reportRevisions: (id: string) => fetch(`/api/runs/${id}/report/revisions`).then((r) => json<ReportRevision[]>(r)),
  restoreReportRevision: (id: string, revisionId: string, expected_version: number) =>
    fetch(`/api/runs/${id}/report/revisions/${revisionId}/restore`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_version }),
    }).then((r) => json<ReportDocument>(r)),
  reportValidation: (id: string) => fetch(`/api/runs/${id}/report/validation`).then((r) => json<ReportValidation>(r)),
  reportExportUrl: (id: string, format: "md" | "docx" | "pdf") => `/api/runs/${id}/report/export?format=${format}`,
  series: (id: string, caseId?: string, revisionId?: string) => {
    const query = new URLSearchParams();
    if (caseId) query.set("case_id", caseId);
    if (revisionId) query.set("revision_id", revisionId);
    return fetch(`/api/runs/${id}/series${query.size ? `?${query}` : ""}`).then((r) => json<Series>(r));
  },
  results: (id: string) => fetch(`/api/runs/${id}/results`).then((r) => json<ExperimentResultSet>(r)),
  analysisRevisions: (id: string) => fetch(`/api/runs/${id}/results/revisions`).then((r) => json<AnalysisRevision[]>(r)),
  analysisRevision: (id: string, revisionId: string) =>
    fetch(`/api/runs/${id}/results/revisions/${revisionId}`).then((r) => json<ExperimentResultSet>(r)),
  analysisRevisionUrl: (id: string, revisionId: string) => `/api/runs/${id}/results/revisions/${revisionId}`,
  manifest: (id: string) => fetch(`/api/runs/${id}/manifest`).then((r) => json<RunManifest>(r)),
  artifactExportUrl: (id: string) => `/api/runs/${id}/artifacts/export`,
  // pdf.js fetches this itself, so it is a URL builder like the export endpoints.
  literaturePdfUrl: (sha256: string) => `/api/literature/pdf/${sha256}`,
  literatureAsset: (sha256: string) =>
    fetch(`/api/literature/assets/${sha256}`).then((r) => json<PdfAsset>(r)),
  annotations: (id: string, evidenceId?: string) => {
    const query = evidenceId ? `?evidence_id=${encodeURIComponent(evidenceId)}` : "";
    return fetch(`/api/runs/${id}/annotations${query}`).then((r) => json<EvidenceAnnotation[]>(r));
  },
  createAnnotation: (id: string, draft: AnnotationDraft) =>
    fetch(`/api/runs/${id}/annotations`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(draft),
    }).then((r) => json<EvidenceAnnotation>(r)),
  resolveAnnotation: (id: string, annotationId: string, resolution_note: string, author: string) =>
    fetch(`/api/runs/${id}/annotations/${annotationId}/resolve`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ resolution_note, author }),
    }).then((r) => json<EvidenceAnnotation>(r)),
  evaluation: (id: string, reviewerId?: string, condition = "platform") => {
    const query = new URLSearchParams({ condition });
    if (reviewerId) query.set("reviewer_id", reviewerId);
    return fetch(`/api/runs/${id}/evaluation?${query}`).then((r) => json<EvaluationView>(r));
  },
  submitScorecard: (id: string, body: Record<string, unknown>) =>
    fetch(`/api/runs/${id}/evaluation`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }).then((r) => json<EvaluationScorecard>(r)),
  proposeFullText: (id: string, paper_id: string) =>
    fetch(`/api/runs/${id}/literature/full-text`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paper_id }),
    }).then((r) => json<FullTextExtraction>(r)),
  memoryTopics: () => fetch("/api/memory").then((r) => json<MemoryTopic[]>(r)),
  memoryDetail: (slug: string) => fetch(`/api/memory/${slug}`).then((r) => json<MemoryDetail>(r)),
  models: () => fetch("/api/models").then((r) => json<Registry>(r)),
  modelValidation: (name: string) => fetch(`/api/models/${encodeURIComponent(name)}/validation`).then((r) => json<ModelValidationReport>(r)),
  simulate: (model_name: string, parameters: Record<string, number>, stop_time?: number) =>
    fetch("/api/simulations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_name, parameters, stop_time }),
    }).then((r) => json<ResultBundle>(r)),
  simulationSeries: (specId: string, points = 200) =>
    fetch(`/api/simulations/${encodeURIComponent(specId)}/series?points=${points}`).then((r) => json<Series>(r)),
};

/** Live run record: initial fetch + SSE updates, polling fallback. */
export function useRunRecord(runId: string | null): { record: RunRecord | null; error: string; refresh: () => Promise<RunRecord | null> } {
  const [record, setRecord] = useState<RunRecord | null>(null);
  const [error, setError] = useState("");
  const pollTimer = useRef<number>();

  const refresh = useCallback(async () => {
    if (!runId) return null;
    try {
      const next = await api.runDetail(runId);
      setRecord(next); setError("");
      return next;
    } catch (err) {
      setError(errorMessage(err));
      return null;
    }
  }, [runId]);

  useEffect(() => {
    if (!runId) return;
    let closed = false;
    api.runDetail(runId).then((r) => { if (!closed) { setRecord(r); setError(""); } }).catch((err) => { if (!closed) setError(errorMessage(err)); });

    const source = new EventSource(`/api/runs/${runId}/events`);
    source.onmessage = (ev) => {
      if (!closed) { setRecord(JSON.parse(ev.data)); setError(""); }
    };
    source.onerror = () => {
      source.close();
      // fall back to polling while the run is alive
      const poll = async () => {
        try {
          const r = await api.runDetail(runId);
          if (closed) return;
          setRecord(r); setError("");
          if (r.status === "running" || r.status === "resuming" || r.status === "waiting_gate") {
            pollTimer.current = window.setTimeout(poll, 1500);
          }
        } catch (err) {
          if (closed) return;
          setError(errorMessage(err));
          pollTimer.current = window.setTimeout(poll, 3000);
        }
      };
      poll();
    };
    return () => {
      closed = true;
      source.close();
      window.clearTimeout(pollTimer.current);
    };
  }, [runId]);

  return { record, error, refresh };
}

export function fmtElapsed(r: { started_at: number | null; ended_at: number | null }): string {
  if (!r.started_at) return "—";
  const end = r.ended_at ?? Date.now() / 1000;
  let s = Math.max(0, Math.floor(end - r.started_at));
  const m = Math.floor(s / 60);
  s = s % 60;
  return (m > 0 ? m + "m " : "") + String(s).padStart(2, "0") + "s";
}

export function fmtAgo(ts: number): string {
  const m = Math.floor((Date.now() / 1000 - ts) / 60);
  if (m < 1) return "now";
  if (m < 60) return m + "m ago";
  const hr = Math.floor(m / 60);
  if (hr < 24) return hr + "h ago";
  return Math.floor(hr / 24) + "d ago";
}
