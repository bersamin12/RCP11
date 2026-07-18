import { useEffect, useRef, useState } from "react";

import type { MemoryDetail, MemoryTopic, Registry, ResultBundle, RunRecord, Series } from "./types";

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
  return resp.json();
}

export const api = {
  health: () => fetch("/api/health").then((r) => json<{ ok: boolean }>(r)),
  listRuns: () => fetch("/api/runs").then((r) => json<RunRecord[]>(r)),
  createRun: (topic: string, constraints: string[], auto: boolean) =>
    fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic, constraints, auto }),
    }).then((r) => json<{ run_id: string }>(r)),
  runDetail: (id: string) => fetch(`/api/runs/${id}`).then((r) => json<RunRecord>(r)),
  answerGate: (id: string, answer: string) =>
    fetch(`/api/runs/${id}/gate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answer }),
    }).then((r) => json<{ ok: boolean }>(r)),
  report: (id: string) =>
    fetch(`/api/runs/${id}/report`).then((r) => (r.ok ? r.text() : Promise.resolve(""))),
  series: (id: string) =>
    fetch(`/api/runs/${id}/series`).then((r) => (r.ok ? r.json() : null)) as Promise<Series | null>,
  memoryTopics: () => fetch("/api/memory").then((r) => json<MemoryTopic[]>(r)),
  memoryDetail: (slug: string) => fetch(`/api/memory/${slug}`).then((r) => json<MemoryDetail>(r)),
  models: () => fetch("/api/models").then((r) => json<Registry>(r)),
  simulate: (model_name: string, parameters: Record<string, number>) =>
    fetch("/api/simulations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_name, parameters }),
    }).then((r) => json<ResultBundle>(r)),
};

/** Live run record: initial fetch + SSE updates, polling fallback. */
export function useRunRecord(runId: string | null): RunRecord | null {
  const [record, setRecord] = useState<RunRecord | null>(null);
  const pollTimer = useRef<number>();

  useEffect(() => {
    if (!runId) return;
    let closed = false;
    api.runDetail(runId).then((r) => !closed && setRecord(r)).catch(() => {});

    const source = new EventSource(`/api/runs/${runId}/events`);
    source.onmessage = (ev) => {
      if (!closed) setRecord(JSON.parse(ev.data));
    };
    source.onerror = () => {
      source.close();
      // fall back to polling while the run is alive
      const poll = async () => {
        try {
          const r = await api.runDetail(runId);
          if (closed) return;
          setRecord(r);
          if (r.status === "running" || r.status === "waiting_gate") {
            pollTimer.current = window.setTimeout(poll, 1500);
          }
        } catch {
          /* run may not exist */
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

  return record;
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
