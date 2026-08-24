import { useMemo, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { Series } from "../types";

interface ChartLine { key: string; label: string; color: string; }

export function ScientificChart({ title, unit, series, lines }: { title: string; unit: string; series: Series | null; lines: ChartLine[] }) {
  const [showTable, setShowTable] = useState(false);
  const data = useMemo(() => {
    if (!series?.time) return [];
    return series.time.map((time, index) => Object.fromEntries([
      ["hours", time / 3600],
      ...lines.map((line) => [line.key, series[line.key]?.[index]]),
    ]));
  }, [lines, series]);
  const summaries = lines.map((line) => {
    const values = (series?.[line.key] ?? []).filter(Number.isFinite);
    return { ...line, min: values.length ? Math.min(...values) : null, max: values.length ? Math.max(...values) : null, last: values.at(-1) ?? null };
  });
  return <section className="card chart-card" aria-label={title}>
    <div className="chart-header"><div><strong>{title}</strong><span>{unit}</span></div><button className="btn btn-ghost" aria-expanded={showTable} onClick={() => setShowTable(!showTable)}>{showTable ? "Hide summary" : "Data summary"}</button></div>
    {data.length ? <div className="chart-area" role="img" aria-label={`${title}, ${data.length} time samples`}><ResponsiveContainer width="100%" height="100%"><LineChart data={data} accessibilityLayer margin={{ top: 8, right: 16, bottom: 4, left: 0 }}><CartesianGrid stroke="var(--border)" strokeDasharray="3 3" /><XAxis dataKey="hours" type="number" domain={["dataMin", "dataMax"]} tick={{ fill: "var(--text-muted)", fontSize: 10 }} tickFormatter={(value) => `${Number(value).toFixed(0)}h`} /><YAxis tick={{ fill: "var(--text-muted)", fontSize: 10 }} width={54} /><Tooltip contentStyle={{ background: "var(--surface-raised)", border: "1px solid var(--border)", borderRadius: 7, color: "var(--text)" }} labelFormatter={(value) => `${Number(value).toFixed(2)} hours`} /><Legend wrapperStyle={{ fontSize: 11 }} />{lines.map((line) => <Line key={line.key} dataKey={line.key} name={line.label} stroke={line.color} dot={false} strokeWidth={2} isAnimationActive={false} connectNulls />)}</LineChart></ResponsiveContainer></div> : <div className="empty-state">Series unavailable.</div>}
    {showTable && <table className="data-table chart-summary"><caption className="sr-only">Summary values for {title}</caption><thead><tr><th>Series</th><th>Minimum</th><th>Maximum</th><th>Final</th></tr></thead><tbody>{summaries.map((item) => <tr key={item.key}><td>{item.label}</td><td className="mono">{item.min?.toPrecision(5) ?? "—"}</td><td className="mono">{item.max?.toPrecision(5) ?? "—"}</td><td className="mono">{item.last?.toPrecision(5) ?? "—"}</td></tr>)}</tbody></table>}
  </section>;
}
