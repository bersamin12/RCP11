import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const nodes = ["research_memory_build", "gap_mining", "hypothesis_gen", "select_hypothesis", "spec_compile", "approve_spec", "run_modelica", "analyze_results", "review_evidence", "draft_report"];
const hypothesis = { id: "H1", statement: "Adaptive cooling reduces energy.", rationale: "Registry grounded.", variables: ["Q_room"], expected_effect: "Lower energy", metrics: ["E_HVAC_kWh"], risks: ["Uncalibrated"], model_names: ["ChillerCooledIntegrated"], supporting_gap_ids: ["gap-1"], supporting_conflict_ids: [], supporting_paper_ids: ["p1"], rank: 1, rank_score: 86, ranking_factors: { model_fit: 1, evidence_grounding: .7, testability: 1, novelty_opportunity: .3 }, rank_explanation: "Fixed score." };
const record = {
  run_id: "run-1", topic: "Cooling resilience", constraints: [], auto: false, status: "done",
  current_node: null, node_history: nodes.map((node, index) => ({ node, at: index + 1 })),
  gate: null, error: "", created_at: 1, started_at: 1, ended_at: 12, version: 12,
  outcome: {
    primary_finding: "Within this exploratory model, the candidate reduced HVAC energy.",
    quality_status: "qualified", qualifications: ["The model is not calibrated to a physical facility."],
    metrics: [{ metric: "E_HVAC_kWh", wins: 8, losses: 1, ties: 0, median_percent_delta: -9.4, direction: "lower_is_better", unit: "kWh" }],
    next_action: "Review the supported claims and limitations.", elapsed_seconds: 11, token_usage: { total_tokens: 2400 },
  },
  state: {
    selected_hypothesis: hypothesis,
    paper_cards: [{ id: "p1", title: "Cooling study", year: 2025, doi: null, url: null, venue: "Energy", authors: [], citations: 4, abstract: "Higher setpoints reduced cooling energy.", problem: "Cooling", method: "Simulation", metrics: ["energy"], limitations: [], findings: [{ id: "p1:finding:1", paper_id: "p1", statement: "Higher setpoints reduced cooling energy.", intervention: "setpoint", outcome: "cooling energy", direction: "decrease", conditions: [], metrics: ["energy"], extraction_basis: "abstract" }], study_conditions: [], tags: [], publication_type: "article", peer_review_confidence: "likely", credibility_explanation: "Metadata", provenance: ["openalex"], selection_score: 80, ranking_factors: {} }],
    gaps: ["Operating conditions remain unresolved."], hypotheses: [hypothesis], research_synthesis: { source_snapshot: "/snapshot", papers_total: 1, papers_with_abstract: 1, papers_with_findings: 1, finding_count: 1, gaps: [{ id: "gap-1", category: "scenario", statement: "Operating conditions remain unresolved.", paper_ids: ["p1"], finding_ids: ["p1:finding:1"], model_names: ["DataCenterRoom"], confidence: "medium", testability_note: "Run a bounded sweep." }], conflicts: [], warnings: [], generated_at: "2026-01-01" }, experiment_plan: null, experiment_spec: null, experiment_results: null,
    result_bundle: null, claim_bundle: { hypothesis_id: "H1", claims: [{ statement: "Supported claim", evidence: "", confidence: "medium", evidence_ids: [], comparison_ids: [], case_ids: [], paper_ids: [], warnings: [] }], summary: "", credibility_warnings: [] },
    review_bundle: { valid: true, issues: [] }, report_path: "/tmp/report.md",
  },
};
const report = {
  schema_version: 1, version: 1, run_id: "run-1", created_at: "2026-01-01", updated_at: "2026-01-01", migrated_from_legacy: false,
  metadata: { title: "Cooling resilience", run_id: "run-1", authors: [], abstract: "", keywords: [], disclosures: ["Exploratory"] },
  sections: [{ id: "conclusion", title: "Conclusion", kind: "conclusion", content: "Supported conclusion.", locked: false, generated: true, stale: false, citation_ids: [], evidence_ids: [], generated_content: "Supported conclusion.", updated_at: "2026-01-01" }],
  references: [], figures: [], evidence_links: [],
};

async function mockApi(page: import("@playwright/test").Page) {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/health") return route.fulfill({ json: { ok: true } });
    if (path.endsWith("/events")) return route.fulfill({ status: 204 });
    if (path.endsWith("/report/document")) return route.fulfill({ json: report });
    if (path.endsWith("/report/validation")) return route.fulfill({ json: { valid: true, errors: 0, warnings: 0, issues: [] } });
    if (path.endsWith("/lineage")) return route.fulfill({ json: { root_run_id: "run-1", current_run_id: "run-1", runs: [] } });
    if (path === "/api/runs/run-1") return route.fulfill({ json: record });
    return route.fulfill({ json: [] });
  });
}

for (const theme of ["light", "dark"] as const) {
  test(`${theme} run detail has no detectable accessibility violations`, async ({ page }) => {
    await mockApi(page);
    await page.addInitScript((value) => localStorage.setItem("rcp-theme", value), theme);
    await page.goto("/#/runs/run-1?tab=intelligence");
    await expect(page.getByRole("heading", { name: "Cooling resilience" })).toBeVisible();
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toEqual([]);
  });
}

for (const width of [390, 768, 1440]) {
  test(`run detail remains usable at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await mockApi(page);
    await page.goto("/#/runs/run-1?tab=intelligence");
    await expect(page.getByText("Analyse & report")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  });
}

test("report confirmation traps focus and survives 200% zoom", async ({ page }) => {
  await mockApi(page);
  await page.goto("/#/runs/run-1?tab=report");
  await page.evaluate(() => { document.documentElement.style.zoom = "2"; });
  await page.getByRole("button", { name: "Delete" }).click();
  const dialog = page.getByRole("dialog", { name: "Delete report section?" });
  await expect(dialog).toBeVisible();
  const cancel = dialog.getByRole("button", { name: "Cancel" });
  const confirm = dialog.getByRole("button", { name: "Delete section" });
  await confirm.focus(); await page.keyboard.press("Tab");
  await expect(cancel).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});
