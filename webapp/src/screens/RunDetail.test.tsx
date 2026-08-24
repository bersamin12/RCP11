import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { axe } from "vitest-axe";
import { describe, expect, it, vi } from "vitest";

import * as apiModule from "../api";
import { ToastProvider } from "../components/Toast";
import type { RunRecord } from "../types";
import { NODE_DEFS } from "../theme";
import { RunDetail } from "./RunDetail";

const completedRun: RunRecord = {
  run_id: "run-1",
  topic: "Cooling resilience under variable load",
  constraints: [],
  auto: false,
  status: "done",
  current_node: null,
  node_history: NODE_DEFS.map((node, index) => ({ node: node.id, at: index + 1 })),
  gate: null,
  error: "",
  created_at: 1,
  started_at: 1,
  ended_at: 12,
  version: 12,
  retryable: false,
  thesis_idea: null,
  outcome: {
    primary_finding: "Candidate reduced energy in the approved comparison.",
    quality_status: "passed",
    qualifications: [],
    metrics: [{ metric: "E_HVAC_kWh", wins: 1, losses: 0, ties: 0, median_percent_delta: -10, direction: "lower_is_better", unit: "kWh" }],
    next_action: "Review the supported claims.",
    elapsed_seconds: 11,
    token_usage: { total_tokens: 120 },
  },
  state: {
    selected_hypothesis: {
      id: "H1",
      statement: "Adaptive cooling reduces HVAC energy without thermal violations.",
      rationale: "Matched cases isolate the control change.",
      variables: [],
      expected_effect: "Lower energy",
      metrics: ["E_HVAC_kWh"],
      risks: [],
      model_names: ["ChillerCooledIntegrated"],
      supporting_gap_ids: ["gap-1"],
      supporting_conflict_ids: [],
      supporting_paper_ids: [],
      rank: 1,
      rank_score: 82,
      ranking_factors: { model_fit: 1, evidence_grounding: 0.6, testability: 0.8, novelty_opportunity: 0.3 },
      rank_explanation: "Fixed score from model fit and evidence.",
    },
    paper_cards: [],
    hypotheses: [],
    experiment_plan: null,
    experiment_spec: null,
    experiment_results: null,
    result_bundle: null,
    claim_bundle: null,
    review_bundle: null,
  },
};

