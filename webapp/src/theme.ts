export const ACCENT = "#0891b2";

export type StageKey = "knowledge" | "idea" | "experiment" | "analysis" | "gate";

export const STAGES: Record<StageKey, { c: string; bg: string; ring: string }> = {
  knowledge: { c: "#0e7490", bg: "#ecfeff", ring: "#a5eef7" },
  idea: { c: "#1d4ed8", bg: "#eff6ff", ring: "#bcd3fb" },
  experiment: { c: "#0f766e", bg: "#f0fdfa", ring: "#a7ecdf" },
  analysis: { c: "#6d28d9", bg: "#f5f3ff", ring: "#d3c6fb" },
  gate: { c: "#b45309", bg: "#fffbeb", ring: "#fbdf99" },
};

export interface NodeDef {
  id: string;
  label: string;
  stage: StageKey;
  gate?: 1 | 2;
}

export const NODE_DEFS: NodeDef[] = [
  { id: "research_memory_build", label: "Research & Memory", stage: "knowledge" },
  { id: "gap_mining", label: "Gap Mining", stage: "knowledge" },
  { id: "hypothesis_gen", label: "Hypothesis Gen", stage: "idea" },
  { id: "select_hypothesis", label: "Select Hypothesis", stage: "gate", gate: 1 },
  { id: "spec_compile", label: "Spec Compile", stage: "experiment" },
  { id: "approve_spec", label: "Approve Spec", stage: "gate", gate: 2 },
  { id: "run_modelica", label: "Run Modelica", stage: "experiment" },
  { id: "analyze_results", label: "Analyze Results", stage: "analysis" },
  { id: "draft_report", label: "Draft Report", stage: "analysis" },
];

export const nodeIndex = (id: string | null | undefined) =>
  NODE_DEFS.findIndex((n) => n.id === id);

export const STATUS: Record<string, { c: string; bg: string; label: string; dot: string; anim?: boolean }> = {
  running: { c: "#1d4ed8", bg: "#eff6ff", label: "running", dot: "#2563eb", anim: true },
  waiting_gate: { c: "#b45309", bg: "#fffbeb", label: "waiting on gate", dot: "#d97706", anim: true },
  done: { c: "#15803d", bg: "#f0fdf4", label: "done", dot: "#16a34a" },
  failed: { c: "#b91c1c", bg: "#fef2f2", label: "failed", dot: "#dc2626" },
  stale: { c: "#6b7280", bg: "#f1f3f4", label: "archived", dot: "#9ca3af" },
};

export const statusOf = (s: string) => STATUS[s] ?? STATUS.stale;

export const METRIC_DISPLAY: Record<string, { unit: string; label: string; color: string }> = {
  T_peak_degC: { unit: "°C", label: "peak room temp", color: "#dc2626" },
  T_avg_steady_degC: { unit: "°C", label: "steady mean", color: "#dc2626" },
  T_std_steady_degC: { unit: "°C", label: "steady std", color: "#6d28d9" },
  E_cool_kWh: { unit: "kWh", label: "24h cooling energy", color: "#0f766e" },
  P_cool_avg_W: { unit: "W", label: "mean cooling power", color: "#0f766e" },
};

export const fmtMetric = (key: string, value: number): string => {
  if (key === "P_cool_avg_W" && Math.abs(value) >= 1000) return (value / 1000).toFixed(1) + "k";
  if (Math.abs(value) >= 1000) return value.toFixed(0);
  return value.toFixed(Math.abs(value) < 10 ? 2 : 1);
};
