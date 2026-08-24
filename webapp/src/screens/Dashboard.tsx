import { useEffect, useMemo, useState } from "react";

import { api, errorMessage, fmtAgo, fmtElapsed } from "../api";
import { useToast } from "../components/Toast";
import { Button, EmptyState, LoadingBlock } from "../components/UI";
import { NODE_DEFS } from "../theme";
import type { RunRecord } from "../types";

type StatusFilter = "all" | "active" | "attention" | "done" | "failed";

const statusLabel = (status: string) => status === "waiting_gate" ? "waiting on gate" : status;

export function Dashboard({ openRun }: { openRun: (id: string) => void }) {
  const notify = useToast();
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [showArchived, setShowArchived] = useState(false);
  const [busyId, setBusyId] = useState("");

  const load = async (quiet = false) => {
    if (!quiet) setLoading(true);
    try { setRuns(await api.listRuns()); setError(""); }
    catch (err) { setError(errorMessage(err)); }
    finally { if (!quiet) setLoading(false); }
  };

  useEffect(() => {
    let alive = true;
    const poll = () => api.listRuns().then((rows) => alive && setRuns(rows)).catch((err) => alive && setError(errorMessage(err)));
    void load();
    const timer = window.setInterval(poll, 3000);
    return () => { alive = false; window.clearInterval(timer); };
  }, []);

  const counts = useMemo(() => ({
    active: runs.filter((run) => ["running", "resuming"].includes(run.status) && !run.archived_at).length,
    attention: runs.filter((run) => run.status === "waiting_gate" && !run.archived_at).length,
    done: runs.filter((run) => run.status === "done" && !run.archived_at).length,
    failed: runs.filter((run) => run.status === "failed" && !run.archived_at).length,
  }), [runs]);

  const filtered = useMemo(() => runs.filter((run) => {
    if (showArchived !== Boolean(run.archived_at)) return false;
    const needle = query.trim().toLowerCase();
    if (needle && !`${run.run_id} ${run.topic} ${run.current_node ?? ""}`.toLowerCase().includes(needle)) return false;
    if (status === "active") return ["running", "resuming"].includes(run.status);
    if (status === "attention") return run.status === "waiting_gate";
    if (status === "done") return run.status === "done";
    if (status === "failed") return run.status === "failed";
    return true;
  }), [query, runs, showArchived, status]);

  const archive = async (run: RunRecord, archived: boolean) => {
    setBusyId(run.run_id);
    try {
      const updated = await api.setRunArchived(run.run_id, archived);
      setRuns((items) => items.map((item) => item.run_id === run.run_id ? { ...item, ...updated } : item));
      notify(archived ? "Run archived." : "Run restored to the active list.", "success");
    } catch (err) { notify(errorMessage(err)); }
    finally { setBusyId(""); }
  };

  const retry = async (run: RunRecord) => {
    setBusyId(run.run_id);
    try {
      const updated = await api.retryRun(run.run_id);
      setRuns((items) => items.map((item) => item.run_id === run.run_id ? { ...item, ...updated } : item));
      notify("Run resumed from its checkpoint.", "success");
    } catch (err) { notify(errorMessage(err)); }
    finally { setBusyId(""); }
  };

  return <section>
    <div className="page-header">
      <div><h1>Research runs</h1><p>Monitor the closed loop, resolve gates, and return to auditable outputs.</p></div>
      <div className="page-header-actions"><Button onClick={() => void load()} disabled={loading}>Refresh</Button></div>
    </div>

    <div className="run-summary" aria-label="Run summary">
      {([
        ["active", "Active", counts.active], ["attention", "Needs attention", counts.attention],
        ["done", "Completed", counts.done], ["failed", "Failed", counts.failed],
      ] as const).map(([key, label, count]) => <button key={key} className={`summary-card ${status === key ? "selected" : ""}`} onClick={() => setStatus(status === key ? "all" : key)} aria-pressed={status === key}><span>{label}</span><strong>{count}</strong></button>)}
    </div>

    <div className="card cockpit-table">
      <div className="dashboard-toolbar">
        <label className="search-field"><span className="sr-only">Search runs</span><input className="field" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search run ID, topic, or node…" /></label>
        <div className="segmented" aria-label="Archive filter"><button aria-pressed={!showArchived} onClick={() => setShowArchived(false)}>Active list</button><button aria-pressed={showArchived} onClick={() => setShowArchived(true)}>Archived</button></div>
        <span className="mono dashboard-count">{filtered.length} shown</span>
      </div>
      {error && <div className="alert alert-danger" style={{ margin: 12 }}>Could not load runs: {error} <Button onClick={() => void load()}>Retry</Button></div>}
      {loading && !runs.length ? <LoadingBlock label="Loading research runs…" /> : filtered.length === 0 ? <EmptyState>{showArchived ? "No archived runs." : "No runs match the current filters."}</EmptyState> : <>
        <div className="table-wrap desktop-run-table"><table className="data-table"><thead><tr><th>Run</th><th>Topic</th><th>Status</th><th>Current stage</th><th>Created</th><th>Elapsed</th><th><span className="sr-only">Actions</span></th></tr></thead><tbody>{filtered.map((run) => {
          const node = NODE_DEFS.find((item) => item.id === run.current_node);
          return <tr key={run.run_id}>
            <td><button className="run-link mono" onClick={() => openRun(run.run_id)}>{run.run_id}</button></td>
            <td><button className="topic-link" onClick={() => openRun(run.run_id)}>{run.topic}</button>{run.retry_count ? <small className="retry-note">retried {run.retry_count}×</small> : null}{run.review?.decision === "accept" ? <small className="cycle-note accepted">accepted</small> : run.revision_decision ? <small className="cycle-note">cycle {(run.iteration ?? 0) + 1} · {run.revision_decision.replaceAll("_", " ")}</small> : null}</td>
            <td><span className={`status-pill status-${run.status}`}>{statusLabel(run.status)}</span></td>
            <td className="muted">{run.status === "done" ? "Complete" : node?.label ?? "—"}</td>
            <td className="mono muted">{fmtAgo(run.created_at)}</td><td className="mono">{fmtElapsed(run)}</td>
            <td><div className="row-actions">{run.status === "failed" && run.retryable && !run.archived_at && <Button onClick={() => void retry(run)} disabled={busyId === run.run_id}>Retry</Button>}<Button variant="ghost" onClick={() => void archive(run, !run.archived_at)} disabled={busyId === run.run_id}>{run.archived_at ? "Restore" : "Archive"}</Button></div></td>
          </tr>;
        })}</tbody></table></div>
        <div className="mobile-run-list">{filtered.map((run) => <article className="run-card" key={run.run_id}><button className="run-card-main" onClick={() => openRun(run.run_id)}><span className="mono">{run.run_id}</span><strong>{run.topic}</strong><span className={`status-pill status-${run.status}`}>{statusLabel(run.status)}</span><small>{fmtAgo(run.created_at)} · {fmtElapsed(run)}{run.revision_decision ? ` · cycle ${(run.iteration ?? 0) + 1}` : ""}</small></button><div className="row-actions">{run.status === "failed" && run.retryable && !run.archived_at && <Button onClick={() => void retry(run)}>Retry</Button>}<Button variant="ghost" onClick={() => void archive(run, !run.archived_at)}>{run.archived_at ? "Restore" : "Archive"}</Button></div></article>)}</div>
      </>}
    </div>
  </section>;
}
