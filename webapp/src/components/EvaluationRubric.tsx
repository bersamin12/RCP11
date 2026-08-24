import { useEffect, useState } from "react";

import { api, errorMessage } from "../api";
import type { EvaluationView, RubricScore } from "../types";
import { Alert, Button, LoadingBlock } from "./UI";

/** Verbatim from docs/EVALUATION.md:60-68. */
export const RUBRIC_DIMENSIONS: { key: string; label: string }[] = [
  { key: "claim_to_number_traceability", label: "Claim-to-number traceability" },
  { key: "claim_to_literature_traceability", label: "Claim-to-literature traceability" },
  { key: "missing_evidence_visibility", label: "Visibility of missing source evidence" },
  { key: "experiment_comparability_preregistration", label: "Experiment comparability and pre-registration" },
  { key: "reproducibility_from_captured_inputs", label: "Reproducibility from captured inputs and versions" },
  { key: "calibration_validation_disclosure", label: "Calibration and validation disclosures" },
  { key: "claim_verification_effort", label: "Effort to locate and verify a challenged claim" },
];

const SCORES: RubricScore[] = [1, 2, 3, 4, 5];

export type RubricValues = Record<string, RubricScore | null>;

export const emptyRubric = (): RubricValues =>
  Object.fromEntries(RUBRIC_DIMENSIONS.map((item) => [item.key, null]));

export const rubricComplete = (values: RubricValues) =>
  RUBRIC_DIMENSIONS.every((item) => values[item.key] != null);

export function EvaluationRubric({ runId, condition = "platform" }: {
  runId: string;
  condition?: "platform" | "baseline";
}) {
  const [view, setView] = useState<EvaluationView | null>(null);
  const [values, setValues] = useState<RubricValues>(emptyRubric);
  const [reviewer, setReviewer] = useState("");
  const [minutes, setMinutes] = useState("");
  const [observations, setObservations] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let active = true;
    api.evaluation(runId, reviewer || undefined, condition)
      .then((value) => { if (active) setView(value); })
      .catch((err) => { if (active) setError(errorMessage(err)); });
    return () => { active = false; };
  }, [runId, condition, reload]); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async () => {
    setBusy(true); setError("");
    try {
      const scores = Object.fromEntries(
        RUBRIC_DIMENSIONS.map((item) => [item.key, values[item.key]]),
      );
      await api.submitScorecard(runId, {
        reviewer_id: reviewer.trim(), condition, observations: observations.trim(),
        verification_time_seconds: minutes ? Number(minutes) * 60 : null,
        ...scores,
      });
      setValues(emptyRubric());
      setReload((key) => key + 1);
    } catch (err) { setError(errorMessage(err)); }
    finally { setBusy(false); }
  };

  if (!view) return <LoadingBlock label="Loading evaluation…" />;

  const blocked = busy || !rubricComplete(values) || !reviewer.trim();

  return <section className="card evaluation-rubric">
    <div className="section-heading">
      <h2>Scientific evaluation</h2>
      <span className="mono">{view.count} of {view.min_reviewers} reviewers</span>
    </div>

    <Alert tone="info">
      Score independently, before discussing with anyone else. Peer scores stay hidden until
      at least {view.min_reviewers} reviewers have submitted. {view.blinding_note}
    </Alert>

    <fieldset className="rubric-grid">
      <legend className="sr-only">Rubric dimensions, scored 1 to 5</legend>
      {RUBRIC_DIMENSIONS.map((dimension) => <div className="rubric-row" key={dimension.key}>
        <span id={`rubric-${dimension.key}`}>{dimension.label}</span>
        <div className="rubric-scale" role="radiogroup" aria-labelledby={`rubric-${dimension.key}`}>
          {SCORES.map((score) => <label key={score}>
            <input
              type="radio" name={`rubric-${dimension.key}`} value={score}
              checked={values[dimension.key] === score}
              onChange={() => setValues((current) => ({ ...current, [dimension.key]: score }))}
            />
            <span aria-hidden="true">{score}</span>
            <span className="sr-only">{score} of 5 for {dimension.label}</span>
          </label>)}
        </div>
      </div>)}
    </fieldset>

    <div className="rubric-meta">
      <label>
        <span className="field-label">Minutes to locate and verify a challenged claim</span>
        <input className="field mono" type="number" min={0} value={minutes}
               onChange={(event) => setMinutes(event.target.value)} />
      </label>
      <label>
        <span className="field-label">Your reviewer name</span>
        <input className="field" value={reviewer}
               onChange={(event) => setReviewer(event.target.value)} />
      </label>
    </div>

    <label>
      <span className="field-label">Observations</span>
      <textarea className="field" rows={3} value={observations}
                onChange={(event) => setObservations(event.target.value)} />
    </label>

    <p className="field-help">
      Scores and verification time are recorded as separate raw observations. They are
      deliberately not combined into a single validity score.
    </p>

    {error && <Alert tone="danger" title="The scorecard was not saved">{error}</Alert>}

    <Button variant="primary" disabled={blocked} onClick={() => void submit()}>
      {busy ? "Submitting…" : "Submit my scores"}
    </Button>

    {view.revealed && view.summary && <div className="rubric-summary">
      <h3>Reviewer spread</h3>
      <table className="data-table">
        <thead><tr>
          <th>Dimension</th><th>n</th><th>Min</th><th>Median</th><th>Max</th>
          <th><span className="sr-only">Reviewer disagreement</span></th>
        </tr></thead>
        <tbody>{view.summary.dimensions.map((row) => <tr key={row.dimension}>
          <td>{RUBRIC_DIMENSIONS.find((d) => d.key === row.dimension)?.label ?? row.dimension}</td>
          <td className="mono">{row.n}</td>
          <td className="mono">{row.minimum}</td>
          <td className="mono">{row.median}</td>
          <td className="mono">{row.maximum}</td>
          <td>{row.disagreement && <span className="annotation-kind flag">disagreement</span>}</td>
        </tr>)}</tbody>
      </table>
      {/* Raw observations, never averaged -- the protocol is explicit about this. */}
      <p className="mono">
        Verification times (seconds): {view.summary.verification_time_seconds.join(", ") || "none recorded"}
      </p>
    </div>}
  </section>;
}
