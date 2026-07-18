import { useEffect, useState } from "react";

import { api, fmtAgo, fmtElapsed } from "../api";
import { StatusBadge } from "../components/Badges";
import { NODE_DEFS, STAGES } from "../theme";
import type { RunRecord } from "../types";

const GRID = "118px 1fr 128px 168px 96px 78px";

export function Dashboard({ openRun }: { openRun: (id: string) => void }) {
  const [runs, setRuns] = useState<RunRecord[]>([]);

  useEffect(() => {
    let alive = true;
    const load = () => api.listRuns().then((r) => alive && setRuns(r)).catch(() => {});
    load();
    const t = window.setInterval(load, 2000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, []);

  const legend = [
    { label: "running", color: "#2563eb" },
    { label: "gate", color: "#d97706" },
    { label: "done", color: "#16a34a" },
    { label: "failed", color: "#dc2626" },
  ];

  return (
    <section>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 14 }}>
        <h1 style={{ fontSize: 18, fontWeight: 600, margin: 0 }}>Runs</h1>
        <span className="mono" style={{ fontSize: 11, color: "#8a9099" }}>{runs.length} total</span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 14 }}>
          {legend.map((lg) => (
            <span key={lg.label} style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11, color: "#6b7280" }}>
              <span style={{ width: 8, height: 8, borderRadius: 2, background: lg.color }} />
              {lg.label}
            </span>
          ))}
        </div>
      </div>
      <div style={{ background: "#fff", border: "1px solid #e4e7ea", borderRadius: 9, overflowX: "auto" }}>
       <div style={{ minWidth: 760 }}>
        <div
          style={{
            display: "grid", gridTemplateColumns: GRID, padding: "8px 14px", background: "#fafbfc",
            borderBottom: "1px solid #eceff1", fontSize: 10.5, textTransform: "uppercase",
            letterSpacing: 0.4, color: "#9aa1a9", fontWeight: 600,
          }}
        >
          <div>Run ID</div><div>Topic</div><div>Status</div><div>Current node</div><div>Created</div>
          <div style={{ textAlign: "right" }}>Elapsed</div>
        </div>
        {runs.map((r) => {
          const nodeDef =
            NODE_DEFS.find((n) => n.id === r.current_node) ??
            (r.status === "done" || r.status === "stale" ? NODE_DEFS[NODE_DEFS.length - 1] : NODE_DEFS[0]);
          const stage = STAGES[nodeDef.stage];
          return (
            <div
              key={r.run_id}
              className="rowhover"
              onClick={() => openRun(r.run_id)}
              style={{
                display: "grid", gridTemplateColumns: GRID, padding: "11px 14px",
                borderBottom: "1px solid #f1f3f4", cursor: "pointer", alignItems: "center",
              }}
            >
              <div className="mono" style={{ fontSize: 11.5, color: "#0e7490", fontWeight: 500 }}>{r.run_id}</div>
              <div style={{ fontWeight: 500, paddingRight: 14, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {r.topic}
              </div>
              <div><StatusBadge status={r.status} /></div>
              <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                <span style={{ width: 7, height: 7, borderRadius: 2, background: stage.c, flex: "0 0 auto" }} />
                <span className="mono" style={{ fontSize: 11, color: "#4b5563", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {r.status === "done" || r.status === "stale" ? "—" : nodeDef.label}
                </span>
              </div>
              <div className="mono" style={{ fontSize: 11, color: "#8a9099" }}>{fmtAgo(r.created_at)}</div>
              <div className="mono" style={{ fontSize: 11.5, color: "#4b5563", textAlign: "right" }}>{fmtElapsed(r)}</div>
            </div>
          );
        })}
        {runs.length === 0 && (
          <div style={{ padding: 26, textAlign: "center", color: "#9aa1a9", fontSize: 12.5 }}>
            No runs yet — start one with <b>New Run</b>.
          </div>
        )}
       </div>
      </div>
    </section>
  );
}