describe("RunDetail", () => {
  it("renders the completed research workflow without obvious accessibility violations", async () => {
    vi.spyOn(apiModule, "useRunRecord").mockReturnValue({ record: completedRun, error: "", refresh: vi.fn() });
    const { container } = render(
      <MemoryRouter initialEntries={["/runs/run-1"]}>
        <ToastProvider><RunDetail runId="run-1" goDashboard={() => undefined} openRun={() => undefined} /></ToastProvider>
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: completedRun.topic })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /candidate reduced energy/i })).toBeInTheDocument();
    expect(screen.getByText("Analyse & report")).toBeInTheDocument();
    const audit = await axe(container, { rules: { "color-contrast": { enabled: false } } });
    expect(audit.violations).toEqual([]);
  });

  it("refreshes terminal state immediately after retry and archive mutations", async () => {
    const user = userEvent.setup();
    const refresh = vi.fn().mockResolvedValue(null);
    const failedRun: RunRecord = { ...completedRun, status: "failed", retryable: true, error: "transient backend error" };
    vi.spyOn(apiModule, "useRunRecord").mockReturnValue({ record: failedRun, error: "", refresh });
    vi.spyOn(apiModule.api, "retryRun").mockResolvedValue({ ...failedRun, status: "resuming", retry_count: 1 });
    vi.spyOn(apiModule.api, "setRunArchived").mockResolvedValue({ ...failedRun, archived_at: 123 });
    render(<MemoryRouter><ToastProvider><RunDetail runId="run-1" goDashboard={() => undefined} openRun={() => undefined} /></ToastProvider></MemoryRouter>);

    await user.click(screen.getByRole("button", { name: "Retry checkpoint" }));
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(2));
  });

  it("shows ranked research intelligence and opens source-grounded findings", async () => {
    const user = userEvent.setup();
    const hypothesis = completedRun.state?.selected_hypothesis!;
    const researchRun: RunRecord = {
      ...completedRun,
      state: {
        ...completedRun.state,
        gaps: ["Conditions require testing."],
        hypotheses: [hypothesis],
        paper_cards: [{
          id: "p1", title: "Cooling study", year: 2025, doi: null, url: null, venue: "Energy",
          authors: [], citations: 4, abstract: "A higher setpoint reduced cooling energy.",
          problem: "Cooling energy", method: "Simulation", metrics: ["E_cool_kWh"], limitations: [],
          findings: [{ id: "p1:finding:1", paper_id: "p1", statement: "A higher setpoint reduced cooling energy.", intervention: "T_set", outcome: "E_cool_kWh", direction: "decrease", conditions: ["high load"], metrics: ["E_cool_kWh"], extraction_basis: "abstract" }],
          study_conditions: ["high load"], tags: ["cooling"], publication_type: "journal-article",
          peer_review_confidence: "likely", credibility_explanation: "Metadata available.", provenance: ["openalex"], selection_score: 80, ranking_factors: {},
        }],
        research_synthesis: {
          source_snapshot: "/snapshot", papers_total: 1, papers_with_abstract: 1, papers_with_findings: 1, finding_count: 1,
          gaps: [{ id: "gap-1", category: "scenario", statement: "Conditions require testing.", paper_ids: ["p1"], finding_ids: ["p1:finding:1"], model_names: ["DataCenterRoom"], confidence: "medium", testability_note: "Sweep load." }],
          conflicts: [], warnings: [], generated_at: "2026-01-01",
        },
      },
    };
    vi.spyOn(apiModule, "useRunRecord").mockReturnValue({ record: researchRun, error: "", refresh: vi.fn() });
    render(<MemoryRouter initialEntries={["/runs/run-1?tab=intelligence"]}><ToastProvider><RunDetail runId="run-1" goDashboard={() => undefined} openRun={() => undefined} /></ToastProvider></MemoryRouter>);
    expect(screen.getByRole("heading", { name: "Evidence-backed gaps" })).toBeInTheDocument();
    expect(screen.getByText("82.0")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "p1:finding:1" }));
    expect(screen.getByRole("heading", { name: "A higher setpoint reduced cooling energy." })).toBeInTheDocument();
    expect(screen.getByText("Abstract-grounded finding")).toBeInTheDocument();
  });

  it("creates a linked successor from the supervisor review dialog", async () => {
    const user = userEvent.setup();
    const openRun = vi.fn();
    vi.spyOn(apiModule, "useRunRecord").mockReturnValue({ record: completedRun, error: "", refresh: vi.fn() });
    vi.spyOn(apiModule.api, "runLineage").mockResolvedValue({ root_run_id: "run-1", current_run_id: "run-1", runs: [] });
    const review = vi.spyOn(apiModule.api, "reviewRun").mockResolvedValue({
      decision: "revise_plan", feedback: "Narrow the design.", created_at: "2026-01-01",
      parent_version: 12, protocol_changes: {}, successor_run_id: "run-2",
    });
    render(<MemoryRouter><ToastProvider><RunDetail runId="run-1" goDashboard={() => undefined} openRun={openRun} /></ToastProvider></MemoryRouter>);

    await user.click(screen.getByRole("button", { name: "Review research cycle" }));
    await user.click(screen.getByRole("radio", { name: /revise experiment plan/i }));
    await user.type(screen.getByRole("textbox", { name: "Supervisor feedback" }), "Narrow the design.");
    await user.click(screen.getByRole("button", { name: "Create successor" }));
    await waitFor(() => expect(review).toHaveBeenCalledWith("run-1", expect.objectContaining({ decision: "revise_plan", expected_version: 12 })));
    expect(openRun).toHaveBeenCalledWith("run-2");
  });
});

