import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import * as apiModule from "../api";
import { EvaluationRubric, RUBRIC_DIMENSIONS } from "./EvaluationRubric";
import type { EvaluationView } from "../types";

const concealed: EvaluationView = {
  count: 1, min_reviewers: 2, revealed: false, reviewer_ids: ["alice"],
  scorecards: [], summary: null,
  dimensions: RUBRIC_DIMENSIONS.map((d) => d.key),
  blinding_note: "Blinding is a claim recorded by each submitter, not a property this service can verify: reviewer identity is self-declared.",
};

const revealed: EvaluationView = {
  ...concealed, count: 2, revealed: true, reviewer_ids: ["alice", "bob"],
  summary: {
    run_id: "run-1", reviewer_count: 2, condition: "platform",
    dimensions: RUBRIC_DIMENSIONS.map((d, index) => ({
      dimension: d.key, n: 2, minimum: index === 2 ? 2 : 4,
      median: index === 2 ? 3.5 : 4, maximum: index === 2 ? 5 : 4,
      disagreement: index === 2,
    })),
    verification_time_seconds: [240, 900],
    disagreement_dimensions: [RUBRIC_DIMENSIONS[2].key],
    generated_at: "2026-08-17T09:00:00Z",
  },
};

describe("EvaluationRubric", () => {
  it("hides peer scores until enough reviewers have submitted", async () => {
    vi.spyOn(apiModule.api, "evaluation").mockResolvedValue(concealed);
    render(<EvaluationRubric runId="run-1" />);
    await waitFor(() => expect(screen.getByText("1 of 2 reviewers")).toBeInTheDocument());
    expect(screen.queryByText("Reviewer spread")).not.toBeInTheDocument();
    expect(screen.getByText(/Score independently, before discussing/)).toBeInTheDocument();
  });

  it("says plainly that blinding is a claim, not a guarantee", async () => {
    vi.spyOn(apiModule.api, "evaluation").mockResolvedValue(concealed);
    render(<EvaluationRubric runId="run-1" />);
    await waitFor(() => expect(screen.getByText(/self-declared/)).toBeInTheDocument());
  });

  it("scores all seven documented dimensions", async () => {
    vi.spyOn(apiModule.api, "evaluation").mockResolvedValue(concealed);
    render(<EvaluationRubric runId="run-1" />);
    await waitFor(() => expect(screen.getAllByRole("radiogroup")).toHaveLength(7));
    expect(screen.getByText("Claim-to-number traceability")).toBeInTheDocument();
    expect(screen.getByText("Effort to locate and verify a challenged claim")).toBeInTheDocument();
  });

  it("cannot submit until every dimension is scored and a reviewer is named", async () => {
    vi.spyOn(apiModule.api, "evaluation").mockResolvedValue(concealed);
    render(<EvaluationRubric runId="run-1" />);
    await waitFor(() => expect(screen.getAllByRole("radiogroup")).toHaveLength(7));

    const submit = screen.getByRole("button", { name: "Submit my scores" });
    expect(submit).toBeDisabled();

    for (const dimension of RUBRIC_DIMENSIONS) {
      await userEvent.click(screen.getByRole("radio", { name: `4 of 5 for ${dimension.label}` }));
    }
    expect(submit).toBeDisabled(); // still needs a reviewer name

    await userEvent.type(screen.getByRole("textbox", { name: "Your reviewer name" }), "alice");
    expect(submit).toBeEnabled();
  });

  it("submits scores with verification time kept as a separate observation", async () => {
    vi.spyOn(apiModule.api, "evaluation").mockResolvedValue(concealed);
    const submitScorecard = vi.spyOn(apiModule.api, "submitScorecard").mockResolvedValue({} as never);
    render(<EvaluationRubric runId="run-1" />);
    await waitFor(() => expect(screen.getAllByRole("radiogroup")).toHaveLength(7));

    for (const dimension of RUBRIC_DIMENSIONS) {
      await userEvent.click(screen.getByRole("radio", { name: `3 of 5 for ${dimension.label}` }));
    }
    await userEvent.type(screen.getByRole("textbox", { name: "Your reviewer name" }), "alice");
    await userEvent.type(
      screen.getByRole("spinbutton", { name: /Minutes to locate and verify/ }), "12",
    );
    await userEvent.click(screen.getByRole("button", { name: "Submit my scores" }));

    await waitFor(() => expect(submitScorecard).toHaveBeenCalledTimes(1));
    const body = submitScorecard.mock.calls[0][1] as Record<string, unknown>;
    expect(body.reviewer_id).toBe("alice");
    expect(body.verification_time_seconds).toBe(720);
    expect(body.claim_to_number_traceability).toBe(3);
  });

  it("shows the spread once revealed, and never an average", async () => {
    vi.spyOn(apiModule.api, "evaluation").mockResolvedValue(revealed);
    const { container } = render(<EvaluationRubric runId="run-1" />);
    await waitFor(() => expect(screen.getByText("Reviewer spread")).toBeInTheDocument());

    expect(screen.getByText("disagreement")).toBeInTheDocument();
    expect(screen.getByText(/240, 900/)).toBeInTheDocument();
    // EVALUATION.md forbids folding the dimensions into one validity score.
    expect(container.textContent).not.toMatch(/total|overall score|composite|average/i);
    expect(screen.getByText(/not combined into a single validity score/)).toBeInTheDocument();
  });

  it("has no accessibility violations across 35 score inputs", async () => {
    vi.spyOn(apiModule.api, "evaluation").mockResolvedValue(revealed);
    const { container } = render(<EvaluationRubric runId="run-1" />);
    await waitFor(() => expect(screen.getAllByRole("radiogroup")).toHaveLength(7));
    const audit = await axe(container, { rules: { "color-contrast": { enabled: false } } });
    expect(audit.violations).toEqual([]);
  });
});
