#!/usr/bin/env python3
"""Offline report evaluator using LangChain LLMs and the rubric evaluator.

Usage:
    python scripts/evaluate_final_report.py \\
        --report-path workdir/my-run/final_report.md \\
        --judge-model openai/gpt-4o

Outputs:
    <report-dir>/report_evaluation.json
    <report-dir>/report_evaluation.md

LangSmith tracing is enabled automatically when LANGCHAIN_TRACING_V2=true
is set in your environment (see .env.template).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

load_dotenv(verbose=True)

from src.evaluation import OfflineReportEvaluator

DEFAULT_JUDGE_MODEL = "openai/gpt-4o"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate a final_report.md with rubric scores.")
    parser.add_argument("--report-path", required=True, help="Path to final_report.md")
    parser.add_argument(
        "--judge-model",
        default=DEFAULT_JUDGE_MODEL,
        help="LLM used for judging in 'provider/model' format",
    )
    parser.add_argument(
        "--task-name",
        default="report-evaluation",
        help="Friendly name for this evaluation run",
    )
    parser.add_argument(
        "--output-prefix",
        default="report_evaluation",
        help="Prefix for output files written beside the report",
    )
    return parser.parse_args()


def read_text(path: Optional[Path]) -> Optional[str]:
    if path and path.exists():
        return path.read_text(encoding="utf-8")
    return None


def infer_task_query(task_name: str, memo_text: Optional[str], report_text: Optional[str]) -> str:
    if report_text:
        m = re.search(r"##\s+Question\s*\n+(.+?)(?:\n##|\Z)", report_text, re.DOTALL)
        if m:
            return m.group(1).strip()
    if memo_text:
        m = re.search(r"##\s+Question\s*\n+(.+?)(?:\n##|\Z)", memo_text, re.DOTALL)
        if m:
            return m.group(1).strip()
    return task_name


def format_markdown(output: Dict[str, Any]) -> str:
    rubric = output["rubric_scores"]
    lines = [
        "# Combined Report Evaluation",
        "",
        f"- Task Name: {output['task_name']}",
        f"- Task Query: {output['task_query']}",
        f"- Final Report: {output['artifacts']['final_report_path']}",
        f"- Researcher Memo: {output['artifacts']['researcher_memo_path']}",
        "",
        "## Rubric Scores",
        "",
    ]
    for key in [
        "task_alignment", "coverage", "evidence_grounding",
        "factual_consistency", "clarity_structure", "actionability",
    ]:
        item = rubric[key]
        lines += [
            f"### {key.replace('_', ' ').title()}",
            "",
            f"- Score: {item['score']}/5",
            f"- Rationale: {item['rationale']}",
            "",
        ]
    lines += [
        f"**Overall Score: {rubric['overall_score']}/5**",
        "",
        "## Strengths",
        "",
    ]
    lines += [f"- {s}" for s in rubric.get("strengths", [])] or ["- None recorded."]
    lines += ["", "## Weaknesses", ""]
    lines += [f"- {s}" for s in rubric.get("weaknesses", [])] or ["- None recorded."]
    lines += ["", "## Missing Items", ""]
    lines += [f"- {s}" for s in rubric.get("missing_items", [])] or ["- None recorded."]
    lines += ["", "## Verdict", "", rubric["verdict"], ""]
    return "\n".join(lines)


async def main() -> int:
    args = parse_args()
    report_path = Path(args.report_path)
    run_dir = report_path.parent
    memo_path = run_dir / "researcher_memo.md"

    if not report_path.exists():
        print(f"Error: report not found at {report_path}", file=sys.stderr)
        return 1

    report_text = read_text(report_path)
    memo_text = read_text(memo_path)

    task_query = infer_task_query(
        task_name=args.task_name,
        memo_text=memo_text,
        report_text=report_text,
    )

    evaluator = OfflineReportEvaluator(model_name=args.judge_model)
    rubric = await evaluator.evaluate(
        task_query=task_query,
        report_text=report_text or "",
        research_memo_text=memo_text,
    )

    output = {
        "task_name": args.task_name,
        "task_query": task_query,
        "artifacts": {
            "final_report_path": str(report_path),
            "researcher_memo_path": str(memo_path) if memo_path.exists() else None,
        },
        "rubric_scores": rubric.model_dump(),
        "summary": {
            "overall_score": rubric.overall_score,
            "task_alignment_score": rubric.task_alignment.score,
            "evidence_grounding_score": rubric.evidence_grounding.score,
        },
    }

    out_json = run_dir / f"{args.output_prefix}.json"
    out_md = run_dir / f"{args.output_prefix}.md"

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    with open(out_md, "w", encoding="utf-8") as f:
        f.write(format_markdown(output))

    print(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"\nEvaluation JSON : {out_json}")
    print(f"Evaluation MD   : {out_md}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