describe("RunDetail literature triage gate", () => {
  const triagePapers = [
    {
      id: "p1", title: "Chilled-water setpoint study", year: 2021, venue: "Applied Energy",
      doi: "10.1/a", url: "https://openalex.org/W1", extraction_basis: "abstract" as const,
      peer_review_confidence: "verified" as const, selection_score: 71.5,
      insufficient_evidence: [], finding_count: 2, pdf_status: "unavailable" as const,
      pdf_sha256: "", pdf_href: null, license: "",
    },
    {
      id: "p2", title: "Astrophysics of quasars", year: 2019, venue: "ApJ",
      doi: "10.1/b", url: "https://openalex.org/W2", extraction_basis: "abstract" as const,
      peer_review_confidence: "likely" as const, selection_score: 44.2,
      insufficient_evidence: [], finding_count: 1, pdf_status: "unavailable" as const,
      pdf_sha256: "", pdf_href: null, license: "",
    },
  ];

  const waitingRun: RunRecord = {
    ...completedRun,
    status: "waiting_gate",
    current_node: "literature_triage",
    node_history: [{ node: "research_memory_build", at: 1 }],
    gate: {
      gate: "literature_triage",
      question: "Confirm the literature set for this run",
      memory_snapshot: "/snap",
      papers: triagePapers,
      defaults: { included_paper_ids: ["p1", "p2"] },
    },
    outcome: undefined,
    state: {},
  };

  it("renders the literature gate before anything is built on the papers", () => {
    vi.spyOn(apiModule, "useRunRecord").mockReturnValue({ record: waitingRun, error: "", refresh: vi.fn() });
    render(<MemoryRouter initialEntries={["/runs/run-1"]}><ToastProvider><RunDetail runId="run-1" goDashboard={() => undefined} openRun={() => undefined} /></ToastProvider></MemoryRouter>);
    expect(screen.getByRole("heading", { name: "Confirm the literature set for this run" })).toBeInTheDocument();
    expect(screen.getByText("Chilled-water setpoint study")).toBeInTheDocument();
    expect(screen.getByText("2 included · 0 excluded")).toBeInTheDocument();
  });

  it("keeps a half-typed exclusion reason when the SSE stream replaces the record", async () => {
    // useRunRecord swaps in a fresh record object roughly every 0.7s while a run
    // waits at a gate. Seeding the form from record identity would wipe the field
    // mid-sentence; this is the regression guard for that.
    const user = userEvent.setup();
    const useRunRecordSpy = vi.spyOn(apiModule, "useRunRecord");
    useRunRecordSpy.mockReturnValue({ record: waitingRun, error: "", refresh: vi.fn() });
    const view = render(<MemoryRouter initialEntries={["/runs/run-1"]}><ToastProvider><RunDetail runId="run-1" goDashboard={() => undefined} openRun={() => undefined} /></ToastProvider></MemoryRouter>);

    await user.click(screen.getAllByRole("radio", { name: "Exclude" })[1]);
    const reason = screen.getByRole("textbox", { name: "Why is this paper excluded?" });
    await user.type(reason, "off-topic: astro");
    expect(reason).toHaveValue("off-topic: astro");

    // A new record object with identical content, exactly as SSE would deliver.
    useRunRecordSpy.mockReturnValue({
      record: { ...waitingRun, version: waitingRun.version + 1, gate: { ...waitingRun.gate! } },
      error: "", refresh: vi.fn(),
    });
    view.rerender(<MemoryRouter initialEntries={["/runs/run-1"]}><ToastProvider><RunDetail runId="run-1" goDashboard={() => undefined} openRun={() => undefined} /></ToastProvider></MemoryRouter>);

    expect(screen.getByRole("textbox", { name: "Why is this paper excluded?" })).toHaveValue("off-topic: astro");
  });

  it("submits inclusions, explained exclusions, and notes together", async () => {
    const user = userEvent.setup();
    vi.spyOn(apiModule, "useRunRecord").mockReturnValue({ record: waitingRun, error: "", refresh: vi.fn() });
    const answerGate = vi.spyOn(apiModule.api, "answerGate").mockResolvedValue({ ok: true });
    render(<MemoryRouter initialEntries={["/runs/run-1"]}><ToastProvider><RunDetail runId="run-1" goDashboard={() => undefined} openRun={() => undefined} /></ToastProvider></MemoryRouter>);

    await user.click(screen.getAllByRole("radio", { name: "Exclude" })[1]);
    await user.type(screen.getByRole("textbox", { name: "Why is this paper excluded?" }), "off-topic");
    await user.type(screen.getByRole("textbox", { name: "Reviewer name" }), "gsw");
    await user.click(screen.getByRole("button", { name: "Confirm literature set" }));

    await waitFor(() => expect(answerGate).toHaveBeenCalledTimes(1));
    expect(answerGate.mock.calls[0][1]).toEqual({
      reviewer: "gsw",
      included_paper_ids: ["p1"],
      exclusions: [{ paper_id: "p2", reason: "off-topic" }],
      notes: [],
    });
  });

  it("has no accessibility violations at the triage gate", async () => {
    vi.spyOn(apiModule, "useRunRecord").mockReturnValue({ record: waitingRun, error: "", refresh: vi.fn() });
    const { container } = render(<MemoryRouter initialEntries={["/runs/run-1"]}><ToastProvider><RunDetail runId="run-1" goDashboard={() => undefined} openRun={() => undefined} /></ToastProvider></MemoryRouter>);
    const audit = await axe(container, { rules: { "color-contrast": { enabled: false } } });
    expect(audit.violations).toEqual([]);
  });
});
