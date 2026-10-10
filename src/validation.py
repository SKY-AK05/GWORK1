"""Deterministic validation for product-facing research artifacts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REQUIRED_REPORT_KEYS = {"schema_version", "run_id", "question", "executive_summary", "sections", "sources", "run_status"}
VALID_STATUSES = {"completed", "partial", "blocked", "failed"}


def validate_product_artifacts(workdir: str | Path) -> dict[str, Any]:
    root = Path(workdir)
    required_files = ["company_research_report.md", "company_research.json", "sources.json", "run_metadata.json"]
    missing = [name for name in required_files if not (root / name).is_file()]
    errors: list[str] = [f"missing artifact: {name}" for name in missing]
    report: dict[str, Any] = {}
    sources: dict[str, Any] = {}
    if not missing:
        try:
            report = json.loads((root / "company_research.json").read_text(encoding="utf-8"))
            sources = json.loads((root / "sources.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid JSON artifact: {exc}")
    errors.extend(f"missing report key: {key}" for key in sorted(REQUIRED_REPORT_KEYS - report.keys()))
    if report.get("run_status") not in VALID_STATUSES:
        errors.append("invalid run_status")
    source_items = sources.get("sources", [])
    if not isinstance(source_items, list):
        errors.append("sources must be a list")
        source_items = []
    for index, source in enumerate(source_items):
        url = source.get("url", "") if isinstance(source, dict) else ""
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            errors.append(f"invalid source URL at index {index}")
    report_text = (root / "company_research_report.md").read_text(encoding="utf-8") if (root / "company_research_report.md").exists() else ""
    if source_items and "## Sources" not in report_text:
        errors.append("report is missing a Sources section")
    return {"valid": not errors, "errors": errors, "source_count": len(source_items), "status": report.get("run_status")}


def compare_snapshot(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    """Compare stable prospect fields without claiming that discovery time is event time."""
    if not previous:
        return {"is_first_snapshot": True, "changed_fields": [], "newly_observed_fields": sorted(current.keys())}
    changed = sorted(key for key in current.keys() if previous.get(key) != current.get(key))
    newly_observed = sorted(key for key in current.keys() if key not in previous)
    return {"is_first_snapshot": False, "changed_fields": changed, "newly_observed_fields": newly_observed}
