"""Assemble the closed-loop workflow graph with checkpointing (PRD §5.2, X.2)."""

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph

from rcp.config import data_dir
from rcp.graph import nodes
from rcp.graph.state import RCPState
from rcp.objects import (
    AnalysisProtocol,
    Claim,
    ClaimBundle,
    ComparisonPair,
    ExperimentCase,
    ExperimentPlan,
    ExperimentResultSet,
    ExperimentSpec,
    FieldCorrection,
    Hypothesis,
    LiteratureTriage,
    MetricComparison,
    PaperCard,
    PdfAsset,
    ResearchConflict,
    ResearchFinding,
    ResearchGap,
    ResearchSynthesis,
    ResearchTopic,
    ResultBundle,
    ReviewBundle,
    ReviewIssue,
    StudyQualityCheck,
    StudyQualityReport,
    ThesisIdea,
    ThesisProfile,
    TriageDecision,
)


# Strict decode allowlist. It must contain exactly the Pydantic types reachable
# from RCPState -- no more, no less. A missing entry makes loads_typed raise, which
# RunManager._load_existing turns into a permanent failure for every in-flight run
# at the next restart. tests/test_checkpoints.py asserts the equality reflectively.
CHECKPOINT_TYPES = [
    RCPState, ResearchTopic, ThesisIdea, ThesisProfile, PaperCard, ResearchFinding,
    ResearchGap, ResearchConflict, ResearchSynthesis, Hypothesis, ExperimentSpec,
    ExperimentCase, ComparisonPair, AnalysisProtocol, ExperimentPlan, ResultBundle,
    MetricComparison, StudyQualityCheck, StudyQualityReport, ExperimentResultSet,
    Claim, ClaimBundle, ReviewIssue, ReviewBundle,
    PdfAsset, TriageDecision, FieldCorrection, LiteratureTriage,
]


def checkpoint_serializer() -> JsonPlusSerializer:
    """Strict, explicit allowlist for every application type stored in graph state."""
    return JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES)


def make_checkpointer(db_path: Path | None = None) -> SqliteSaver:
    path = db_path or data_dir() / "checkpoints.sqlite"
    conn = sqlite3.connect(path, check_same_thread=False)
    return SqliteSaver(conn, serde=checkpoint_serializer())


def build_graph(checkpointer: SqliteSaver | None = None):
    g = StateGraph(RCPState)
    g.add_node("research_memory_build", nodes.research_memory_build)
    g.add_node("literature_triage", nodes.literature_triage)
    g.add_node("gap_mining", nodes.gap_mining)
    g.add_node("hypothesis_gen", nodes.hypothesis_gen)
    g.add_node("select_hypothesis", nodes.select_hypothesis)
    g.add_node("spec_compile", nodes.spec_compile)
    g.add_node("approve_spec", nodes.approve_spec)
    g.add_node("run_modelica", nodes.run_modelica)
    g.add_node("handle_run_failure", nodes.handle_run_failure)
    g.add_node("analyze_results", nodes.analyze_results)
    g.add_node("review_evidence", nodes.review_evidence)
    g.add_node("draft_report", nodes.draft_report)
    g.add_node("abort_run", nodes.abort_run)

    g.add_conditional_edges(
        START, nodes.route_from_entry,
        {
            "research": "research_memory_build",
            "hypothesis": "hypothesis_gen",
            "spec": "spec_compile",
            "reanalysis": "analyze_results",
        },
    )
    g.add_edge("research_memory_build", "literature_triage")
    g.add_edge("literature_triage", "gap_mining")
    g.add_edge("gap_mining", "hypothesis_gen")
    g.add_edge("hypothesis_gen", "select_hypothesis")
    g.add_edge("select_hypothesis", "spec_compile")
    g.add_edge("spec_compile", "approve_spec")
    g.add_conditional_edges(
        "approve_spec",
        nodes.route_after_approval,
        {"run": "run_modelica", "revise": "spec_compile", "abort": "abort_run"},
    )
    g.add_conditional_edges(
        "run_modelica", nodes.route_after_run,
        {"analyze": "analyze_results", "failure": "handle_run_failure"},
    )
    g.add_conditional_edges(
        "handle_run_failure", nodes.route_after_failure,
        {"analyze": "analyze_results", "revise": "spec_compile", "abort": "abort_run"},
    )
    g.add_edge("analyze_results", "review_evidence")
    g.add_conditional_edges(
        "review_evidence", nodes.route_after_review,
        {"draft": "draft_report", "reanalyze": "analyze_results", "abort": "abort_run"},
    )
    g.add_edge("draft_report", END)

    return g.compile(checkpointer=checkpointer or make_checkpointer())
