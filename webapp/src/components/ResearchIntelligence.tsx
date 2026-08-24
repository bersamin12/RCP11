import { Alert, Button, EmptyState } from "./UI";
import type { Hypothesis, ResearchSynthesis } from "../types";

const FACTORS: [string, string][] = [
  ["model_fit", "Model fit"],
  ["evidence_grounding", "Evidence"],
  ["testability", "Testability"],
  ["novelty_opportunity", "Opportunity"],
];

export function HypothesisRanking({ hypotheses, selectedId, onEvidence, onSelect, busy = false }: {
  hypotheses: Hypothesis[];
  selectedId?: string;
  onEvidence: (id: string) => void;
  onSelect?: (id: string) => void;
  busy?: boolean;
}) {
  if (!hypotheses.length) return <EmptyState>Ranked hypotheses will appear after the research synthesis.</EmptyState>;
  return <div className="ranked-hypotheses">{[...hypotheses].sort((a, b) => (a.rank || 999) - (b.rank || 999)).map((hypothesis) => <article className={`card ranked-hypothesis ${selectedId === hypothesis.id ? "selected" : ""}`} key={hypothesis.id}>
    <div className="hypothesis-score"><span className="rank-badge">#{hypothesis.rank || "—"}</span><strong>{hypothesis.rank_score?.toFixed(1) ?? "—"}<small>/100</small></strong>{hypothesis.rank === 1 && <span className="recommended-badge">recommended</span>}</div>
    <div className="hypothesis-body"><div className="section-heading"><h3>{hypothesis.statement}</h3><span className="mono">{hypothesis.id}</span></div><p>{hypothesis.rationale || "No rationale was returned."}</p>
      <div className="ranking-factors">{FACTORS.map(([key, label]) => { const value = hypothesis.ranking_factors?.[key] ?? 0; return <div key={key}><span>{label}</span><span className="ranking-track"><i style={{ width: `${Math.round(value * 100)}%` }} /></span><b className="mono">{Math.round(value * 100)}</b></div>; })}</div>
      <p className="ranking-explanation">{hypothesis.rank_explanation || "Legacy hypothesis — no reproducible ranking is available."}</p>
      <dl className="hypothesis-facts"><dt>Models</dt><dd>{hypothesis.model_names?.join(", ") || "not recorded"}</dd><dt>Expected effect</dt><dd>{hypothesis.expected_effect || "not stated"}</dd><dt>Risks</dt><dd>{hypothesis.risks?.join("; ") || "not stated"}</dd></dl>
      <div className="evidence-chip-row">{hypothesis.supporting_gap_ids?.map((id) => <button key={id} onClick={() => onEvidence(id)}>{id}</button>)}{hypothesis.supporting_conflict_ids?.map((id) => <button key={id} onClick={() => onEvidence(id)}>{id}</button>)}{hypothesis.supporting_paper_ids?.map((id) => <button key={id} onClick={() => onEvidence(`paper:${id}`)}>paper:{id}</button>)}</div>
      {onSelect && <Button variant={hypothesis.rank === 1 ? "primary" : "default"} disabled={busy} onClick={() => onSelect(hypothesis.id)}>{selectedId === hypothesis.id ? "Selected" : `Select hypothesis ${hypothesis.id}`}</Button>}
    </div>
  </article>)}</div>;
}

