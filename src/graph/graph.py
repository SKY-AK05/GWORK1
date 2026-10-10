"""LangGraph research pipeline assembly.

Compiles the researcher → writer → verifier → critic StateGraph and exposes
`build_research_graph()` for the run script.

Single-researcher path (num_researchers == 1):
  START → detect_mode → plan_search → execute_searches → fetch_pages
        → follow_up_searches → build_memo → build_report → verify_claims
        → critique → [build_report if issues found] → save_artifacts → END

Multi-researcher path (num_researchers > 1):
  START → detect_mode → plan_researchers → execute_parallel_research
        → build_report → verify_claims → critique
        → [build_report if issues found] → save_artifacts → END

verify_claims re-checks low-confidence claims against their cited source
pages (almost always a cache hit), then passes failed verifications to
critique as hard evidence of unsupported claims.

Human-in-the-loop (interactive=True):
  Execution pauses after plan_search (single-researcher) or
  plan_researchers (multi-researcher) for user review / query editing.
  Requires a LangGraph checkpointer (MemorySaver injected automatically).

LangSmith traces every node automatically when
LANGCHAIN_TRACING_V2=true is set in the environment.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from src.graph.nodes import (
    build_memo_node,
    build_report_node,
    critique_node,
    detect_mode_node,
    execute_parallel_research_node,
    execute_searches_node,
    fetch_pages_node,
    load_company_memory_node,
    follow_up_searches_node,
    plan_researchers_node,
    plan_search_node,
    save_artifacts_node,
    persist_company_memory_node,
    verify_company_intelligence_node,
    verify_claims_node,
)
from src.graph.state import ResearchState


def _route_after_detect_mode(state: ResearchState) -> str:
    if state.get("num_researchers", 1) > 1:
        return "plan_researchers"
    return "plan_search"


def _route_after_critique(state: ResearchState) -> str:
    """Revise once if the critic found significant issues; otherwise proceed."""
    critique = state.get("critique_result")
    revision_count = state.get("revision_count", 0)
    if critique and critique.get("has_issues") and revision_count < 2:
        return "build_report"
    return "save_artifacts"


def build_research_graph(interactive: bool = False):
    """Build and compile the deep-research LangGraph pipeline.

    Args:
        interactive: When True, the graph pauses after plan_search (single-researcher)
            and plan_researchers (multi-researcher) to allow human review/editing of the
            query plan or sub-topic list before research begins. Requires calling
            ainvoke() twice — once to reach the checkpoint, once to resume.
            A MemorySaver checkpointer is injected automatically.
    """
    workflow = StateGraph(ResearchState)

    # Register all nodes
    workflow.add_node("load_company_memory", load_company_memory_node)
    workflow.add_node("detect_mode", detect_mode_node)
    workflow.add_node("plan_search", plan_search_node)
    workflow.add_node("execute_searches", execute_searches_node)
    workflow.add_node("fetch_pages", fetch_pages_node)
    workflow.add_node("follow_up_searches", follow_up_searches_node)
    workflow.add_node("verify_company_intelligence", verify_company_intelligence_node)
    workflow.add_node("build_memo", build_memo_node)
    workflow.add_node("plan_researchers", plan_researchers_node)
    workflow.add_node("execute_parallel_research", execute_parallel_research_node)
    workflow.add_node("build_report", build_report_node)
    workflow.add_node("verify_claims", verify_claims_node)
    workflow.add_node("critique", critique_node)
    workflow.add_node("persist_company_memory", persist_company_memory_node)
    workflow.add_node("save_artifacts", save_artifacts_node)

    # Entry point
    workflow.add_edge(START, "load_company_memory")
    workflow.add_edge("load_company_memory", "detect_mode")

    # Branch: single-researcher vs multi-researcher
    workflow.add_conditional_edges(
        "detect_mode",
        _route_after_detect_mode,
        {
            "plan_researchers": "plan_researchers",
            "plan_search": "plan_search",
        },
    )

    # Single-researcher path
    workflow.add_edge("plan_search", "execute_searches")
    workflow.add_edge("execute_searches", "fetch_pages")
    workflow.add_edge("fetch_pages", "follow_up_searches")
    workflow.add_edge("follow_up_searches", "verify_company_intelligence")
    workflow.add_edge("verify_company_intelligence", "build_memo")
    workflow.add_edge("build_memo", "build_report")

    # Multi-researcher path
    workflow.add_edge("plan_researchers", "execute_parallel_research")
    workflow.add_edge("execute_parallel_research", "build_report")

    # Common tail: report → verify_claims → critique → (revise or save)
    workflow.add_edge("build_report", "verify_claims")
    workflow.add_edge("verify_claims", "critique")
    workflow.add_conditional_edges(
        "critique",
        _route_after_critique,
        {
            "build_report": "build_report",
            "save_artifacts": "persist_company_memory",
        },
    )

    workflow.add_edge("persist_company_memory", "save_artifacts")
    workflow.add_edge("save_artifacts", END)

    if interactive:
        from langgraph.checkpoint.memory import MemorySaver
        return workflow.compile(
            checkpointer=MemorySaver(),
            interrupt_after=["plan_search", "plan_researchers"],
        )

    return workflow.compile()
