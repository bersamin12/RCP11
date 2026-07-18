"""Assemble the closed-loop workflow graph with checkpointing (PRD §5.2, X.2)."""

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from rcp.config import data_dir
from rcp.graph import nodes
from rcp.graph.state import RCPState


def make_checkpointer(db_path: Path | None = None) -> SqliteSaver:
    path = db_path or data_dir() / "checkpoints.sqlite"
    conn = sqlite3.connect(path, check_same_thread=False)
    return SqliteSaver(conn)


def build_graph(checkpointer: SqliteSaver | None = None):
    g = StateGraph(RCPState)
    g.add_node("research_memory_build", nodes.research_memory_build)
    g.add_node("gap_mining", nodes.gap_mining)
    g.add_node("hypothesis_gen", nodes.hypothesis_gen)
    g.add_node("select_hypothesis", nodes.select_hypothesis)
    g.add_node("spec_compile", nodes.spec_compile)
    g.add_node("approve_spec", nodes.approve_spec)
    g.add_node("run_modelica", nodes.run_modelica)
    g.add_node("analyze_results", nodes.analyze_results)
    g.add_node("draft_report", nodes.draft_report)

    g.add_edge(START, "research_memory_build")
    g.add_edge("research_memory_build", "gap_mining")
    g.add_edge("gap_mining", "hypothesis_gen")
    g.add_edge("hypothesis_gen", "select_hypothesis")
    g.add_edge("select_hypothesis", "spec_compile")
    g.add_edge("spec_compile", "approve_spec")
    g.add_conditional_edges(
        "approve_spec",
        nodes.route_after_approval,
        {"run": "run_modelica", "revise": "spec_compile"},
    )
    g.add_edge("run_modelica", "analyze_results")
    g.add_edge("analyze_results", "draft_report")
    g.add_edge("draft_report", END)

    return g.compile(checkpointer=checkpointer or make_checkpointer())
