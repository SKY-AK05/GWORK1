#!/usr/bin/env python3
"""Entry point for the DeepResearch LangGraph pipeline.

Usage (single researcher):
    python scripts/run_mvp_research_system.py \\
        --task "Compare LangGraph vs AutoGen for multi-agent orchestration" \\
        --tag my-run \\
        --model openrouter/gemini-3-flash-preview

Usage (split research/writer models):
    python scripts/run_mvp_research_system.py \\
        --task "What are the latest advances in fusion energy?" \\
        --model openrouter/gemini-flash-lite \\
        --writer-model openrouter/gemini-3-flash-preview

Usage (multi-researcher + RAG):
    python scripts/run_mvp_research_system.py \\
        --task "What are the latest advances in fusion energy?" \\
        --num-researchers 3 \\
        --rag \\
        --tag fusion-multi \\
        --model openrouter/gemini-3-flash-preview

Usage (interactive — review/edit the search plan before research begins):
    python scripts/run_mvp_research_system.py \\
        --task "Impact of LLMs on scientific publishing" \\
        --interactive

LangSmith tracing is enabled automatically when LANGCHAIN_TRACING_V2=true
is set in your environment (see .env.template).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(verbose=True)

root = str(Path(__file__).resolve().parents[1])
sys.path.append(root)

from src.graph.graph import build_research_graph


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the DeepResearch LangGraph pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--task", required=True, help="Research question to investigate")
    parser.add_argument(
        "--tag",
        default="mvp_research_system",
        help="Run tag used as the workdir subfolder (default: mvp_research_system)",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("AI_MODEL", "openrouter/gemini-3-flash-preview"),
        help="Research model for query planning and gap analysis ('provider/model' format)",
    )
    parser.add_argument(
        "--writer-model",
        default=None,
        metavar="MODEL",
        help=(
            "Synthesis model for memo building, report writing, critique, and claim verification "
            "('provider/model' format). Defaults to --model when omitted. "
            "Use a stronger/larger model here to improve output quality while keeping research "
            "nodes fast and cheap (e.g. --model openrouter/gemini-flash-lite "
            "--writer-model anthropic/claude-sonnet-4-5)."
        ),
    )
    parser.add_argument(
        "--workdir",
        default=None,
        help="Override output directory (default: workdir/<tag>)",
    )
    parser.add_argument(
        "--memory-db",
        default=os.getenv("COMPANY_MEMORY_DB", "~/.cache/deepresearch/company_intelligence.sqlite3"),
        help="Durable company-memory SQLite path (default: ~/.cache/deepresearch/company_intelligence.sqlite3)",
    )
    parser.add_argument(
        "--num-researchers",
        type=int,
        default=1,
        metavar="N",
        help="Number of parallel researchers for comprehensive tasks (default: 1)",
    )
    parser.add_argument(
        "--rag",
        action="store_true",
        default=False,
        help="Enable RAG context trimming before LLM memo calls (recommended for N>1)",
    )
    parser.add_argument(
        "--depth",
        choices=["brief", "standard", "comprehensive"],
        default="standard",
        help=(
            "Research depth: brief (2 queries, 3 pages, no follow-up), "
            "standard (3 queries, 4 pages, 2 follow-up), "
            "comprehensive (5 queries, 6 pages, 3 follow-up + critic revision) "
            "(default: standard)"
        ),
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        default=False,
        help=(
            "Pause after query planning to let you review and edit the search plan "
            "before any web requests are made. Single-researcher: shows search queries. "
            "Multi-researcher: shows sub-topic assignments."
        ),
    )
    return parser.parse_args()


async def _run_interactive(initial_state: dict, session_id: str, is_multi: bool) -> dict:
    """Run the pipeline with a human-in-the-loop pause after query planning.

    Pauses after plan_search (single-researcher) or plan_researchers (multi-researcher),
    displays the proposed plan, and lets the user edit it before research begins.
    """
    graph = build_research_graph(interactive=True)
    config = {"configurable": {"thread_id": session_id}}

    # First run — stops at the interrupt checkpoint
    partial = await graph.ainvoke(initial_state, config=config)

    if is_multi:
        plan_key = "sub_topics"
        plan_label = "Proposed Sub-Topics (one per researcher)"
        edit_hint = "Enter replacement sub-topics one per line, blank line to finish:"
    else:
        plan_key = "search_plan"
        plan_label = "Proposed Search Plan"
        edit_hint = "Enter replacement queries one per line, blank line to finish:"

    current_plan: list = partial.get(plan_key, [])

    print(f"\n--- {plan_label} ---")
    for i, item in enumerate(current_plan, 1):
        print(f"  {i}. {item}")

    print(f"\nPress Enter to accept, or {edit_hint}")
    edited_lines = []
    try:
        while True:
            line = input()
            if not line:
                break
            edited_lines.append(line.strip())
    except EOFError:
        pass  # non-interactive stdin (e.g. pipe) — accept as-is

    if edited_lines:
        graph.update_state(config, {plan_key: edited_lines})
        print(f"Plan updated ({len(edited_lines)} item(s)).")
    else:
        print("Plan accepted.")
    print()

    # Resume from checkpoint with (possibly updated) plan
    return await graph.ainvoke(None, config=config)


async def main() -> int:
    args = parse_args()
    workdir = args.workdir or f"workdir/{args.tag}"

    # Deterministic: same task + model + depth + researcher count → same session_id.
    # This means a failed mid-run restart reuses the same session store and can
    # benefit from any caches already populated (page content, search results).
    session_id = hashlib.sha256(
        f"{args.task}:{args.model}:{args.depth}:{args.num_researchers}".encode()
    ).hexdigest()[:16]

    writer_model = args.writer_model  # None means fall back to args.model in nodes

    mode = f"{args.num_researchers} parallel researchers" if args.num_researchers > 1 else "single researcher"
    rag_flag = " + RAG" if args.rag else ""
    interactive_flag = " + interactive" if args.interactive else ""

    print(f"Task          : {args.task}")
    print(f"Research model: {args.model}")
    if writer_model:
        print(f"Writer model  : {writer_model}")
    print(f"Mode          : {mode}{rag_flag}{interactive_flag}")
    print(f"Depth         : {args.depth}")
    print(f"Workdir       : {workdir}")
    print(f"Session       : {session_id}")
    print()

    initial_state = {
        "task": args.task,
        "workdir": workdir,
        "model_name": args.model,
        "writer_model_name": writer_model,
        "depth": args.depth,
        "session_id": session_id,
        "memory_company_name": None,
        "memory_jurisdiction": None,
        "memory_db_path": args.memory_db,
        # task analysis defaults
        "task_mode": "standard",
        "comparison_targets": [],
        "requested_outputs": [],
        # single-researcher pipeline
        "search_plan": [],
        "research_plan": {},
        "decision_trace": [],
        "model_usage": [],
        "search_results": [],
        "fetched_pages": [],
        "source_coverage": [],
        "search_failures": [],
        "fetch_failures": [],
        "run_status": "completed",
        "coverage_summary": {},
        "india_verification": {},
        "registry_verification": {},
        "identity_candidates": [],
        "role_records": [],
        "dated_events": [],
        "contradictions": [],
        "business_contacts": [],
        "entity_relationships": [],
        "business_analysis": {},
        "workforce_signals": [],
        "hiring_signals": [],
        "claim_ledger": [],
        "company_memory_context": {},
        "memory_gaps": [],
        "stale_findings": [],
        "memory_conflicts": [],
        "memory_summary": {},
        "durable_memory_status": {},
        # multi-researcher pipeline
        "num_researchers": args.num_researchers,
        "sub_topics": [],
        "researcher_memos": [],
        "researcher_errors": [],
        # RAG
        "use_rag": args.rag,
        # critic loop + verification
        "critique_result": None,
        "revision_count": 0,
        "verification_results": None,
        # outputs
        "memo": None,
        "report": None,
        "memo_path": None,
        "memo_paths": None,
        "report_path": None,
        "report_pdf_path": None,
        "diagram_path": None,
        "error": None,
    }

    if args.interactive:
        result = await _run_interactive(initial_state, session_id, args.num_researchers > 1)
    else:
        graph = build_research_graph()
        result = await graph.ainvoke(initial_state)

    if result.get("error"):
        print(f"Error: {result['error']}", file=sys.stderr)
        return 1

    # Multi-researcher: report all memo paths
    memo_paths = result.get("memo_paths")
    if memo_paths:
        for i, p in enumerate(memo_paths, 1):
            print(f"Researcher {i} memo : {p}")
    elif result.get("memo_path"):
        print(f"Researcher memo   : {result['memo_path']}")

    report_path = result.get("report_path")
    if report_path:
        print(f"Final report (MD) : {report_path}")

    if result.get("report_pdf_path"):
        print(f"Final report (PDF): {result['report_pdf_path']}")

    if result.get("diagram_path"):
        print(f"Diagram (PNG)     : {result['diagram_path']}")

    # Print executive summary if available
    if result.get("report"):
        summary = result["report"].get("executive_summary", "")
        if summary:
            print(f"\n--- Executive Summary ---\n{summary}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
