"""Product CLI for Zerone Prospect Intelligence.

Example:
    python -m app research --company ORCHVATE --country India --depth quick
"""
from __future__ import annotations

import argparse
import asyncio
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
    research.add_argument("--model", default="openrouter/gemini-3-flash-preview")
    research.add_argument("--writer-model", default=None)
    research.add_argument("--num-researchers", type=int, default=1)
    research.add_argument("--rag", action="store_true")
    research.add_argument("--interactive", action="store_true")
    research.add_argument("--output-dir", default="reports")
    return parser


def _build_task(args: argparse.Namespace) -> str:
    parts = [
        f"Investigate {args.company} as a company in {args.country}.",
        f"Input company: {args.company}. Target country: {args.country}.",
        "Resolve the brand versus legal entity, distinguish similarly named companies, and use public or explicitly authorized information only.",
        "Cover identity, country of origin/incorporation/headquarters, operations, products/services, customers/partnerships, leadership, workforce and hiring signals, public social presence, recent developments, market context, risks, and unresolved questions.",
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
    return status


def main() -> int:
    args = _parser().parse_args()
    if args.command == "research":
        return asyncio.run(_run(args))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
