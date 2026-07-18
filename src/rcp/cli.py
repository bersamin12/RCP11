"""RCP platform CLI."""

import json
import uuid
from pathlib import Path

import typer
from langgraph.types import Command
from rich.console import Console
from rich.table import Table

from rcp.config import data_dir, get_settings
from rcp.objects import ExperimentSpec, ResearchTopic

app = typer.Typer(help="RCP2026/11 — AI Agent Workflow for Scientific Discovery")
console = Console()


@app.command()
def run(
    topic: str,
    constraint: list[str] = typer.Option([], "--constraint", "-c"),
    auto: bool = typer.Option(False, help="Auto-resolve human gates (testing)"),
):
    """Run the full closed loop: topic -> memory -> hypotheses -> simulation -> report."""
    from rcp.graph.build import build_graph
    from rcp.graph.state import RCPState

    graph = build_graph()
    run_id = uuid.uuid4().hex[:8]
    config = {"configurable": {"thread_id": run_id}}
    console.print(f"[bold]run id:[/] {run_id}")

    state = graph.invoke(
        RCPState(run_id=run_id, topic=ResearchTopic(title=topic, constraints=constraint), auto=auto),
        config,
    )
    while "__interrupt__" in state:
        payload = state["__interrupt__"][0].value
        console.print(f"\n[bold yellow]HUMAN GATE:[/] {payload['question']}")
        for line in payload.get("options", []):
            console.print(f"  {line}")
        if "spec" in payload:
            console.print_json(json.dumps(payload["spec"]))
        answer = typer.prompt("> ")
        state = graph.invoke(Command(resume=answer), config)

    console.print(f"\n[bold green]done.[/] report: {state.get('report_path')}")


@app.command("memory-build")
def memory_build(topic: str, max_papers: int = 8):
    """Build the research memory only (Module 1)."""
    from rcp.memory.pipeline import build_research_memory

    cards, themes, snapshot = build_research_memory(topic, max_papers=max_papers)
    console.print(f"{len(cards)} paper cards, {len(themes)} themes -> {snapshot}")


@app.command("sim-run")
def sim_run(
    model: str = "DataCenterRoom",
    stop_time: float = typer.Option(0, help="0 = model default"),
    set_param: list[str] = typer.Option([], "--set", help="k=v parameter overrides"),
):
    """Run a single simulation directly (Module 4)."""
    from rcp.simulation.collector import build_result_bundle
    from rcp.simulation.registry import get_model
    from rcp.simulation.runner import SimulationError, run_simulation

    info = get_model(model)
    spec = ExperimentSpec(
        id="manual-" + uuid.uuid4().hex[:6],
        hypothesis_id="manual",
        model_name=model,
        parameters={k: float(v) for k, v in (s.split("=", 1) for s in set_param)},
        outputs=info.outputs,
        stop_time=stop_time or info.default_stop_time,
    )
    workdir = data_dir() / "runs" / spec.id
    try:
        csv_path, log = run_simulation(spec, workdir)
        bundle = build_result_bundle(spec, workdir, csv_path, log)
        console.print_json(bundle.model_dump_json())
    except SimulationError as err:
        console.print(f"[red]simulation failed:[/] {err}")
        raise typer.Exit(1)


@app.command()
def models():
    """List registered simulation models (Module 4 registry)."""
    from rcp.simulation.registry import load_registry

    table = Table("model", "description", "parameters")
    for name, m in load_registry().items():
        table.add_row(name, m.description[:80], ", ".join(m.parameters))
    console.print(table)


@app.command("verify-llm")
def verify_llm():
    """Smoke-test the configured LLM provider."""
    from rcp.llm import get_chat_model

    s = get_settings()
    console.print(f"model={s.rcp_model} base_url={s.rcp_base_url}")
    reply = get_chat_model().invoke("Reply with exactly: OK")
    console.print(f"reply: {reply.content!r}")


if __name__ == "__main__":
    app()
