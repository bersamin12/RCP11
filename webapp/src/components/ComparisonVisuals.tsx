import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";

import { api, errorMessage } from "../api";
import { METRIC_DISPLAY, fmtMetric } from "../theme";
import type { ComparisonPair, ExperimentPlan, ExperimentResultSet, MetricComparison, Series } from "../types";
import { Alert } from "./UI";
import { ScientificChart } from "./ScientificChart";

const MODES = ["free_cooling_hours", "partial_mechanical_hours", "full_mechanical_hours"] as const;

function comparison(results: ExperimentResultSet, pairId: string, metric: string) {
  return results.comparisons.find((item) => item.pair_id === pairId && item.metric === metric);
}

function pairLabel(pair: ComparisonPair) { return pair.label || pair.id.replace(/^pair-/, ""); }

export function ComparisonVisuals({ runId, revisionId, plan, results }: { runId: string; revisionId?: string; plan: ExperimentPlan; results: ExperimentResultSet }) {
  const pairs = plan.comparison_pairs;
  const metrics = Array.from(new Set(results.comparisons.map((item) => item.metric)));
  const [metric, setMetric] = useState(metrics[0] ?? "");
  const [pairId, setPairId] = useState(pairs[0]?.id ?? "");
  const [trajectories, setTrajectories] = useState<Series | null>(null);
  const [seriesError, setSeriesError] = useState("");
  const selectedPair = pairs.find((item) => item.id === pairId) ?? pairs[0];

  useEffect(() => { if (!metrics.includes(metric)) setMetric(metrics[0] ?? ""); }, [metric, metrics]);
  useEffect(() => {
    if (!selectedPair) return;
    let active = true;
    setTrajectories(null); setSeriesError("");
    Promise.all([
      api.series(runId, selectedPair.baseline_case_id, revisionId),
      api.series(runId, selectedPair.candidate_case_id, revisionId),
    ]).then(([baseline, candidate]) => {
      if (!active) return;
      const temperatureKey = baseline.T_room_K ? "T_room_K" : "T";
      const count = Math.min(baseline.time?.length ?? 0, candidate.time?.length ?? 0);
      setTrajectories({
        time: (baseline.time ?? []).slice(0, count),
        baseline_temperature: (baseline[temperatureKey] ?? []).slice(0, count),
        candidate_temperature: (candidate[temperatureKey] ?? []).slice(0, count),
      });
    }).catch((err) => active && setSeriesError(errorMessage(err)));
    return () => { active = false; };
  }, [pairId, revisionId, runId, selectedPair?.baseline_case_id, selectedPair?.candidate_case_id]);

  const varyingFactors = useMemo(() => {
    const keys = Array.from(new Set(plan.cases.flatMap((item) => Object.keys(item.factor_values))));
    return keys.filter((key) => new Set(plan.cases.map((item) => item.factor_values[key])).size > 1).slice(0, 2);
  }, [plan.cases]);
  const heatmapRows = pairs.map((pair) => {
    const item = comparison(results, pair.id, metric);
    const planned = plan.cases.find((row) => row.id === pair.candidate_case_id) ?? plan.cases.find((row) => row.id === pair.baseline_case_id);
    return { pair, item, factors: planned?.factor_values ?? {} };
  }).filter((row) => row.item);
  const heatMagnitude = Math.max(...heatmapRows.map((row) => Math.abs(row.item?.percent_delta ?? 0)), 1);

  const energyMetric = metrics.includes("E_HVAC_kWh") ? "E_HVAC_kWh" : metrics[0];
  const thermalMetric = metrics.includes("T_room_peak_degC") ? "T_room_peak_degC" : metrics.find((item) => item !== energyMetric);
  const tradeoff = pairs.map((pair) => ({ pair, energy: comparison(results, pair.id, energyMetric), thermal: thermalMetric ? comparison(results, pair.id, thermalMetric) : undefined }))
    .filter((row) => row.energy && row.thermal).map((row) => ({ name: pairLabel(row.pair), x: row.energy!.candidate_value, y: row.thermal!.candidate_value }));

  const modes = selectedPair ? MODES.map((mode) => comparison(results, selectedPair.id, mode)).filter(Boolean) as MetricComparison[] : [];
  const modeData = modes.length === MODES.length ? [
    { configuration: "Baseline", free: modes[0].baseline_value, partial: modes[1].baseline_value, full: modes[2].baseline_value },
    { configuration: "Candidate", free: modes[0].candidate_value, partial: modes[1].candidate_value, full: modes[2].candidate_value },
  ] : [];

  if (!pairs.length || !metrics.length) return null;
  return <section className="comparison-visuals" aria-labelledby="comparison-visuals-heading">
    <div className="section-heading"><h2 id="comparison-visuals-heading">Decision visualisations</h2><span>Derived from approved comparisons</span></div>
    <div className="visual-grid">
      <section className="card visual-card">
        <div className="visual-heading"><div><h3>Comparison heatmap</h3><p>{varyingFactors.length === 2 ? `${varyingFactors[0]} × ${varyingFactors[1]}` : "Matched case matrix"}</p></div><label><span className="sr-only">Heatmap metric</span><select className="field" value={metric} onChange={(event) => setMetric(event.target.value)}>{metrics.map((item) => <option key={item}>{item}</option>)}</select></label></div>
        <div className="heatmap" role="img" aria-label={`${metric} candidate percentage change across ${heatmapRows.length} matched pairs`}>{heatmapRows.map((row) => { const delta = row.item?.percent_delta; const intensity = Math.abs(delta ?? 0) / heatMagnitude; const good = row.item?.candidate_better === true; return <div className="heatmap-cell" key={row.pair.id} style={{ background: `color-mix(in srgb, ${good ? "var(--success)" : row.item?.candidate_better === false ? "var(--danger)" : "var(--text-faint)"} ${Math.round(12 + intensity * 48)}%, var(--surface))` }}><b>{delta == null ? "—" : `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}%`}</b><small>{varyingFactors.map((factor) => `${factor} ${row.factors[factor]}`).join(" · ") || pairLabel(row.pair)}</small></div>; })}</div>
        <div className="table-wrap"><table className="data-table compact-table"><caption className="sr-only">Heatmap values for {metric}</caption><thead><tr><th>Pair</th>{varyingFactors.map((factor) => <th key={factor}>{factor}</th>)}<th>Change</th></tr></thead><tbody>{heatmapRows.map((row) => <tr key={row.pair.id}><td>{pairLabel(row.pair)}</td>{varyingFactors.map((factor) => <td className="mono" key={factor}>{row.factors[factor]}</td>)}<td className="mono">{row.item?.percent_delta?.toFixed(2) ?? "—"}%</td></tr>)}</tbody></table></div>
      </section>

      <section className="card visual-card">
        <div className="visual-heading"><div><h3>Candidate trade-off</h3><p>{energyMetric} versus {thermalMetric || "second metric"}</p></div></div>
        {tradeoff.length ? <div className="decision-chart" role="img" aria-label={`Trade-off plot for ${tradeoff.length} candidate cases`}><ResponsiveContainer width="100%" height="100%"><ScatterChart accessibilityLayer margin={{ top: 12, right: 18, bottom: 12, left: 6 }}><CartesianGrid stroke="var(--border)" /><XAxis type="number" dataKey="x" name={energyMetric} tick={{ fill: "var(--text-muted)", fontSize: 11 }} /><YAxis type="number" dataKey="y" name={thermalMetric} tick={{ fill: "var(--text-muted)", fontSize: 11 }} /><Tooltip cursor={{ strokeDasharray: "3 3" }} contentStyle={{ background: "var(--surface-raised)", border: "1px solid var(--border)" }} /><Scatter data={tradeoff} fill="var(--accent)" isAnimationActive={false} /></ScatterChart></ResponsiveContainer></div> : <p className="empty-inline">Two comparable metrics are required for a trade-off plot.</p>}
        {tradeoff.length > 0 && <table className="data-table compact-table"><caption className="sr-only">Trade-off plot values</caption><thead><tr><th>Pair</th><th>{energyMetric}</th><th>{thermalMetric}</th></tr></thead><tbody>{tradeoff.map((row) => <tr key={row.name}><td>{row.name}</td><td className="mono">{row.x}</td><td className="mono">{row.y}</td></tr>)}</tbody></table>}
      </section>
    </div>

    <div className="visual-toolbar"><label><span>Matched pair</span><select className="field" value={selectedPair?.id} onChange={(event) => setPairId(event.target.value)}>{pairs.map((pair) => <option value={pair.id} key={pair.id}>{pairLabel(pair)}</option>)}</select></label></div>
    {seriesError && <Alert tone="danger" title="Comparison trajectory unavailable">{seriesError}</Alert>}
    <div className="visual-grid">
      <ScientificChart title="Baseline and candidate room temperature" unit={trajectories?.baseline_temperature?.some((value) => value > 100) ? "K" : "°C"} series={trajectories} lines={[{ key: "baseline_temperature", label: "Baseline", color: "#667085" }, { key: "candidate_temperature", label: "Candidate", color: "#087f95" }]} />
      <section className="card visual-card"><div className="visual-heading"><div><h3>Cooling-mode allocation</h3><p>{selectedPair ? pairLabel(selectedPair) : "Selected pair"}</p></div></div>{modeData.length ? <><div className="decision-chart" role="img" aria-label="Baseline and candidate cooling mode hours"><ResponsiveContainer width="100%" height="100%"><BarChart data={modeData} accessibilityLayer><CartesianGrid stroke="var(--border)" /><XAxis dataKey="configuration" tick={{ fill: "var(--text-muted)", fontSize: 11 }} /><YAxis tick={{ fill: "var(--text-muted)", fontSize: 11 }} /><Tooltip contentStyle={{ background: "var(--surface-raised)", border: "1px solid var(--border)" }} /><Legend /><Bar dataKey="free" name="Free" stackId="m" fill="#16794a" /><Bar dataKey="partial" name="Partial mechanical" stackId="m" fill="#2457b2" /><Bar dataKey="full" name="Full mechanical" stackId="m" fill="#b42318" /></BarChart></ResponsiveContainer></div><table className="data-table compact-table"><caption className="sr-only">Cooling mode allocation in hours</caption><thead><tr><th>Configuration</th><th>Free</th><th>Partial</th><th>Full</th></tr></thead><tbody>{modeData.map((row) => <tr key={row.configuration}><td>{row.configuration}</td><td>{row.free.toFixed(2)}</td><td>{row.partial.toFixed(2)}</td><td>{row.full.toFixed(2)}</td></tr>)}</tbody></table></> : <p className="empty-inline">Cooling-mode metrics are not available for this plan.</p>}</section>
    </div>
  </section>;
}
