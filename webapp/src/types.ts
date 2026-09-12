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
  findings: ResearchFinding[];
  study_conditions: string[];
  tags: string[];
  publication_type: string;
  peer_review_confidence: "verified" | "likely" | "uncertain" | "preprint";
  credibility_explanation: string;
  provenance: string[];
  selection_score: number;
  ranking_factors: Record<string, number>;
  extraction_basis?: "title" | "abstract" | "full_text";
  field_provenance?: Record<string, string[]>;
  insufficient_evidence?: string[];
  pdf?: PdfAsset | null;
  /** Server-supplied reader URL; absent when no open-access full text was cached. */
  pdf_href?: string | null;
  triage_status?: "pending" | "included" | "excluded";
  triage_reason?: string;
  human_reviewed?: boolean;
  human_corrected_fields?: string[];
  reviewer_notes?: string[];
  full_text_extraction_id?: string;
}

export interface ResearchFinding {
  id: string;
  paper_id: string;
  statement: string;
  intervention: string;
  outcome: string;
  direction: "increase" | "decrease" | "no_change" | "mixed" | "not_reported";
  conditions: string[];
  metrics: string[];
  extraction_basis: "abstract" | "full_text";
}

export interface ResearchGap {
  id: string;
  category: "method" | "scenario" | "metric" | "scope" | "validation";
  statement: string;
  paper_ids: string[];
  finding_ids: string[];
  model_names: string[];
  confidence: "high" | "medium" | "low";
  testability_note: string;
}

export interface ResearchConflict {
  id: string;
  kind: "contradiction" | "tension";
  statement: string;
  finding_ids: string[];
  paper_ids: string[];
  explanatory_factors: string[];
  confidence: "high" | "medium" | "low";
}

export interface ResearchSynthesis {
  source_snapshot: string;
  papers_total: number;
  papers_with_abstract: number;
  papers_with_findings: number;
  finding_count: number;
  gaps: ResearchGap[];
  conflicts: ResearchConflict[];
  warnings: string[];
  generated_at: string;
}

export interface ThesisProfile {
  domain: string;
  interests: string[];
  objectives: string[];
  preferred_methods: string[];
  constraints: string[];
  experience_level: string;
}

export interface ThesisIdea {
  id: string;
  rank: number;
  title: string;
  research_question: string;
  novelty: string;
  feasibility: string;
  contribution: string;
  risks: string[];
  supporting_paper_ids: string[];
  model_names: string[];
  rank_score: number;
  rank_explanation: string;
  ranking_factors: Record<string, number>;
  provider_status: string;
  provider_warnings: string[];
}

