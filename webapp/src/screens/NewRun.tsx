import { useEffect, useState } from "react";

import { api, errorMessage } from "../api";
import { WarningBanner } from "../components/Credibility";
import { Alert, Button, EmptyState } from "../components/UI";
import type { ThesisIdea, ThesisProfile } from "../types";

const STEPS = ["Research profile", "Ranked ideas", "Run configuration", "Confirmation"];
const STORAGE_KEY = "rcp-new-run-draft-v1";
const DEFAULT_PROFILE: ThesisProfile = {
  domain: "Data-center digital twins", interests: [], objectives: [],
  preferred_methods: ["Modelica simulation"], constraints: [], experience_level: "intermediate",
};

interface NewRunDraft {
  step: number;
  direct: boolean;
  profile: ThesisProfile;
  ideas: ThesisIdea[];
  selected: ThesisIdea | null;
  topic: string;
  constraints: string[];
  auto: boolean;
}

function split(value: string): string[] {
  return value.split(/[,\n]/).map((item) => item.trim()).filter(Boolean);
}

function readDraft(): NewRunDraft | null {
  try {
    const value = sessionStorage.getItem(STORAGE_KEY);
    if (!value) return null;
    const parsed = JSON.parse(value) as Partial<NewRunDraft>;
    if (!parsed.profile || !Array.isArray(parsed.ideas) || !Array.isArray(parsed.constraints)) return null;
    return {
      step: Math.max(0, Math.min(3, Number(parsed.step) || 0)), direct: Boolean(parsed.direct),
      profile: parsed.profile, ideas: parsed.ideas, selected: parsed.selected ?? null,
      topic: String(parsed.topic ?? ""), constraints: parsed.constraints, auto: Boolean(parsed.auto),
    };
  } catch { return null; }
}