export function ResearchIntelligence({ synthesis, legacyGaps, hypotheses, selectedId, onEvidence }: {
  synthesis: ResearchSynthesis | null | undefined;
  legacyGaps: string[];
  hypotheses: Hypothesis[];
  selectedId?: string;
  onEvidence: (id: string) => void;
}) {
  const gaps = synthesis?.gaps ?? [];
  const contradictions = synthesis?.conflicts.filter((item) => item.kind === "contradiction") ?? [];
  const tensions = synthesis?.conflicts.filter((item) => item.kind === "tension") ?? [];
  return <div className="intelligence-workspace">
    {synthesis ? <section className="card synthesis-coverage"><div><span className="evidence-kind">Evidence coverage</span><h2>{synthesis.papers_with_findings} of {synthesis.papers_total} papers yielded findings</h2><p>{synthesis.finding_count} abstract-grounded findings · {synthesis.papers_with_abstract} records with abstracts</p></div><div className="coverage-meter" role="progressbar" aria-label="Papers with abstract-grounded findings" aria-valuemin={0} aria-valuemax={synthesis.papers_total} aria-valuenow={synthesis.papers_with_findings}><i style={{ width: `${synthesis.papers_total ? synthesis.papers_with_findings / synthesis.papers_total * 100 : 0}%` }} /></div></section> : <Alert tone="warning" title="Legacy research cycle">This run predates structured synthesis. Its original free-text gaps remain visible below.</Alert>}
    {synthesis?.warnings.map((warning) => <Alert key={warning} tone="warning">{warning}</Alert>)}
    <section><div className="section-heading"><div><h2>Evidence-backed gaps</h2><p>Opportunities retained only when their source references validate.</p></div><span className="mono">{gaps.length || legacyGaps.length}</span></div>{gaps.length ? <div className="gap-grid">{gaps.map((gap) => <article className="card intelligence-card" key={gap.id}><div className="toolbar"><span className="gap-category">{gap.category}</span><span className={`confidence-label ${gap.confidence}`}>{gap.confidence}</span><span className="mono">{gap.id}</span></div><h3>{gap.statement}</h3><p>{gap.testability_note || "Testability was not described."}</p><div className="model-chip-row">{gap.model_names.map((name) => <span key={name}>{name}</span>)}</div><div className="evidence-chip-row">{gap.finding_ids.map((id) => <button key={id} onClick={() => onEvidence(id)}>{id}</button>)}{gap.paper_ids.map((id) => <button key={id} onClick={() => onEvidence(`paper:${id}`)}>paper:{id}</button>)}</div></article>)}</div> : legacyGaps.length ? <div className="gap-grid">{legacyGaps.map((gap, index) => <article className="card intelligence-card legacy" key={gap}><span className="mono">legacy gap {index + 1}</span><h3>{gap}</h3><p>No structured source links are available for this older result.</p></article>)}</div> : <EmptyState>No supported gaps are available.</EmptyState>}</section>
    <div className="conflict-columns"><section><div className="section-heading"><h2>Contradictions</h2><span>{contradictions.length}</span></div><ConflictList items={contradictions} onEvidence={onEvidence} empty="No directly opposing findings passed validation." /></section><section><div className="section-heading"><h2>Possible tensions</h2><span>{tensions.length}</span></div><ConflictList items={tensions} onEvidence={onEvidence} empty="No conditional or methodological tensions were retained." /></section></div>
    <section><div className="section-heading"><div><h2>Ranked hypotheses</h2><p>Fixed weights: model fit 35%, evidence 30%, testability 20%, opportunity 15%.</p></div></div><HypothesisRanking hypotheses={hypotheses} selectedId={selectedId} onEvidence={onEvidence} /></section>
  </div>;
}

function ConflictList({ items, onEvidence, empty }: { items: NonNullable<ResearchSynthesis["conflicts"]>; onEvidence: (id: string) => void; empty: string }) {
  if (!items.length) return <EmptyState>{empty}</EmptyState>;
  return <div className="conflict-list">{items.map((item) => <article className={`card conflict-card ${item.kind}`} key={item.id}><div className="toolbar"><span className="mono">{item.id}</span><span className={`confidence-label ${item.confidence}`}>{item.confidence}</span></div><h3>{item.statement}</h3>{item.explanatory_factors.length > 0 && <p>Possible explanations: {item.explanatory_factors.join("; ")}</p>}<div className="evidence-chip-row">{item.finding_ids.map((id) => <button key={id} onClick={() => onEvidence(id)}>{id}</button>)}{item.paper_ids.map((id) => <button key={id} onClick={() => onEvidence(`paper:${id}`)}>paper:{id}</button>)}</div></article>)}</div>;
}
