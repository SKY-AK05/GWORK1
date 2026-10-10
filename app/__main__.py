"""Product CLI for Zerone Prospect Intelligence.

Example:
    python -m app research --company ORCHVATE --country India --depth quick
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "company"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app", description="Zerone Prospect Intelligence")
    commands = parser.add_subparsers(dest="command", required=True)
    research = commands.add_parser("research", help="Research one company from public/authorized sources")
    research.add_argument("--company", required=True, help="Company or brand name")
    research.add_argument("--country", required=True, help="Target country/jurisdiction")
    research.add_argument("--website", default=None, help="Optional known website or domain")
    research.add_argument("--depth", choices=["quick", "standard", "comprehensive"], default="standard")
    research.add_argument("--recent", default=None, help="Optional period, e.g. 'last 12 months'")
    research.add_argument("--model", default=os.getenv("AI_MODEL", "openrouter/gemini-3-flash-preview"))
    research.add_argument("--writer-model", default=None)
    research.add_argument("--num-researchers", type=int, default=1)
    research.add_argument("--rag", action="store_true")
    research.add_argument("--interactive", action="store_true")
    research.add_argument("--output-dir", default="reports")
    research.add_argument("--memory-db", default=os.getenv("COMPANY_MEMORY_DB", "~/.cache/deepresearch/company_intelligence.sqlite3"))
    return parser


def _build_task(args: argparse.Namespace) -> str:
    parts = [
        f"Investigate the name '{args.company}' as an open company-identity question in {args.country}; do not assume the name identifies one business.",
        f"Input name: {args.company}. Target jurisdiction/country: {args.country}.",
        "Create candidate entities, compare identifiers, determine which candidates are unrelated, related, or the same real-world business, and never merge on name similarity alone.",
        "Identify legal entities, brands, subsidiaries, branches, locations, registration details, websites, aliases, parent relationships, and evidence for or against each link.",
        "Analyze purpose, mission, business model, products, services, operations, customers, beneficiaries, partnerships, competitors, and industry.",
        "Research founders, leadership, employees, hiring activity, recent joiners, departures, position changes, and public job postings including skills, work locations, and remote/hybrid/office arrangements.",
        "Use adaptive reasoning: plan searches, gather evidence, identify gaps, run targeted follow-ups, prioritize official registries/company pages/filings/reliable reporting, and distinguish verified facts, secondary claims, inferences, and unknowns.",
        "Produce an executive summary, entity comparison, business analysis, leadership/workforce analysis, hiring analysis, recent developments, risks, source-backed claims, and unresolved questions.",
    ]
    if args.website:
        parts.append(f"Known website/domain: {args.website}.")
    if args.recent:
        parts.append(f"Recent-development period: {args.recent}.")
    return " ".join(parts)


async def _run(args: argparse.Namespace) -> int:
    if args.num_researchers < 1:
        raise SystemExit("--num-researchers must be at least 1")
    from scripts import run_mvp_research_system as legacy

    depth = {"quick": "brief", "standard": "standard", "comprehensive": "comprehensive"}[args.depth]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    workdir = Path(args.output_dir) / _slug(args.company) / timestamp
    task = _build_task(args)
    forwarded = [
        "run_mvp_research_system.py",
        "--task", task,
        "--model", args.model,
        "--depth", depth,
        "--num-researchers", str(args.num_researchers),
        "--workdir", str(workdir),
        "--memory-db", args.memory_db,
    ]
    if args.writer_model:
        forwarded += ["--writer-model", args.writer_model]
    if args.rag:
        forwarded.append("--rag")
    if args.interactive:
        forwarded.append("--interactive")
    old_argv = sys.argv
    try:
        sys.argv = forwarded
        status = await legacy.main()
    finally:
        sys.argv = old_argv
    print(f"Run status       : {'completed' if status == 0 else 'failed'}")
    print(f"Report directory : {workdir}")
    from src.validation import validate_product_artifacts
    validation = validate_product_artifacts(workdir)
    print(f"Artifact validation: {'passed' if validation['valid'] else 'failed'}")
    for error in validation["errors"]:
        print(f"Validation error : {error}", file=sys.stderr)
    for name in ("company_research_report.md", "company_research.json", "sources.json", "run_metadata.json", "prospect.json"):
        path = workdir / name
        if path.exists():
            print(f"Output           : {path}")
    return status if status != 0 else (0 if validation["valid"] else 1)


def main() -> int:
    args = _parser().parse_args()
    if args.command == "research":
        return asyncio.run(_run(args))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
