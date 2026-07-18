import { useState } from "react";

import { api } from "../api";
import { ACCENT } from "../theme";

const labelStyle = {
  display: "block", fontSize: 11, textTransform: "uppercase" as const, letterSpacing: 0.4,
  color: "#8a9099", fontWeight: 600, marginBottom: 6,
};

export function NewRun({ goDashboard, openRun }: { goDashboard: () => void; openRun: (id: string) => void }) {
  const [topic, setTopic] = useState("");
  const [draft, setDraft] = useState("");
  const [constraints, setConstraints] = useState<string[]>([]);
  const [auto, setAuto] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!topic.trim() || busy) return;
    setBusy(true);
    try {
      const { run_id } = await api.createRun(topic.trim(), constraints, auto);
      openRun(run_id);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section style={{ maxWidth: 620, margin: "8px auto 0" }}>
      <button onClick={goDashboard} style={{ background: "none", border: 0, color: "#6b7280", fontSize: 12, cursor: "pointer", padding: 0, marginBottom: 14 }}>
        &larr; Runs
      </button>
      <div style={{ background: "#fff", border: "1px solid #e4e7ea", borderRadius: 11, padding: "26px 28px" }}>
        <h1 style={{ fontSize: 18, fontWeight: 600, margin: "0 0 4px" }}>New research run</h1>
        <p style={{ color: "#6b7280", margin: "0 0 22px", fontSize: 12.5 }}>
          Kick off the closed-loop workflow. The graph pauses at two approval gates.
        </p>

        <label style={labelStyle}>Research topic</label>
        <input
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="e.g. Chilled-water setpoint optimization for GPU rooms"
          style={{ width: "100%", height: 38, border: "1px solid #d7dbdf", borderRadius: 7, padding: "0 12px", fontSize: 13, outline: "none", marginBottom: 18 }}
        />

        <label style={labelStyle}>Constraints</label>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
          {constraints.map((c, i) => (
            <span
              key={i}
              className="mono"
              style={{
                display: "inline-flex", alignItems: "center", gap: 6, background: "#ecfeff", color: "#0e7490",
                border: "1px solid #cff0f5", borderRadius: 6, padding: "4px 8px", fontSize: 11.5,
              }}
            >
              {c}
              <span
                onClick={() => setConstraints(constraints.filter((_, j) => j !== i))}
                style={{ cursor: "pointer", color: "#0891b2", fontWeight: 700 }}
              >
                ×
              </span>
            </span>
          ))}
        </div>
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && draft.trim()) {
              setConstraints([...constraints, draft.trim()]);
              setDraft("");
            }
          }}
          placeholder="Type a constraint, press Enter"
          style={{ width: "100%", height: 34, border: "1px solid #d7dbdf", borderRadius: 7, padding: "0 12px", fontSize: 12.5, outline: "none", marginBottom: 20 }}
        />

        <div
          onClick={() => setAuto(!auto)}
          style={{
            display: "flex", alignItems: "center", gap: 11, padding: "12px 14px", border: "1px solid #eceff1",
            borderRadius: 8, cursor: "pointer", marginBottom: 22, background: "#fafbfc",
          }}
        >
          <div style={{ width: 34, height: 19, borderRadius: 11, background: auto ? "#0891b2" : "#cfd4d9", position: "relative", transition: ".15s", flex: "0 0 auto" }}>
            <div style={{ position: "absolute", top: 2, left: auto ? 17 : 2, width: 15, height: 15, borderRadius: "50%", background: "#fff", transition: ".15s" }} />
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600, fontSize: 12.5 }}>Auto mode</div>
            <div style={{ color: "#8a9099", fontSize: 11.5 }}>Auto-resolve both gates (skip manual approval)</div>
          </div>
          <span className="mono" style={{ fontSize: 11, color: auto ? "#0891b2" : "#9aa1a9" }}>auto={String(auto)}</span>
        </div>

        <button
          onClick={submit}
          style={{
            width: "100%", height: 40, border: 0, borderRadius: 8,
            background: topic.trim() && !busy ? ACCENT : "#cbd0d5", color: "#fff",
            fontWeight: 600, fontSize: 13.5, cursor: topic.trim() && !busy ? "pointer" : "not-allowed",
          }}
        >
          {busy ? "Starting…" : "Start run →"}
        </button>
      </div>
    </section>
  );
}