export function NewRun({ goDashboard, openRun }: { goDashboard: () => void; openRun: (id: string) => void }) {
  const [initial] = useState(readDraft);
  const [step, setStep] = useState(initial?.step ?? 0);
  const [direct, setDirect] = useState(initial?.direct ?? false);
  const [profile, setProfile] = useState<ThesisProfile>(initial?.profile ?? DEFAULT_PROFILE);
  const [ideas, setIdeas] = useState<ThesisIdea[]>(initial?.ideas ?? []);
  const [selected, setSelected] = useState<ThesisIdea | null>(initial?.selected ?? null);
  const [topic, setTopic] = useState(initial?.topic ?? "");
  const [constraintDraft, setConstraintDraft] = useState("");
  const [constraints, setConstraints] = useState<string[]>(initial?.constraints ?? []);
  const [auto, setAuto] = useState(initial?.auto ?? false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [restored, setRestored] = useState(Boolean(initial));

  useEffect(() => {
    const value: NewRunDraft = { step, direct, profile, ideas, selected, topic, constraints, auto };
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  }, [auto, constraints, direct, ideas, profile, selected, step, topic]);

  const generate = async (regenerate = false) => {
    if (!profile.domain.trim() || busy) return;
    setBusy(true); setError(""); setSelected(null);
    try {
      const next = await api.thesisIdeas(profile, regenerate);
      setIdeas(next);
      if (!next.length) setError("No thesis suggestions were returned. Refine the profile and retry.");
      else setStep(1);
    } catch (err) { setError(`Could not generate thesis ideas. ${errorMessage(err)}`); }
    finally { setBusy(false); }
  };

  const choose = (idea: ThesisIdea) => {
    setSelected({ ...idea }); setTopic(idea.title);
    setConstraints(Array.from(new Set([...profile.constraints, ...constraints])));
  };

  const submit = async () => {
    if (!topic.trim() || busy) return;
    setBusy(true); setError("");
    try {
      const { run_id } = await api.createRun(topic.trim(), constraints, auto, selected, direct ? null : profile);
      sessionStorage.removeItem(STORAGE_KEY);
      openRun(run_id);
    } catch (err) { setError(`Could not start the run. ${errorMessage(err)}`); setBusy(false); }
  };

  const addConstraint = () => {
    const value = constraintDraft.trim();
    if (!value) return;
    setConstraints((current) => Array.from(new Set([...current, value]))); setConstraintDraft("");
  };

  const reset = () => {
    sessionStorage.removeItem(STORAGE_KEY);
    setStep(0); setDirect(false); setProfile(DEFAULT_PROFILE); setIdeas([]); setSelected(null);
    setTopic(""); setConstraintDraft(""); setConstraints([]); setAuto(false); setError(""); setRestored(false);
  };

  return <section className="new-run-page">
    <div className="new-run-topbar"><Button variant="ghost" onClick={goDashboard}>← Runs</Button>{step > 0 || ideas.length || topic ? <Button variant="ghost" onClick={reset}>Start over</Button> : null}</div>
    {restored && <Alert tone="info" title="Draft restored"><div className="toolbar"><span>Your unfinished run configuration was recovered from this browser tab.</span><Button variant="ghost" onClick={() => setRestored(false)}>Dismiss</Button></div></Alert>}

    <ol className="new-run-progress" aria-label="New run progress">{STEPS.map((name, index) => <li key={name} className={index < step ? "complete" : index === step ? "current" : "pending"} aria-current={index === step ? "step" : undefined}><span>{index < step ? "✓" : index + 1}</span><b>{name}</b></li>)}</ol>

    <div className="card new-run-card">
      {step === 0 && <div>
        <div className="wizard-heading"><div><h1>Build a research profile</h1><p>Combine your research intent with the model registry and literature scan to rank feasible thesis directions.</p></div><Button onClick={() => { setDirect(true); setSelected(null); setIdeas([]); setStep(2); setError(""); }}>Enter topic directly</Button></div>
        <div className="profile-grid">
          <label className="profile-domain"><span className="field-label">Domain</span><input id="profile-domain" className="field" value={profile.domain} onChange={(event) => setProfile({ ...profile, domain: event.target.value })} placeholder="Data-center digital twins" /></label>
          <label><span className="field-label">Interests <i>(comma separated)</i></span><textarea className="field" value={profile.interests.join(", ")} onChange={(event) => setProfile({ ...profile, interests: split(event.target.value) })} placeholder="cooling optimization, GPU rooms" /></label>
          <label><span className="field-label">Objectives</span><textarea className="field" value={profile.objectives.join(", ")} onChange={(event) => setProfile({ ...profile, objectives: split(event.target.value) })} placeholder="reduce cooling energy, quantify resilience" /></label>
          <label><span className="field-label">Preferred methods</span><input className="field" value={profile.preferred_methods.join(", ")} onChange={(event) => setProfile({ ...profile, preferred_methods: split(event.target.value) })} /></label>
          <label><span className="field-label">Thesis constraints</span><input className="field" value={profile.constraints.join(", ")} onChange={(event) => setProfile({ ...profile, constraints: split(event.target.value) })} placeholder="12-week timeline, no facility data" /></label>
          <label><span className="field-label">Experience level</span><select className="field" value={profile.experience_level} onChange={(event) => setProfile({ ...profile, experience_level: event.target.value })}><option value="beginner">Beginner</option><option value="intermediate">Intermediate</option><option value="advanced">Advanced</option></select></label>
        </div>
        <Button variant="primary" className="wizard-primary" onClick={() => void generate(false)} disabled={busy || !profile.domain.trim()}>{busy ? "Scanning literature and ranking ideas…" : "Generate five thesis ideas →"}</Button>
      </div>}

      {step === 1 && <div>
        <div className="wizard-heading"><div><h1>Ranked thesis ideas</h1><p>Select one, inspect its rationale, and refine the title or research question before continuing.</p></div><Button onClick={() => void generate(true)} disabled={busy}>{busy ? "Regenerating…" : "Regenerate all"}</Button></div>
        {ideas[0]?.provider_status === "degraded" && <WarningBanner title="Reduced provider coverage">{ideas[0].provider_warnings.join(" ")}</WarningBanner>}
        {!ideas.length ? <EmptyState>No ideas are available. Return to the profile and try again.</EmptyState> : <div className="idea-list">{ideas.map((idea) => { const active = selected?.id === idea.id; return <article className={`idea-card ${active ? "selected" : ""}`} key={idea.id}>
          <div className="idea-main"><span className="idea-rank mono">#{idea.rank}</span><div>{active ? <><label className="sr-only" htmlFor={`idea-title-${idea.id}`}>Selected idea title</label><input id={`idea-title-${idea.id}`} aria-label="Selected idea title" className="field idea-title-input" value={selected.title} onChange={(event) => { setSelected({ ...selected, title: event.target.value }); setTopic(event.target.value); }} /><label className="sr-only" htmlFor={`idea-question-${idea.id}`}>Selected research question</label><textarea id={`idea-question-${idea.id}`} aria-label="Selected research question" className="field" value={selected.research_question} onChange={(event) => setSelected({ ...selected, research_question: event.target.value })} /></> : <><h2>{idea.title}</h2><p>{idea.research_question}</p></>}</div><strong className="idea-score mono">{idea.rank_score.toFixed(0)}/100</strong></div>
          <div className="idea-factors">{[["Novelty", idea.novelty], ["Feasibility", idea.feasibility], ["Contribution", idea.contribution]].map(([label, value]) => <div key={label}><b>{label}</b><span>{value}</span></div>)}</div>
          <details><summary>Why ranked #{idea.rank}</summary><p>{idea.rank_explanation}</p><div>Models: {idea.model_names.join(", ")} · Supporting papers: {idea.supporting_paper_ids.join(", ") || "no stable IDs returned"}</div><div className="idea-risks">Risks: {idea.risks.join("; ") || "none stated"}</div></details>
          <Button variant={active ? "primary" : "default"} onClick={() => choose(active && selected ? selected : idea)}>{active ? "Selected — keep edits" : "Select this idea"}</Button>
        </article>; })}</div>}
        <div className="wizard-actions"><Button variant="ghost" onClick={() => setStep(0)}>← Profile</Button><Button variant="primary" disabled={!selected} onClick={() => { if (selected) { setTopic(selected.title); setStep(2); } }}>Configure run →</Button></div>
      </div>}

      {step === 2 && <div>
        <div className="wizard-heading"><div><h1>{direct ? "Enter a research topic" : "Configure the selected idea"}</h1><p>The topic, execution constraints, and approval mode remain editable before launch.</p></div></div>
        <label htmlFor="run-topic"><span className="field-label">Research topic</span><input id="run-topic" className="field" value={topic} onChange={(event) => setTopic(event.target.value)} placeholder="e.g. Chilled-water setpoint optimization for GPU rooms" /></label>
        <fieldset className="constraint-fieldset"><legend className="field-label">Constraints</legend><div className="constraint-tags">{constraints.map((constraint) => <span key={constraint} className="mono">{constraint}<button type="button" aria-label={`Remove ${constraint}`} onClick={() => setConstraints((items) => items.filter((item) => item !== constraint))}>×</button></span>)}</div><div className="constraint-entry"><input aria-label="New constraint" className="field" value={constraintDraft} onChange={(event) => setConstraintDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); addConstraint(); } }} placeholder="Type a constraint" /><Button onClick={addConstraint} disabled={!constraintDraft.trim()}>Add</Button></div></fieldset>
        <button type="button" className="auto-mode" role="switch" aria-checked={auto} onClick={() => setAuto(!auto)}><span className="switch-track"><i /></span><span><b>Auto mode</b><small>Auto-resolve the hypothesis and experiment approval gates</small></span><span className="mono">{auto ? "on" : "off"}</span></button>
        <div className="wizard-actions"><Button variant="ghost" onClick={() => direct ? setStep(0) : setStep(1)}>← Back</Button><Button variant="primary" onClick={() => topic.trim() && setStep(3)} disabled={!topic.trim()}>Review →</Button></div>
      </div>}

      {step === 3 && <div>
        <div className="wizard-heading"><div><h1>Confirm research run</h1><p>Review the metadata and human-oversight mode that will travel with this run.</p></div></div>
        <dl className="run-review">{[["Topic", topic], ["Source", selected ? `Ranked thesis idea #${selected.rank}` : "Direct topic entry"], ["Models", selected?.model_names.join(", ") || "Chosen during specification compilation"], ["Constraints", constraints.join("; ") || "None"], ["Approval mode", auto ? "Automatic" : "Two human gates"]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
        {selected && <WarningBanner title="Idea metadata retained">Novelty, feasibility, risks, supporting-paper IDs, and the research profile will be stored with the run.</WarningBanner>}
        {error && <Alert tone="danger" title="Run could not start">{error}</Alert>}
        <div className="wizard-actions"><Button variant="ghost" onClick={() => setStep(2)}>← Edit configuration</Button><Button variant="primary" onClick={() => void submit()} disabled={busy}>{busy ? "Starting…" : "Start run →"}</Button></div>
      </div>}

      {error && step !== 3 && <Alert tone="danger" title="Action unavailable"><div className="toolbar"><span>{error}</span>{step <= 1 && <Button onClick={() => void generate(step === 1)}>Retry</Button>}</div></Alert>}
    </div>
  </section>;
}