export interface Hypothesis {
  id: string;
  statement: string;
  rationale: string;
  variables: string[];
  expected_effect: string;
  metrics: string[];
  risks: string[];
  model_names: string[];
  supporting_gap_ids: string[];
  supporting_conflict_ids: string[];
  supporting_paper_ids: string[];
  rank: number;
  rank_score: number;
  ranking_factors: Record<string, number>;
  rank_explanation: string;
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

export interface ExperimentCase {
  id: string;
  label: string;
  role: "baseline" | "candidate" | "ablation" | "sweep";
  model_name: string;
  parameters: Record<string, number>;
  outputs: string[];
  stop_time: number;
  intervals: number;
  factor_values: Record<string, number>;
}

export interface ComparisonPair {
  id: string;
  baseline_case_id: string;
  candidate_case_id: string;
  label: string;
}

export interface AnalysisProtocol {
  id: string;
  version: string;
  thermal_threshold_degC: number;
  hvac_power_screen_min_W: number;
  hvac_power_screen_max_W: number;
  power_screen_method: "linear_bridge";
  max_power_screen_fraction: number;
  pue_min: number;
  pue_max: number;
  mode_hours_tolerance: number;
  comparison_absolute_tolerance: number;
  comparison_relative_tolerance: number;
  require_complete_pair_metrics: boolean;
  require_it_energy_load_monotonicity: boolean;
  metric_directions: Record<string, "lower_is_better" | "higher_is_better" | "neutral">;
  metric_units: Record<string, string>;
  metric_methods: Record<string, string>;
}

export interface ExperimentPlan {
  id: string;
  hypothesis_id: string;
  cases: ExperimentCase[];
  comparison_pairs: ComparisonPair[];
  primary_metrics: string[];
  analysis_protocol?: AnalysisProtocol;
  description: string;
  validation_issues: string[];
}

export interface ResultBundle {
  spec_id: string;
  case_id: string;
  model_name: string;
  parameters: Record<string, number>;
  status: "ok" | "failed" | "pending";
  workdir: string;
  result_file: string | null;
  execution_spec_sha256?: string;
  result_file_sha256?: string;
  observed_result_file_sha256?: string;
  result_file_bytes?: number;
  result_file_integrity?: "verified" | "unverified" | "mismatch";
  sample_count?: number;
  metrics: Record<string, number>;
  metric_methods?: Record<string, string>;
  log_excerpt: string;
  validation_status: string;
  warnings: string[];
  validation_report_id: string | null;
}

export interface MetricComparison {
  id: string;
  pair_id: string;
  metric: string;
  baseline_case_id: string;
  candidate_case_id: string;
  baseline_value: number;
  candidate_value: number;
  absolute_delta: number;
  percent_delta: number | null;
  direction: "lower_is_better" | "higher_is_better" | "neutral";
  candidate_better: boolean | null;
  unit: string;
}

export interface ExperimentResultSet {
  plan_id: string;
  status: "pending" | "ok" | "partial" | "failed";
  cases: ResultBundle[];
  comparisons: MetricComparison[];
  experiment_plan_sha256?: string;
  analysis_protocol_sha256?: string;
  analysis_protocol_snapshot?: AnalysisProtocol | null;
  raw_dataset_sha256?: string;
  analysis_revision_id?: string;
  quality_report?: StudyQualityReport | null;
  warnings: string[];
  generated_at?: string;
}

export interface AnalysisRevision {
  id: string;
  plan_id: string;
  experiment_plan_sha256: string;
  protocol_id: string;
  protocol_sha256: string;
  raw_dataset_sha256: string;
  generated_at: string;
  status: "ok" | "partial" | "failed";
  quality_valid: boolean | null;
  case_count: number;
  comparison_count: number;
  current: boolean;
  warnings: string[];
}

export interface StudyQualityCheck {
  id: string;
  status: "passed" | "warning" | "failed";
  message: string;
  observed: string;
  expected: string;
  case_ids: string[];
}

export interface StudyQualityReport {
  valid: boolean;
  protocol_id: string;
  protocol_sha256: string;
  checks: StudyQualityCheck[];
  generated_at: string;
}

export interface Claim {
  statement: string;
  evidence: string;
  confidence: "low" | "medium" | "high";
  evidence_ids: string[];
  comparison_ids: string[];
  case_ids: string[];
  paper_ids: string[];
  warnings: string[];
}

export interface ClaimBundle {
  hypothesis_id: string;
  claims: Claim[];
  summary: string;
  credibility_warnings: string[];
}

export interface MetricOutcome {
  metric: string;
  wins: number;
  losses: number;
  ties: number;
  median_percent_delta: number | null;
  direction: "lower_is_better" | "higher_is_better" | "neutral";
  unit: string;
}

export interface RunOutcome {
  primary_finding: string;
  quality_status: "pending" | "passed" | "qualified" | "failed";
  qualifications: string[];
  metrics: MetricOutcome[];
  next_action: string;
  elapsed_seconds: number | null;
  token_usage: Record<string, number>;
}

export interface CheckpointHealth {
  status: "ok" | "empty" | "missing" | "incompatible" | "corrupt";
  detail: string;
  resumable: boolean;
  schema_version: number;
}

export type ResearchReviewDecision = "accept" | "reanalyse" | "revise_plan" | "refine_hypothesis";

export interface ProtocolChanges {
  thermal_threshold_degC?: number;
  hvac_power_screen_min_W?: number;
  hvac_power_screen_max_W?: number;
  max_power_screen_fraction?: number;
  pue_min?: number;
  pue_max?: number;
  mode_hours_tolerance?: number;
  comparison_absolute_tolerance?: number;
  comparison_relative_tolerance?: number;
}

export interface ResearchReview {
  decision: ResearchReviewDecision;
  feedback: string;
  created_at: string;
  parent_version: number;
  protocol_changes: ProtocolChanges;
  successor_run_id: string | null;
}

export interface ResearchLineageItem {
  run_id: string;
  topic: string;
  status: string;
  iteration: number;
  parent_run_id: string | null;
  revision_decision: string | null;
  review: ResearchReview | null;
}

export interface ResearchLineage {
  root_run_id: string;
  current_run_id: string;
  runs: ResearchLineageItem[];
}

export interface RunState {
  run_id: string;
  topic: { title: string; constraints: string[]; notes: string };
  paper_cards: PaperCard[];
  themes: Record<string, string[]>;
  gaps: string[];
  research_synthesis: ResearchSynthesis | null;
  hypotheses: Hypothesis[];
  selected_hypothesis: Hypothesis | null;
  experiment_spec: ExperimentSpec | null;
  experiment_plan: ExperimentPlan | null;
  spec_attempts: number;
  result_bundle: ResultBundle | null;
  experiment_results: ExperimentResultSet | null;
  claim_bundle: ClaimBundle | null;
  review_bundle: { valid: boolean; issues: { severity: string; code: string; message: string; claim_index: number | null }[] } | null;
  memory_snapshot: string;
  report_path: string;
}

export interface TriagePaper {
  id: string;
  title: string;
  year: number | null;
  venue: string | null;
  doi: string | null;
  url: string | null;
  extraction_basis: "title" | "abstract" | "full_text";
  peer_review_confidence: "verified" | "likely" | "uncertain" | "preprint";
  selection_score: number;
  insufficient_evidence: string[];
  finding_count: number;
  pdf_status: PdfAssetStatus;
  pdf_sha256: string;
  pdf_href: string | null;
  license: string;
}

export interface TriageEntry {
  paper_id: string;
  decision: "include" | "exclude";
  reason: string;
  note: string;
}

export interface GatePayload {
  gate: "literature_triage" | "hypothesis_selection" | "spec_approval" | "rollback_decision";
  question: string;
  options?: { id: string; label: string }[];
  spec?: ExperimentSpec;
  plan?: ExperimentPlan;
  results?: ExperimentResultSet;
  model_validation?: ModelValidationReport | Record<string, ModelValidationReport>;
  papers?: TriagePaper[];
  memory_snapshot?: string;
  defaults?: { included_paper_ids: string[] };
}

export interface RunRecord {
  run_id: string;
  topic: string;
  constraints: string[];
  auto: boolean;
  status: "running" | "resuming" | "waiting_gate" | "done" | "failed" | "stale";
  current_node: string | null;
  node_history: { node: string; at: number }[];
  gate: GatePayload | null;
  error: string;
  created_at: number;
  started_at: number | null;
  ended_at: number | null;
  archived_at?: number | null;
  retry_count?: number;
  retryable?: boolean;
  version: number;
  thesis_idea?: ThesisIdea | null;
  thesis_profile?: ThesisProfile | null;
  entry_point?: "research" | "hypothesis" | "spec" | "reanalysis";
  root_run_id?: string;
  parent_run_id?: string | null;
  iteration?: number;
  revision_decision?: ResearchReviewDecision | null;
  revision_feedback?: string;
  review?: ResearchReview | null;
  outcome?: RunOutcome;
  checkpoint_health?: CheckpointHealth;
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
  validation_status: string;
  model_version: string;
  validation_report_id: string | null;
  limitations: string[];
  operating_range: Record<string, { min: number; max: number; unit: string }>;
  libraries?: Record<string, string>;
  source?: string;
  metric_profile?: string;
}

export interface ValidationReferenceCase {
  id: string;
  name: string;
  status: "passed" | "failed" | "warning";
  tolerance: string;
  observed: string;
  expected: string;
  details: string;
}

export interface ModelValidationReport {
  id: string;
  model_name: string;
  model_version: string;
  status: string;
  checks_status: string;
  generated_at: string;
  assumptions: string[];
  operating_range: Record<string, { min: number; max: number; unit: string }>;
  reference_cases: ValidationReferenceCase[];
  tolerances: Record<string, number | string>;
  limitations: string[];
  disclosure: string;
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

export interface RunManifest {
  schema_version: number;
  run_id: string;
  created_at: string;
  code_revision: string;
  code_dirty: boolean;
  runtime: Record<string, string>;
  models: Record<string, Record<string, string>>;
  llm: Record<string, string | number | boolean>;
  inputs: Record<string, unknown>;
  memory_snapshot: string;
  artifacts: { path: string; sha256: string; bytes: number }[];
  timings_seconds: Record<string, number>;
  token_usage: Record<string, number>;
  lineage: Record<string, string | number | null>;
  warnings: string[];
}

export interface ReportMetadata {
  title: string;
  run_id: string;
  authors: string[];
  abstract: string;
  keywords: string[];
  disclosures: string[];
}

export interface ReportSection {
  id: string;
  title: string;
  kind: string;
  content: string;
  locked: boolean;
  generated: boolean;
  stale: boolean;
  citation_ids: string[];
  evidence_ids: string[];
  generated_content: string;
  updated_at: string;
}

export interface ReportReference {
  id: string;
  paper_id: string;
  citation: string;
  doi: string | null;
  url: string | null;
}

export interface EvidenceLink {
  id: string;
  kind: string;
  label: string;
  source: string;
}

export interface ReportDocument {
  schema_version: number;
  version: number;
  run_id: string;
  metadata: ReportMetadata;
  sections: ReportSection[];
  references: ReportReference[];
  figures: { id: string; title: string; path: string; caption: string; evidence_ids: string[] }[];
  evidence_links: EvidenceLink[];
  created_at: string;
  updated_at: string;
  migrated_from_legacy: boolean;
}

export interface ReportRevision {
  id: string;
  version: number;
  created_at: string;
  summary: string;
}

export interface ReportValidationIssue {
  severity: "error" | "warning";
  code: string;
  message: string;
  section_id: string | null;
}

export interface ReportValidation {
  valid: boolean;
  errors: number;
  warnings: number;
  issues: ReportValidationIssue[];
  version: number;
}

/* ---------- Literature full text ---------- */

export type PdfAssetStatus =
  | "not_attempted" | "available" | "unavailable" | "not_pdf" | "too_large" | "unreadable";

export interface PdfAsset {
  status: PdfAssetStatus;
  sha256: string;
  bytes: number;
  page_count: number;
  source_url: string;
  landing_page_url: string;
  oa_status: string;
  license: string;
  oa_version: string;
  provider: string;
  content_type: string;
  http_status: number | null;
  error: string;
  retrieved_at: string;
  attempted_urls: string[];
}

/** Normalized 0..1 against the unrotated page, so it is zoom- and DPR-independent. */
export interface PdfHighlightRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface PdfSelectionAnchor {
  paper_id: string;
  pdf_sha256: string;
  page: number;
  quote: string;
  prefix: string;
  suffix: string;
  char_start: number;
  char_end: number;
  rects: PdfHighlightRect[];
  extractor: string;
}

/* ---------- reviewer annotations ---------- */

export type AnnotationKind = "comment" | "flag" | "correction";
export type AnnotationSeverity = "info" | "concern" | "blocker";

export interface EvidenceAnnotation {
  id: string;
  run_id: string;
  evidence_id: string;
  evidence_kind: string;
  evidence_fingerprint: string;
  kind: AnnotationKind;
  severity: AnnotationSeverity;
  body: string;
  proposed_value: string;
  applied: boolean;
  anchor: PdfSelectionAnchor | null;
  author: string;
  created_at: string;
  supersedes: string | null;
  resolved: boolean;
  resolution_note: string;
}

export interface AnnotationDraft {
  evidence_id: string;
  kind: AnnotationKind;
  severity: AnnotationSeverity;
  body: string;
  author: string;
  proposed_value?: string;
  anchor?: PdfSelectionAnchor | null;
}

/* ---------- full-text re-extraction ---------- */

export interface FullTextExtraction {
  id: string;
  run_id: string;
  paper_id: string;
  pdf_sha256: string;
  page_count: number;
  pages_used: number[];
  chars_used: number;
  status: "proposed" | "accepted" | "rejected" | "superseded";
  proposed: {
    problem: string;
    method: string;
    metrics: string[];
    limitations: string[];
    study_conditions: string[];
    tags: string[];
    findings: ResearchFinding[];
  };
  superseded_finding_ids: string[];
  confirmed_by: string;
  confirmed_at: string;
  warnings: string[];
  created_at: string;
}
