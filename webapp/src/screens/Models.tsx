import { useEffect, useMemo, useState } from "react";

import { api } from "../api";
import { LineChart } from "../components/LineChart";
import { ACCENT, METRIC_DISPLAY, fmtMetric } from "../theme";
import type { Registry, ResultBundle, Series } from "../types";

function niceStep(min: number, max: number): number {
  const raw = (max - min) / 100;
  const mag = Math.pow(10, Math.floor(Math.log10(raw || 1)));
  return Math.max(mag, Math.round(raw / mag) * mag);
}

export function Models() {
  const [registry, setRegistry] = useState<Registry>({});
  const [modelName, setModelName] = useState<string>("");
  const [vals, setVals] = useState<Record<string, number>>({});
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<ResultBundle | null>(null);
  const [series, setSeries] = useState<Series | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.models().then((r) => {
      setRegistry(r);
      const first = Object.keys(r)[0];
      if (first) {
        setModelName(first);
        setVals(Object.fromEntries(Object.entries(r[first].parameters).map(([k, p]) => [k, p.default])));
      }
    }).catch(() => {});
  }, []);

  const model = registry[modelName];
  const params = useMemo(() => Object.entries(model?.parameters ?? {}), [model]);

  const run = async () => {
    if (!model || running) return;
    setRunning(true);
    setError("");
    try {
      const bundle = await api.simulate(modelName, vals);
      setResult(bundle);
      const s = await api.series(bundle.spec_id);
      setSeries(s);
    } catch (err) {
      setError(String(err).slice(0, 400));
      setResult(null);
    } finally {
      setRunning(false);
    }
  };

  if (!model) return null;
  const keyMetrics = result ? ["T_peak_degC", "E_cool_kWh", "P_cool_avg_W"].filter((k) => k in result.metrics) : [];

  return (
    <section>
      <h1 style={{ fontSize: 18, fontWeight: 600, margin: "0 0 14px" }}>Models &amp; simulations</h1>
      <div style={{ display: "grid", gridTemplateColumns: "1.15fr 1fr", gap: 16, alignItems: "start" }}>
        <div style={{ background: "#fff", border: "1px solid #e4e7ea", borderRadius: 10, overflow: "hidden" }}>
          <div style={{ padding: "12px 16px", borderBottom: "1px solid #eceff1" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
              <span className="mono" style={{ fontSize: 13, fontWeight: 600, color: "#0f766e" }}>{modelName}</span>
            </div>
            <div style={{ fontSize: 11.5, color: "#6b7280", marginTop: 3, lineHeight: 1.4 }}>{model.description}</div>
            <div className="mono" style={{ fontSize: 10.5, color: "#9aa1a9", marginTop: 6 }}>
              outputs: {model.outputs.join(", ")} · default stop {model.default_stop_time}s
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 76px 84px 128px", padding: "7px 16px", background: "#fafbfc", borderBottom: "1px solid #eceff1", fontSize: 10, textTransform: "uppercase", letterSpacing: 0.4, color: "#9aa1a9", fontWeight: 600 }}>
            <div>Parameter</div><div style={{ textAlign: "right" }}>Default</div><div style={{ textAlign: "right" }}>Unit</div><div style={{ textAlign: "right" }}>Range</div>
          </div>
          {params.map(([name, p]) => (
            <div key={name} style={{ display: "grid", gridTemplateColumns: "1fr 76px 84px 128px", padding: "8px 16px", borderBottom: "1px solid #f4f5f6", alignItems: "center" }}>
              <div>
                <div className="mono" style={{ fontSize: 11.5, fontWeight: 500 }}>{name}</div>
                <div style={{ fontSize: 10, color: "#9aa1a9" }}>{p.description}</div>
              </div>
              <div className="mono" style={{ textAlign: "right", fontSize: 12, color: "#4b5563" }}>{p.default}</div>
              <div className="mono" style={{ textAlign: "right", fontSize: 11, color: "#8a9099" }}>{p.unit}</div>
              <div className="mono" style={{ textAlign: "right", fontSize: 11, color: "#9aa1a9" }}>{p.min}–{p.max}</div>
            </div>
          ))}
        </div>

        <div style={{ background: "#fff", border: "1px solid #e4e7ea", borderRadius: 10, padding: "16px 18px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
            <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>Quick simulate</h3>
            <span className="mono" style={{ fontSize: 10.5, color: "#9aa1a9" }}>POST /api/simulations</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 13, marginBottom: 16 }}>
            {params.map(([name, p]) => (
              <div key={name}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 4 }}>
                  <span className="mono" style={{ fontSize: 11.5, fontWeight: 500 }}>{name}</span>
                  <span className="mono" style={{ fontSize: 11.5, fontWeight: 600, color: "#0f766e" }}>
                    {vals[name]} <span style={{ color: "#9aa1a9", fontWeight: 400 }}>{p.unit}</span>
                  </span>
                </div>
                <input
                  type="range"
                  min={p.min}
                  max={p.max}
                  step={niceStep(p.min, p.max)}
                  value={vals[name] ?? p.default}
                  onChange={(e) => setVals({ ...vals, [name]: parseFloat(e.target.value) })}
                  style={{ width: "100%", accentColor: ACCENT, height: 4 }}
                />
              </div>
            ))}
          </div>
          <button
            onClick={run}
            style={{
              width: "100%", height: 36, border: 0, borderRadius: 7,
              background: running ? "#94d3df" : ACCENT, color: "#fff",
              fontWeight: 600, fontSize: 12.5, cursor: running ? "wait" : "pointer",
            }}
          >
            {running ? "Running OpenModelica…" : "Run simulation →"}
          </button>
          {error && (
            <div className="mono" style={{ marginTop: 10, fontSize: 11, color: "#b91c1c", whiteSpace: "pre-wrap" }}>{error}</div>
          )}

          {result && (
            <div style={{ marginTop: 16, borderTop: "1px solid #eceff1", paddingTop: 14 }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8, marginBottom: 12 }}>
                {keyMetrics.map((key) => {
                  const d = METRIC_DISPLAY[key] ?? { unit: "", label: key, color: "#4b5563" };
                  return (
                    <div key={key} style={{ background: "#fafbfc", border: "1px solid #eceff1", borderRadius: 7, padding: "9px 11px" }}>
                      <div className="mono" style={{ fontSize: 9.5, color: "#9aa1a9" }}>{key}</div>
                      <div className="mono" style={{ fontSize: 16, fontWeight: 600, color: d.color }}>
                        {fmtMetric(key, result.metrics[key])}
                        <span style={{ fontSize: 9.5, color: "#8a9099", fontWeight: 400 }}> {d.unit}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
              {series?.T && <LineChart time={series.time ?? []} values={series.T} color="#dc2626" unit="°C" />}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
