export interface PaperCard {
  id: string;
  title: string;
  year: number | null;
  doi: string | null;
  url: string | null;
  venue: string | null;
  authors: string[];
  citations: number;
  abstract: string;
  problem: string;
  method: string;
  metrics: string[];
  limitations: string[];
  tags: string[];
}

export interface Hypothesis {
  id: string;
  statement: string;
  rationale: string;
  variables: string[];
  expected_effect: string;
  metrics: string[];
  risks: string[];
}

export interface ExperimentSpec {
  id: string;
  hypothesis_id: string;
  model_name: string;
  parameters: Record<string, number>;
  outputs: string[];
  stop_time: number;
  intervals: number;
  description: string;
}

export interface ResultBundle {
  spec_id: string;
  status: "ok" | "failed" | "pending";
  workdir: string;
  result_file: string | null;
  metrics: Record<string, number>;
  log_excerpt: string;
}

export interface Claim {
  statement: string;
  evidence: string;
  confidence: "low" | "medium" | "high";
}

export interface ClaimBundle {
  hypothesis_id: string;
  claims: Claim[];
  summary: string;
}

export interface RunState {
  run_id: string;
  topic: { title: string; constraints: string[]; notes: string };
  paper_cards: PaperCard[];
  themes: Record<string, string[]>;
  gaps: string[];
  hypotheses: Hypothesis[];
  selected_hypothesis: Hypothesis | null;
  experiment_spec: ExperimentSpec | null;
  spec_attempts: number;
  result_bundle: ResultBundle | null;
  claim_bundle: ClaimBundle | null;
  report_path: string;
}

export interface GatePayload {
  gate: "hypothesis_selection" | "spec_approval";
  question: string;
  options?: string[];
  spec?: ExperimentSpec;
}

export interface RunRecord {
  run_id: string;
  topic: string;
  constraints: string[];
  auto: boolean;
  status: "running" | "waiting_gate" | "done" | "failed" | "stale";
  current_node: string | null;
  node_history: { node: string; at: number }[];
  gate: GatePayload | null;
  error: string;
  created_at: number;
  started_at: number | null;
  ended_at: number | null;
  version: number;
  state?: Partial<RunState>;
}

export interface ParamSpec {
  default: number;
  min: number;
  max: number;
  unit: string;
  description: string;
}

export interface ModelInfo {
  description: string;
  default_stop_time: number;
  outputs: string[];
  parameters: Record<string, ParamSpec>;
}

export type Registry = Record<string, ModelInfo>;

export interface MemoryTopic {
  slug: string;
  cards: number;
  snapshot: string;
}

export interface MemoryDetail {
  slug: string;
  snapshot: string;
  paper_cards: PaperCard[];
  themes: Record<string, string[]>;
}

export type Series = Record<string, number[]>;
