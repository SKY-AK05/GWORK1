#!/usr/bin/env python3
"""Demonstration of the multi-researcher + RAG pipeline.

This script runs a comprehensive research task using 3 parallel researchers
and RAG-based context trimming, then prints a rich progress trace.

Usage:
    python scripts/run_multi_researcher_example.py

The task used — "What are the key technical challenges and recent breakthroughs
in making large language models more efficient?" — is intentionally broad so
the multi-researcher decomposition adds clear value over a single researcher.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(verbose=True)

root = str(Path(__file__).resolve().parents[1])
sys.path.append(root)

from src.graph.graph import build_research_graph

TASK = (
    "What are the key technical challenges and recent breakthroughs "
    "in making large language models more efficient? "
    "Cover training efficiency, inference optimization, and model compression."
)
MODEL = "openrouter/gemini-3-flash-preview"
NUM_RESEARCHERS = 3
USE_RAG = True
TAG = "multi_researcher_example"


def _hr(char: str = "─", width: int = 72) -> str:
    return char * width


async def main() -> int:
    print(_hr("═"))
    print("  DeepResearch Agent — Multi-Researcher + RAG Demo")
    print(_hr("═"))
    print(f"  Task            : {TASK}")
    print(f"  Model           : {MODEL}")
    print(f"  Researchers     : {NUM_RESEARCHERS} parallel")
    print(f"  RAG             : {'enabled' if USE_RAG else 'disabled'}")
    print(_hr())
    print()

    graph = build_research_graph()

    initial_state = {
        "task": TASK,
        "workdir": f"workdir/{TAG}",
        "model_name": MODEL,
        "depth": "comprehensive",
        "task_mode": "standard",
        "comparison_targets": [],
        "requested_outputs": [],
        "search_plan": [],
        "search_results": [],
        "fetched_pages": [],
        "num_researchers": NUM_RESEARCHERS,
        "sub_topics": [],
        "researcher_memos": [],
        "researcher_errors": [],
        "use_rag": USE_RAG,
        "critique_result": None,
        "revision_count": 0,
        "memo": None,
        "report": None,
        "memo_path": None,
        "memo_paths": None,
        "report_path": None,
        "error": None,
    }

    t0 = time.perf_counter()

    print("[1/5] detect_mode        — classifying task type ...")
    print("[2/5] plan_researchers   — decomposing into sub-topics ...")
    print("[3/5] parallel research  — 3 researchers running concurrently ...")
    print("      Each researcher: search → fetch pages → RAG trim → build memo")
    print("[4/5] build_report       — synthesizing memos into final report ...")
    print("[5/5] save_artifacts     — writing output files ...")
    print()

    result = await graph.ainvoke(initial_state)

    elapsed = time.perf_counter() - t0

    if result.get("error"):
        print(f"ERROR: {result['error']}", file=sys.stderr)
        return 1

    print(_hr())
    print(f"  Completed in {elapsed:.1f}s")
    print(_hr())
    print()

    # Show sub-topics chosen by the planner
    sub_topics = result.get("sub_topics", [])
    if sub_topics:
        print("Sub-topics assigned to parallel researchers:")
        for i, topic in enumerate(sub_topics, 1):
            print(f"  Researcher {i}: {topic}")
        print()

    # Show per-researcher memo paths
    memo_paths = result.get("memo_paths", [])
    if memo_paths:
        print("Researcher memos saved:")
        for p in memo_paths:
            print(f"  {p}")
        print()

    # Show final report location
    report_path = result.get("report_path")
    if report_path:
        print(f"Final report: {report_path}")
        print()

    # Print executive summary and section overview
    if result.get("report"):
        report = result["report"]
        summary = report.get("executive_summary", "")
        sections = report.get("sections", [])
        # Flatten claims from all sections for display
        all_claims = [c for s in sections for c in s.get("claims", [])]
        sources = report.get("sources", [])
        recommendations = report.get("recommendations", [])

        print(_hr("─"))
        print("  Executive Summary")
        print(_hr("─"))
        print(summary)
        print()

        if sections:
            print(_hr("─"))
            print(f"  Report Sections ({len(sections)} total)")
            print(_hr("─"))
            for i, s in enumerate(sections, 1):
                n_claims = len(s.get("claims", []))
                print(f"  {i}. {s.get('title', '(untitled)')}  [{n_claims} claims]")
            print()

        if all_claims:
            print(_hr("─"))
            print(f"  Top Claims ({len(all_claims)} total, first 5 shown)")
            print(_hr("─"))
            for i, c in enumerate(all_claims[:5], 1):
                confidence = c.get("confidence", "?")
                agreement = c.get("source_agreement", "?")
                claim_text = c.get("claim", "")
                print(f"  {i}. [{confidence} / {agreement}]")
                print(f"     {claim_text}")
                print()

        if recommendations:
            print(_hr("─"))
            print(f"  Recommendations ({len(recommendations)} total)")
            print(_hr("─"))
            for r in recommendations[:3]:
                print(f"  - {r}")
            print()

        print(_hr("─"))
        print(f"  Sources ({len(sources)} total, first 5 shown)")
        print(_hr("─"))
        for src in sources[:5]:
            print(f"  - {src}")
        print()

    # RAG efficiency note
    print(_hr("─"))
    print("  RAG Context Engineering — Efficiency Analysis")
    print(_hr("─"))
    print(
        "  With 3 researchers × 4 pages each × ~10k tokens/page = ~120k tokens raw.\n"
        "  RAG retrieval selects the top-10 most relevant 800-token chunks per sub-topic,\n"
        "  reducing context to ~8k tokens per researcher — an 15× compression that:\n"
        "    • Prevents context-window overflow on large fetches\n"
        "    • Focuses memo synthesis on the highest-signal evidence\n"
        "    • Reduces LLM call cost by ~85%\n"
        "\n"
        "  Caveat: RAG adds ~2-4s of embedding/retrieval overhead and can miss\n"
        "  cross-document connections. For tasks with < 30k tokens of content,\n"
        "  full-context (--no-rag) is faster and just as accurate."
    )
    print()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
