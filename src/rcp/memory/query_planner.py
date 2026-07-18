"""Query planner: expand a research topic into multiple search queries (PRD M1.1)."""

from pydantic import BaseModel, Field

from rcp.llm import llm_json


class QueryPlan(BaseModel):
    queries: list[str] = Field(min_length=2, max_length=8)


def plan_queries(topic: str, n: int = 4) -> list[str]:
    plan = llm_json(
        f"Research topic: {topic}\n\n"
        f"Produce {n} diverse literature-search queries covering the main methods, "
        "applications, and adjacent subfields of this topic. Keep each query short "
        "(3-8 words), as used in academic search engines.",
        QueryPlan,
        system="You are a research librarian planning a literature search.",
    )
    return plan.queries[:n]
