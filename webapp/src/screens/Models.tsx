import { useEffect, useMemo, useState } from "react";

import { api, errorMessage } from "../api";
import { CredibilityBadge, WarningBanner } from "../components/Credibility";
import { LineChart } from "../components/LineChart";
import { Alert, Button, EmptyState, LoadingBlock } from "../components/UI";
import { METRIC_DISPLAY, fmtMetric } from "../theme";
import type { ModelValidationReport, Registry, ResultBundle, Series } from "../types";

function niceStep(min: number, max: number): number {
  const raw = (max - min) / 100;
  const magnitude = Math.pow(10, Math.floor(Math.log10(raw || 1)));
  return Math.max(magnitude, Math.round(raw / magnitude) * magnitude);
}

export function Models() {
  const [registry, setRegistry] = useState<Registry>({});
  const [modelName, setModelName] = useState("");
  const [values, setValues] = useState<Record<string, number>>({});
  const [stopTime, setStopTime] = useState(0);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<ResultBundle | null>(null);
  const [series, setSeries] = useState<Series | null>(null);
  const [error, setError] = useState("");
  const [validation, setValidation] = useState<ModelValidationReport | null>(null);
  const [validationError, setValidationError] = useState("");
  const [showValidation, setShowValidation] = useState(false);

  const loadRegistry = async () => {
    setLoading(true); setError("");
    try {
      const next = await api.models();
      setRegistry(next);
      setModelName((current) => current && next[current] ? current : Object.keys(next)[0] ?? "");
    } catch (err) { setError(errorMessage(err)); }
    finally { setLoading(false); }
  };

  useEffect(() => { void loadRegistry(); }, []);
  const model = registry[modelName];
  const parameters = useMemo(() => Object.entries(model?.parameters ?? {}), [model]);

  useEffect(() => {
    if (!model) return;
    setValues(Object.fromEntries(Object.entries(model.parameters).map(([name, parameter]) => [name, parameter.default])));
    setStopTime(model.default_stop_time);
    setResult(null); setSeries(null); setError(""); setShowValidation(false);
  }, [model]);

  useEffect(() => {
    if (!modelName) return;
    let active = true;
    setValidation(null); setValidationError("");
    api.modelValidation(modelName)
      .then((next) => active && setValidation(next))
      .catch((err) => active && setValidationError(errorMessage(err)));
    return () => { active = false; };
  }, [modelName]);

  const updateParameter = (name: string, value: number) => {
    if (!Number.isFinite(value)) return;
    setValues((current) => ({ ...current, [name]: value }));
    setResult(null); setSeries(null);
  };

  const run = async () => {
    if (!model || running) return;
    const invalid = parameters.find(([name, parameter]) => !Number.isFinite(values[name]) || values[name] < parameter.min || values[name] > parameter.max);
    if (invalid) { setError(`${invalid[0]} must be between ${invalid[1].min} and ${invalid[1].max} ${invalid[1].unit}.`); return; }
    if (!Number.isFinite(stopTime) || stopTime <= 0) { setError("Stop time must be greater than zero seconds."); return; }
    setRunning(true); setError(""); setResult(null); setSeries(null);
    try {
      const bundle = await api.simulate(modelName, values, stopTime);
      setResult(bundle);
      setSeries(await api.simulationSeries(bundle.spec_id));
    } catch (err) { setError(errorMessage(err)); }
    finally { setRunning(false); }
  };

  if (loading) return <LoadingBlock label="Loading model registry…" />;
  if (!model) return <section><div className="page-header"><div><h1>Models &amp; simulations</h1></div></div>{error ? <Alert tone="danger" title="Registry unavailable"><p>{error}</p><Button onClick={() => void loadRegistry()}>Retry</Button></Alert> : <EmptyState>No simulation models are registered.</EmptyState>}</section>;

  const keyMetrics = result ? ["T_peak_degC", "E_cool_kWh", "P_cool_avg_W"].filter((key) => key in result.metrics) : [];
  return <section>
    <div className="page-header">
      <div><h1>Models &amp; simulations</h1><p>Inspect credibility boundaries and run a controlled single-case simulation.</p></div>
      <label className="model-selector"><span className="field-label">Registered model</span><select className="field mono" value={modelName} onChange={(event) => setModelName(event.target.value)}>{Object.keys(registry).map((name) => <option key={name}>{name}</option>)}</select></label>
    </div>

    <div className="models-grid">
      <section className="card model-card" aria-labelledby="model-heading">
        <div className="model-card-header"><div className="toolbar"><h2 id="model-heading" className="mono">{modelName}</h2><CredibilityBadge status={model.validation_status} /><span className="mono muted">v{model.model_version}</span></div><p>{model.description}</p><div className="mono model-outputs">outputs: {model.outputs.join(", ")} · default stop {model.default_stop_time}s</div></div>
        <div className="model-disclosure"><WarningBanner>{model.limitations[0] ?? "Review the validation report before interpreting results."}</WarningBanner><Button variant="ghost" aria-expanded={showValidation} onClick={() => setShowValidation(!showValidation)}>{showValidation ? "Hide validation details" : "View validation details"}</Button></div>
        {showValidation && <div className="validation-panel">
          {validationError ? <Alert tone="danger">Validation report unavailable: {validationError}</Alert> : !validation ? <LoadingBlock label="Loading validation evidence…" /> : <>
            <div className="section-heading"><h2>Reference checks</h2><span className="mono">{validation.id} · {validation.checks_status}</span></div>
            <div className="table-wrap"><table className="data-table"><thead><tr><th>Check</th><th>Status</th><th>Observed</th><th>Tolerance</th></tr></thead><tbody>{validation.reference_cases.map((check) => <tr key={check.id}><td>{check.name}</td><td><span className={`check-state ${check.status}`}>{check.status}</span></td><td>{check.observed}</td><td className="mono">{check.tolerance}</td></tr>)}</tbody></table></div>
            <details><summary>Assumptions and limitations</summary><ul>{validation.assumptions.map((item) => <li key={item}>{item}</li>)}{validation.limitations.map((item) => <li key={item}>{item}</li>)}</ul></details>
          </>}
        </div>}
        <div className="table-wrap"><table className="data-table"><thead><tr><th>Parameter</th><th>Default</th><th>Unit</th><th>Range</th></tr></thead><tbody>{parameters.map(([name, parameter]) => <tr key={name}><td><b className="mono">{name}</b><small className="parameter-description">{parameter.description}</small></td><td className="mono">{parameter.default}</td><td className="mono">{parameter.unit}</td><td className="mono">{parameter.min}–{parameter.max}</td></tr>)}</tbody></table></div>
      </section>

      <section className="card simulation-card" aria-labelledby="simulation-heading">
        <div className="section-heading"><h2 id="simulation-heading">Quick simulate</h2><span className="mono">single case</span></div>
        <div className="parameter-controls">{parameters.map(([name, parameter]) => <fieldset key={name} className="parameter-control"><legend><span className="mono">{name}</span><span>{parameter.unit}</span></legend><div className="parameter-inputs"><input aria-label={`${name} slider`} type="range" min={parameter.min} max={parameter.max} step={niceStep(parameter.min, parameter.max)} value={values[name] ?? parameter.default} onChange={(event) => updateParameter(name, Number(event.target.value))} /><input aria-label={`${name} exact value`} className="field mono" type="number" min={parameter.min} max={parameter.max} step="any" value={values[name] ?? parameter.default} onChange={(event) => updateParameter(name, Number(event.target.value))} /></div><small>{parameter.min}–{parameter.max} {parameter.unit}</small></fieldset>)}</div>
        <label><span className="field-label">Stop time (seconds)</span><input aria-label="Stop time" className="field mono" type="number" min="1" step="1" value={stopTime} onChange={(event) => { setStopTime(Number(event.target.value)); setResult(null); setSeries(null); }} /></label>
        <Button variant="primary" className="simulation-submit" disabled={running} onClick={() => void run()}>{running ? "Running OpenModelica…" : "Run simulation"}</Button>
        {error && <Alert tone="danger" title="Simulation unavailable">{error}</Alert>}
        {result && <div className="simulation-result" aria-live="polite">
          {result.warnings.length > 0 && <WarningBanner>{result.warnings.join(" ")}</WarningBanner>}
          <div className="metric-grid">{keyMetrics.map((key) => { const display = METRIC_DISPLAY[key] ?? { unit: "", label: key, color: "var(--text)" }; return <div className="card metric-card" key={key}><span className="mono">{key}</span><strong style={{ color: display.color }}>{fmtMetric(key, result.metrics[key])} <small>{display.unit}</small></strong><small>{display.label}</small></div>; })}</div>
          {series?.T ? <div className="quick-chart"><h3>Room temperature</h3><LineChart title="Room temperature" time={series.time ?? []} values={series.T} color="#dc4c4c" unit="°C" /></div> : <Alert tone="warning">The simulation completed, but no room-temperature series was returned.</Alert>}
        </div>}
      </section>
    </div>
  </section>;
}
