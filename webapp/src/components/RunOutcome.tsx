import type { RunOutcome as RunOutcomeType } from "../types";
import { METRIC_DISPLAY, fmtMetric } from "../theme";

export function RunOutcome({ outcome, claims = 0 }: { outcome: RunOutcomeType; claims?: number }) {
  const tokens = outcome.token_usage.total_tokens;
  return <div className="outcome-layout">
    <section className="card outcome-finding">
      <span className="outcome-eyebrow">Primary reviewed finding</span>
      <h2>{outcome.primary_finding}</h2>
      <div className="outcome-meta">
        <span className={`quality-badge quality-${outcome.quality_status}`}>{outcome.quality_status}</span>
        <span>{claims} supported claim{claims === 1 ? "" : "s"}</span>
        <span>{outcome.elapsed_seconds == null ? "duration pending" : `${outcome.elapsed_seconds.toFixed(1)} s elapsed`}</span>
        <span>{tokens == null ? "token usage unavailable" : `${tokens.toLocaleString()} tokens`}</span>
      </div>
    </section>
    <aside className="card outcome-next"><span className="outcome-eyebrow">Next action</span><p>{outcome.next_action}</p></aside>
    {outcome.metrics.length > 0 && <section className="outcome-metrics" aria-label="Metric outcomes">{outcome.metrics.slice(0, 4).map((metric) => {
      const display = METRIC_DISPLAY[metric.metric];
      return <article className="card outcome-metric" key={metric.metric}><span>{display?.label ?? metric.metric}</span><strong>{metric.median_percent_delta == null ? "—" : `${metric.median_percent_delta >= 0 ? "+" : ""}${fmtMetric(metric.metric, metric.median_percent_delta)}%`}</strong><small>{metric.wins} better · {metric.losses} worse · {metric.ties} neutral</small></article>;
    })}</section>}
    {outcome.qualifications.length > 0 && <details className="card outcome-qualifications"><summary>{outcome.qualifications.length} qualification{outcome.qualifications.length === 1 ? "" : "s"} affect interpretation</summary><ul>{outcome.qualifications.map((item) => <li key={item}>{item}</li>)}</ul></details>}
  </div>;
}
