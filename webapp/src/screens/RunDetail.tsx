import { useEffect, useMemo, useState } from "react";

import { api, fmtElapsed, useRunRecord } from "../api";
import { ConfidenceBadge, PendingMessage, StatusBadge } from "../components/Badges";
import { LineChart } from "../components/LineChart";
import { Markdown } from "../components/Markdown";
import { ACCENT, NODE_DEFS, STAGES, METRIC_DISPLAY, fmtMetric, nodeIndex } from "../theme";
import type { Registry, Series } from "../types";

type TabKey = "papers" | "gaps" | "exp" | "results" | "report" | "claims";

export function RunDetail({ runId, goDashboard }: { runId: string; goDashboard: () => void }) {
  const record = useRunRecord(runId);
  const [tab, setTab] = useState<TabKey>("gaps");
  const [feedback, setFeedback] = useState("");
  const [series, setSeries] = useState<Series | null>(null);
  const [report, setReport] = useState("");
  const [registry, setRegistry] = useState<Registry>({});
  const [, tick] = useState(0);

  useEffect(() => {
    api.models().then(setRegistry).catch(() => {});
  }, []);

  // elapsed ticker while alive
  useEffect(() => {
    const t = window.setInterval(() => tick((x) => x + 1), 1000);
    return () => window.clearInterval(t);
  }, []);

  const state = record?.state ?? {};
  const status = record?.status ?? "running";

  // fetch series/report once available
  useEffect(() => {
    if (state.result_bundle?.status === "ok" && !series) api.series(runId).then(setSeries).catch(() => {});
    if (state.report_path && !report) api.report(runId).then(setReport).catch(() => {});
  }, [state.result_bundle?.status, state.report_path]); // eslint-disable-line react-hooks/exhaustive-deps

  const doneNodes = useMemo(() => new Set((record?.node_history ?? []).map((n) => n.node)), [record]);

  if (!record) return <PendingMessage>Loading run…</PendingMessage>;

  const currentIdx = nodeIndex(record.current_node);
  const spec = state.experiment_spec;
  const model = spec ? registry[spec.model_name] : undefined;

  const specRows = spec
    ? Object.entries(spec.parameters).map(([name, value]) => {
        const p = model?.parameters[name];
        return {
          name, value: String(value),
          desc: p?.description ?? "", range: p ? `${p.min}–${p.max} ${p.unit}` : "",
        };
      })
    : [];

  const answerGate = (answer: string) => {
    setFeedback("");
    api.answerGate(runId, answer).catch(() => {});
  };

  const gate = record.status === "waiting_gate" ? record.gate : null;

  const tabDefs: { key: TabKey; label: string; ready: boolean; count?: number }[] = [
    { key: "papers", label: "Papers", ready: !!state.paper_cards?.length, count: state.paper_cards?.length },
    { key: "gaps", label: "Gaps & Hypotheses", ready: !!state.hypotheses?.length, count: state.hypotheses?.length },
    { key: "exp", label: "Experiment", ready: !!spec },
    { key: "results", label: "Results", ready: !!state.result_bundle },
    { key: "report", label: "Report", ready: !!state.report_path },
    { key: "claims", label: "Claims", ready: !!state.claim_bundle, count: state.claim_bundle?.claims?.length },
  ];

  return (
    <section>
      <button onClick={goDashboard} style={{ background: "none", border: 0, color: "#6b7280", fontSize: 12, cursor: "pointer", padding: 0, marginBottom: 12 }}>
        &larr; Runs
      </button>

      <div style={{ display: "flex", alignItems: "flex-start", gap: 14, marginBottom: 16 }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 3 }}>
            <h1 style={{ fontSize: 17, fontWeight: 600, margin: 0 }}>{record.topic}</h1>
            <StatusBadge status={status} />
          </div>
          <div className="mono" style={{ display: "flex", gap: 14, alignItems: "center", fontSize: 11.5, color: "#8a9099" }}>
            <span>{record.run_id}</span>
            <span>·</span>
            <span>elapsed {fmtElapsed(record)}</span>
            <span>·</span>
            <span>{record.constraints.length ? record.constraints.join(" · ") : "no constraints"}</span>
          </div>
        </div>
      </div>

      {/* STEPPER */}
      <div style={{ background: "#fff", border: "1px solid #e4e7ea", borderRadius: 10, padding: "16px 14px 12px", marginBottom: 14, overflowX: "auto" }}>
        <div style={{ display: "flex", alignItems: "flex-start", minWidth: 880 }}>
          {NODE_DEFS.map((nd, i) => {
            const stg = STAGES[nd.stage];
            let st: "done" | "running" | "failed" | "pending" = "pending";
            if (doneNodes.has(nd.id) && i !== currentIdx) st = "done";
            if (i === currentIdx && (status === "running" || status === "waiting_gate")) st = "running";
            if (status === "failed" && i === currentIdx) st = "failed";
            if (status === "done" || (status === "stale" && doneNodes.size === 0)) st = status === "done" ? "done" : st;

            const base = {
              width: 26, height: 26, borderRadius: "50%", display: "flex", alignItems: "center",
              justifyContent: "center", fontSize: 11, fontWeight: 700, flex: "0 0 auto", zIndex: 1,
            } as const;
            let circle: React.CSSProperties = { ...base };
            let icon: React.ReactNode = nd.gate ? "◇" : i + 1;
            let labelColor = "#9aa1a9";
            if (st === "done") {
              circle = { ...base, background: stg.c, color: "#fff" };
              icon = "✓"; labelColor = "#374151";
            } else if (st === "running") {
              circle = { ...base, background: stg.bg, color: stg.c, border: `2px solid ${stg.c}`, boxShadow: `0 0 0 4px ${stg.c}22`, animation: "pulse 1.2s infinite" };
              icon = nd.gate ? "!" : i + 1; labelColor = stg.c;
            } else if (st === "failed") {
              circle = { ...base, background: "#fef2f2", color: "#dc2626", border: "2px solid #dc2626" };
              icon = "✕"; labelColor = "#b91c1c";
            } else {
              circle = { ...base, background: "#fff", color: "#b0b6bd", border: "1.5px solid #e0e3e6" };
            }
            const prevDone = i > 0 && doneNodes.has(NODE_DEFS[i - 1].id);
            const line = (done: boolean): React.CSSProperties => ({ flex: 1, height: 2, background: done ? stg.c : "#e8ebed" });
            return (
              <div key={nd.id} style={{ display: "flex", flexDirection: "column", alignItems: "center", flex: 1, position: "relative" }}>
                <div style={{ display: "flex", alignItems: "center", width: "100%" }}>
                  <div style={i === 0 ? { flex: 1, height: 2, background: "transparent" } : line(prevDone)} />
                  <div style={circle}>{icon}</div>
                  <div style={i === NODE_DEFS.length - 1 ? { flex: 1, height: 2, background: "transparent" } : line(st === "done")} />
                </div>
                <div style={{ marginTop: 7, textAlign: "center", padding: "0 4px" }}>
                  <div style={{ fontSize: 11, fontWeight: 600, lineHeight: 1.15, color: labelColor }}>{nd.label}</div>
                  <div className="mono" style={{ fontSize: 9, color: "#aab0b7", marginTop: 2 }}>{nd.id}</div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* FAILURE BANNER */}
      {status === "failed" && record.error && (
        <div style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 10, padding: "12px 16px", marginBottom: 14, fontSize: 12, color: "#b91c1c" }}>
          <b>Run failed · </b>
          <span className="mono">{record.error.slice(0, 400)}</span>
        </div>
      )}

      {/* GATE 1 */}
      {gate?.gate === "hypothesis_selection" && (
        <div style={{ background: "#fffbeb", border: "1px solid #fcd34d", borderRadius: 10, padding: "16px 18px", marginBottom: 14 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3 }}>
            <span className="mono" style={{ fontSize: 10, fontWeight: 700, color: "#b45309", background: "#fef3c7", padding: "2px 7px", borderRadius: 5, letterSpacing: 0.5 }}>GATE 1</span>
            <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600, color: "#92400e" }}>Hypothesis selection</h3>
          </div>
          <p style={{ margin: "0 0 13px", color: "#a16207", fontSize: 12.5 }}>Which hypothesis should we compile into an experiment?</p>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 11 }}>
            {(state.hypotheses ?? []).map((h, i) => (
              <div key={h.id} style={{ background: "#fff", border: "1px solid #f0e0b0", borderRadius: 9, padding: "13px 14px", display: "flex", flexDirection: "column", gap: 8 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                  <span className="mono" style={{ fontSize: 11, fontWeight: 700, color: "#1d4ed8" }}>{h.id}</span>
                </div>
                <div style={{ fontWeight: 600, fontSize: 12.5, lineHeight: 1.35 }}>{h.statement}</div>
                <div style={{ fontSize: 11.5, color: "#6b7280", lineHeight: 1.4 }}>{h.rationale}</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 11, color: "#4b5563" }}>
                  <div><span style={{ color: "#9aa1a9" }}>expect · </span>{h.expected_effect || "—"}</div>
                  <div><span style={{ color: "#9aa1a9" }}>risks · </span>{h.risks?.join(", ") || "—"}</div>
                </div>
                <button
                  onClick={() => answerGate(String(i))}
                  style={{ marginTop: "auto", height: 30, border: 0, borderRadius: 6, background: "#1d4ed8", color: "#fff", fontWeight: 600, fontSize: 12, cursor: "pointer" }}
                >
                  Select {h.id}
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* GATE 2 */}
      {gate?.gate === "spec_approval" && spec && (
        <div style={{ background: "#fffbeb", border: "1px solid #fcd34d", borderRadius: 10, padding: "16px 18px", marginBottom: 14 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3 }}>
            <span className="mono" style={{ fontSize: 10, fontWeight: 700, color: "#b45309", background: "#fef3c7", padding: "2px 7px", borderRadius: 5, letterSpacing: 0.5 }}>GATE 2</span>
            <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600, color: "#92400e" }}>Experiment spec approval</h3>
            <span className="mono" style={{ marginLeft: "auto", fontSize: 11, color: "#a16207" }}>attempt {state.spec_attempts ?? 1} of 3</span>
          </div>
          <p style={{ margin: "0 0 12px", color: "#a16207", fontSize: 12.5 }}>
            Approve this experiment specification, or request changes to route back to spec_compile.
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 16 }}>
            <div style={{ background: "#fff", border: "1px solid #f0e0b0", borderRadius: 9, overflow: "hidden" }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 88px 118px", padding: "7px 12px", background: "#fafbfc", borderBottom: "1px solid #eceff1", fontSize: 10, textTransform: "uppercase", letterSpacing: 0.4, color: "#9aa1a9", fontWeight: 600 }}>
                <div>Parameter</div><div style={{ textAlign: "right" }}>Value</div><div style={{ textAlign: "right" }}>Range · unit</div>
              </div>
              {specRows.map((p) => (
                <div key={p.name} style={{ display: "grid", gridTemplateColumns: "1fr 88px 118px", padding: "8px 12px", borderBottom: "1px solid #f4f5f6", alignItems: "center" }}>
                  <div>
                    <div className="mono" style={{ fontSize: 11.5, fontWeight: 500 }}>{p.name}</div>
                    <div style={{ fontSize: 10, color: "#9aa1a9" }}>{p.desc}</div>
                  </div>
                  <div className="mono" style={{ textAlign: "right", fontSize: 12, fontWeight: 600, color: "#0f766e" }}>{p.value}</div>
                  <div className="mono" style={{ textAlign: "right", fontSize: 10.5, color: "#9aa1a9" }}>{p.range}</div>
                </div>
              ))}
              <div className="mono" style={{ display: "flex", gap: 16, padding: "9px 12px", background: "#fafbfc", fontSize: 11 }}>
                <span style={{ color: "#9aa1a9" }}>stop_time <span style={{ color: "#4b5563" }}>{spec.stop_time}s</span></span>
                <span style={{ color: "#9aa1a9" }}>intervals <span style={{ color: "#4b5563" }}>{spec.intervals}</span></span>
                <span style={{ color: "#9aa1a9" }}>model <span style={{ color: "#4b5563" }}>{spec.model_name}</span></span>
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column" }}>
              <div style={{ fontSize: 11.5, color: "#6b7280", lineHeight: 1.45, marginBottom: 10 }}>{spec.description}</div>
              <button
                onClick={() => answerGate("yes")}
                style={{ height: 34, border: 0, borderRadius: 7, background: "#16a34a", color: "#fff", fontWeight: 600, fontSize: 12.5, cursor: "pointer", marginBottom: 12 }}
              >
                Approve &amp; run simulation
              </button>
              <label style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.4, color: "#8a9099", fontWeight: 600, marginBottom: 5 }}>Request changes</label>
              <textarea
                className="amber"
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                placeholder="Describe the revision — routes back to spec_compile"
                style={{ flex: 1, minHeight: 64, border: "1px solid #d7dbdf", borderRadius: 7, padding: "8px 10px", fontSize: 12, resize: "vertical", outline: "none", marginBottom: 9 }}
              />
              <button
                onClick={() => feedback.trim() && answerGate(feedback.trim())}
                style={{ height: 30, border: "1px solid #e0c48a", borderRadius: 7, background: "#fff", color: "#b45309", fontWeight: 600, fontSize: 12, cursor: "pointer" }}
              >
                Reject &amp; revise &rarr;
              </button>
            </div>
          </div>
        </div>
      )}

      {/* TABS */}
      <div style={{ display: "flex", gap: 3, borderBottom: "1px solid #e4e7ea", marginBottom: 16 }}>
        {tabDefs.map((t) => {
          const on = tab === t.key;
          return (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              style={{
                position: "relative", height: 34, padding: "0 13px", border: 0, background: "none",
                fontSize: 12.5, fontWeight: on ? 600 : 500,
                color: on ? "#0e7490" : t.ready ? "#4b5563" : "#b0b6bd",
                cursor: "pointer", borderBottom: `2px solid ${on ? ACCENT : "transparent"}`,
                display: "flex", alignItems: "center", gap: 6,
              }}
            >
              {t.label}
              {!!t.count && (
                <span className="mono" style={{ fontSize: 10, background: on ? "#ecfeff" : "#f1f3f4", color: on ? "#0e7490" : "#8a9099", padding: "0 5px", borderRadius: 8 }}>
                  {t.count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      <div style={{ minHeight: 180 }}>
        {tab === "papers" &&
          (state.paper_cards?.length ? (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 11 }}>
              {state.paper_cards.map((p) => (
                <div key={p.id} style={{ background: "#fff", border: "1px solid #e4e7ea", borderRadius: 9, padding: "13px 15px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 10, marginBottom: 5 }}>
                    <div style={{ fontWeight: 600, fontSize: 12.5, lineHeight: 1.35 }}>{p.title}</div>
                    <span className="mono" style={{ fontSize: 11, color: "#8a9099", whiteSpace: "nowrap" }}>{p.year ?? "—"}</span>
                  </div>
                  <div style={{ fontSize: 11, color: "#8a9099", marginBottom: 8 }}>
                    {p.authors.slice(0, 3).join(", ")} · {p.venue ?? "—"} · {p.citations} cites
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 11.5, color: "#4b5563", lineHeight: 1.4 }}>
                    <div><span style={{ color: "#0e7490", fontWeight: 600 }}>problem </span>{p.problem}</div>
                    <div><span style={{ color: "#0f766e", fontWeight: 600 }}>method </span>{p.method}</div>
                    <div><span style={{ color: "#b45309", fontWeight: 600 }}>limits </span>{p.limitations.join("; ") || "—"}</div>
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginTop: 9 }}>
                    {p.tags.map((t) => (
                      <span key={t} className="mono" style={{ fontSize: 10, background: "#f1f3f4", color: "#6b7280", padding: "2px 6px", borderRadius: 4 }}>{t}</span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <PendingMessage>Papers appear after <span className="mono">research_memory_build</span> completes.</PendingMessage>
          ))}

        {tab === "gaps" &&
          (state.hypotheses?.length ? (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1.2fr", gap: 16 }}>
              <div>
                <h3 style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: 0.4, color: "#0e7490", margin: "0 0 9px" }}>Research gaps</h3>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {(state.gaps ?? []).map((g, i) => (
                    <div key={i} style={{ background: "#fff", border: "1px solid #e4e7ea", borderLeft: "3px solid #0891b2", borderRadius: 7, padding: "10px 13px", fontSize: 12, lineHeight: 1.4, color: "#374151" }}>
                      {g}
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <h3 style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: 0.4, color: "#1d4ed8", margin: "0 0 9px" }}>Hypotheses</h3>
                <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
                  {state.hypotheses.map((h) => {
                    const selected = state.selected_hypothesis?.id === h.id;
                    return (
                      <div
                        key={h.id}
                        style={{
                          background: "#fff", border: `1px solid ${selected ? "#93c5fd" : "#e4e7ea"}`,
                          borderRadius: 9, padding: "12px 14px",
                          boxShadow: selected ? "0 0 0 3px #2563eb18" : "none",
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5 }}>
                          <span className="mono" style={{ fontSize: 11, fontWeight: 700, color: "#1d4ed8" }}>{h.id}</span>
                          {selected && (
                            <span className="mono" style={{ fontSize: 9.5, fontWeight: 700, color: "#15803d", background: "#dcfce7", padding: "1px 6px", borderRadius: 4 }}>SELECTED</span>
                          )}
                        </div>
                        <div style={{ fontWeight: 600, fontSize: 12.5, lineHeight: 1.35, marginBottom: 5 }}>{h.statement}</div>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                          {h.variables.map((v) => (
                            <span key={v} className="mono" style={{ fontSize: 10, background: "#eff6ff", color: "#1d4ed8", padding: "2px 6px", borderRadius: 4 }}>{v}</span>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          ) : (
            <PendingMessage>Gaps &amp; hypotheses appear after <span className="mono">hypothesis_gen</span>.</PendingMessage>
          ))}

        {tab === "exp" &&
          (spec ? (
            <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 16 }}>
              <div style={{ background: "#fff", border: "1px solid #e4e7ea", borderRadius: 9, overflow: "hidden" }}>
                <div style={{ padding: "10px 14px", borderBottom: "1px solid #eceff1", display: "flex", alignItems: "center", gap: 9 }}>
                  <span className="mono" style={{ fontSize: 11.5, fontWeight: 600, color: "#0f766e" }}>{spec.model_name}</span>
                  <span className="mono" style={{ fontSize: 10.5, color: "#9aa1a9" }}>{spec.id}</span>
                </div>
                {specRows.map((p) => (
                  <div key={p.name} style={{ display: "grid", gridTemplateColumns: "1fr 96px 120px", padding: "8px 14px", borderBottom: "1px solid #f4f5f6", alignItems: "center" }}>
                    <div>
                      <div className="mono" style={{ fontSize: 11.5, fontWeight: 500 }}>{p.name}</div>
                      <div style={{ fontSize: 10, color: "#9aa1a9" }}>{p.desc}</div>
                    </div>
                    <div className="mono" style={{ textAlign: "right", fontSize: 12, fontWeight: 600, color: "#0f766e" }}>{p.value}</div>
                    <div className="mono" style={{ textAlign: "right", fontSize: 10.5, color: "#9aa1a9" }}>{p.range}</div>
                  </div>
                ))}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
                <div style={{ background: "#fff", border: "1px solid #e4e7ea", borderRadius: 9, padding: "13px 15px" }}>
                  <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.4, color: "#8a9099", marginBottom: 7 }}>Run status</div>
                  <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
                    <StatusBadge status={state.result_bundle ? (state.result_bundle.status === "ok" ? "done" : "failed") : "running"} />
                    <span className="mono" style={{ fontSize: 11, color: "#8a9099" }}>stop {spec.stop_time}s · {spec.intervals} pts</span>
                  </div>
                </div>
                {state.result_bundle?.status === "failed" && (
                  <div style={{ background: "#1a1d21", borderRadius: 9, padding: "13px 15px", overflow: "auto" }}>
                    <div className="mono" style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: 0.4, color: "#f87171", marginBottom: 7 }}>log excerpt · run.mos</div>
                    <pre className="mono" style={{ margin: 0, fontSize: 11, color: "#e5e7eb", whiteSpace: "pre-wrap", lineHeight: 1.5 }}>{state.result_bundle.log_excerpt}</pre>
                  </div>
                )}
                <div style={{ background: "#fff", border: "1px solid #e4e7ea", borderRadius: 9, padding: "13px 15px", fontSize: 11.5, color: "#6b7280", lineHeight: 1.45 }}>
                  {spec.description || "No description."}
                </div>
              </div>
            </div>
          ) : (
            <PendingMessage>The spec appears after <span className="mono">spec_compile</span>.</PendingMessage>
          ))}

        {tab === "results" &&
          (state.result_bundle?.status === "ok" ? (
            <div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 10, marginBottom: 14 }}>
                {Object.entries(state.result_bundle.metrics).map(([key, value]) => {
                  const d = METRIC_DISPLAY[key] ?? { unit: "", label: key, color: "#4b5563" };
                  return (
                    <div key={key} style={{ background: "#fff", border: "1px solid #e4e7ea", borderRadius: 9, padding: "12px 14px" }}>
                      <div className="mono" style={{ fontSize: 10, color: "#9aa1a9", marginBottom: 4 }}>{key}</div>
                      <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
                        <span className="mono" style={{ fontSize: 21, fontWeight: 600, color: d.color }}>{fmtMetric(key, value)}</span>
                        <span className="mono" style={{ fontSize: 11, color: "#8a9099" }}>{d.unit}</span>
                      </div>
                      <div style={{ fontSize: 10.5, color: "#8a9099", marginTop: 3 }}>{d.label}</div>
                    </div>
                  );
                })}
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <ChartCard title="Room temperature T" color="#dc2626" unit="°C" series={series} column="T" />
                <ChartCard title="Cooling power P_cool" color="#0f766e" unit="W" series={series} column="P_cool" />
              </div>
            </div>
          ) : (
            <PendingMessage>Metrics &amp; charts appear after <span className="mono">run_modelica</span> &amp; <span className="mono">analyze_results</span>.</PendingMessage>
          ))}

        {tab === "report" &&
          (report ? (
            <div style={{ display: "flex", justifyContent: "center" }}>
              <div style={{ background: "#fff", border: "1px solid #e4e7ea", borderRadius: 10, padding: "34px 44px", maxWidth: 720, width: "100%" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                  <span className="mono" style={{ fontSize: 10.5, color: "#9aa1a9" }}>data/runs/{runId}/report.md</span>
                  <span className="mono" style={{ fontSize: 10.5, color: "#0e7490" }}>markdown</span>
                </div>
                <Markdown source={report} />
              </div>
            </div>
          ) : (
            <PendingMessage>The report appears after <span className="mono">draft_report</span>.</PendingMessage>
          ))}

        {tab === "claims" &&
          (state.claim_bundle ? (
            <div style={{ maxWidth: 820 }}>
              {state.claim_bundle.summary && (
                <div style={{ background: "#f5f3ff", border: "1px solid #e5deff", borderRadius: 9, padding: "13px 16px", marginBottom: 12, fontSize: 12.5, color: "#5b21b6", lineHeight: 1.5 }}>
                  <span style={{ fontWeight: 600 }}>Summary · </span>
                  {state.claim_bundle.summary}
                </div>
              )}
              <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
                {state.claim_bundle.claims.map((c, i) => (
                  <div key={i} style={{ background: "#fff", border: "1px solid #e4e7ea", borderRadius: 9, padding: "13px 16px", display: "flex", gap: 14, alignItems: "flex-start" }}>
                    <ConfidenceBadge level={c.confidence} />
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: 600, fontSize: 12.5, lineHeight: 1.4, marginBottom: 4 }}>{c.statement}</div>
                      <div style={{ fontSize: 11.5, color: "#6b7280", lineHeight: 1.45 }}>
                        <span className="mono" style={{ color: "#7c3aed" }}>evidence · </span>
                        {c.evidence}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <PendingMessage>Claims appear after <span className="mono">analyze_results</span>.</PendingMessage>
          ))}
      </div>
    </section>
  );
}

function ChartCard({ title, color, unit, series, column }: { title: string; color: string; unit: string; series: Series | null; column: string }) {
  return (
    <div style={{ background: "#fff", border: "1px solid #e4e7ea", borderRadius: 9, padding: "14px 12px 10px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "0 4px", marginBottom: 6 }}>
        <span style={{ width: 12, height: 2.5, background: color, borderRadius: 2 }} />
        <span style={{ fontSize: 12, fontWeight: 600 }}>{title}</span>
        <span className="mono" style={{ fontSize: 10.5, color: "#9aa1a9", marginLeft: "auto" }}>{unit} vs time</span>
      </div>
      {series?.[column] ? (
        <LineChart time={series.time ?? []} values={series[column]} color={color} unit={unit} />
      ) : (
        <div style={{ padding: 30, textAlign: "center", color: "#9aa1a9", fontSize: 12 }}>loading series…</div>
      )}
    </div>
  );
}
