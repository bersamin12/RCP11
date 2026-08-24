import { NODE_DEFS, PHASE_DEFS, nodeIndex } from "../theme";

const ENTRY_NODE: Record<string, string> = { research: "research_memory_build", hypothesis: "hypothesis_gen", spec: "spec_compile", reanalysis: "analyze_results" };

export function WorkflowPhases({ current, history, status, entryPoint = "research" }: { current: string | null; history: { node: string; at: number }[]; status: string; entryPoint?: string }) {
  const completed = new Map(history.map((item) => [item.node, item.at]));
  const entryIndex = nodeIndex(ENTRY_NODE[entryPoint] ?? ENTRY_NODE.research);
  const currentIndex = nodeIndex(current);
  const phaseStates = PHASE_DEFS.map((phase) => {
    const indices = phase.nodes.map(nodeIndex);
    const inherited = Math.max(...indices) < entryIndex;
    const active = phase.nodes.includes(current as never) && ["running", "resuming", "waiting_gate", "failed"].includes(status);
    const complete = phase.nodes.some((node) => completed.has(node)) && phase.nodes.filter((node) => node !== "handle_run_failure").every((node) => completed.has(node) || nodeIndex(node) < entryIndex);
    return { ...phase, inherited, active, complete };
  });
  const completedPhases = phaseStates.filter((phase) => phase.complete);
  const openPhase = phaseStates.find((phase) => phase.active)?.id ?? completedPhases[completedPhases.length - 1]?.id;

  return <ol className="workflow-phases" aria-label="Research workflow progress">{phaseStates.map((phase, phaseIndex) => {
    const state = phase.inherited ? "inherited" : phase.active && status === "failed" ? "failed" : phase.active ? "active" : phase.complete ? "complete" : "pending";
    return <li key={phase.id} className={`workflow-phase ${state}`}>
      <details open={phase.id === openPhase}>
        <summary><span className="phase-dot">{state === "complete" ? "✓" : state === "inherited" ? "↳" : phaseIndex + 1}</span><span><b>{phase.label}</b><small>{state === "inherited" ? "Inherited from parent" : state === "active" ? "In progress" : state === "failed" ? "Stopped here" : state}</small></span></summary>
        <ol>{phase.nodes.map((nodeId) => { const node = NODE_DEFS.find((item) => item.id === nodeId)!; const doneAt = completed.get(nodeId); const inheritedNode = nodeIndex(nodeId) < entryIndex; const activeNode = currentIndex === nodeIndex(nodeId) && phase.active; return <li key={nodeId} className={inheritedNode ? "inherited" : doneAt ? "complete" : activeNode ? "active" : "pending"}><span>{inheritedNode || doneAt ? "✓" : "○"}</span><span>{node.label}{doneAt && <time dateTime={new Date(doneAt * 1000).toISOString()}>{new Date(doneAt * 1000).toLocaleTimeString()}</time>}</span></li>; })}</ol>
      </details>
    </li>;
  })}</ol>;
}
