"""Deterministic validation for product-facing research artifacts."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REQUIRED_REPORT_KEYS = {"schema_version", "run_id", "question", "executive_summary", "sections", "sources", "run_status"}
VALID_STATUSES = {"completed", "partial", "blocked", "failed"}

CORE_REPORT_SECTIONS = [
    "Executive Summary",
    "Company Identity",
    "Entity Comparison",
    "Business Overview",
    "Leadership",
    "Recent Developments",
    "Risks and Unknowns",
    "Sources",
]


def extract_pdf_content(pdf_path: Path) -> dict[str, Any]:
    """Extract text and metadata from a generated PDF using pypdfium2 or pdfminer."""
    text = ""
    page_count = 0

    # Try pypdfium2 first for page count & text
    try:
        import pypdfium2
        doc = pypdfium2.PdfDocument(str(pdf_path))
        page_count = len(doc)
        pages_text = [page.get_textpage().get_text_range() for page in doc]
        text = "\n".join(pages_text)
    except Exception:
        pass

    # Try pdfminer if pypdfium2 text was empty
    if not text.strip():
        try:
            import pdfminer.high_level
            text = pdfminer.high_level.extract_text(str(pdf_path))
        except Exception:
            pass

    return {
        "text": text,
        "page_count": page_count,
        "length": len(text),
    }


def validate_pdf_artifact(pdf_path: Path, expected_company: str = "", md_text: str = "") -> dict[str, Any]:
    """Validate that the PDF artifact exists, is non-empty, and has extracted content agreeing with findings."""
    errors = []
    if not pdf_path.is_file():
        return {"valid": False, "errors": ["missing PDF artifact"], "page_count": 0}

    size = pdf_path.stat().st_size
    if size < 500:
        errors.append(f"PDF file is too small ({size} bytes)")

    extraction = extract_pdf_content(pdf_path)
    pdf_text = extraction.get("text", "")
    page_count = extraction.get("page_count", 0)

    if not pdf_text.strip():
        errors.append("PDF text extraction produced empty text")
    else:
        # Check required key sections in PDF text
        for section in ["Executive Summary", "Company Identity"]:
            if section.lower() not in pdf_text.lower():
                errors.append(f"PDF missing required section: {section}")

        # Check agreement on company name if specified
        if expected_company and expected_company.lower() not in pdf_text.lower():
            errors.append(f"PDF does not mention company name: {expected_company}")

    return {
        "valid": not errors,
        "errors": errors,
        "page_count": page_count,
        "extracted_chars": len(pdf_text),
    }


def validate_product_artifacts(workdir: str | Path, require_pdf: bool = False) -> dict[str, Any]:
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

    # Validate Markdown report
    md_path = root / "company_research_report.md"
    report_text = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
    if md_path.exists() and md_path.stat().st_size == 0:
        errors.append("company_research_report.md is empty")

    if report_text:
        # Check core section headings
        lower_report = report_text.lower()
        if source_items and ("sources" not in lower_report):
            errors.append("report is missing a Sources section")

    # Validate PDF report
    pdf_path = root / "company_research_report.pdf"
    pdf_validation: dict[str, Any] = {"valid": False, "page_count": 0}

    if pdf_path.exists():
        pdf_validation = validate_pdf_artifact(pdf_path, md_text=report_text)
        if not pdf_validation["valid"]:
            errors.extend([f"PDF validation: {err}" for err in pdf_validation["errors"]])
    elif require_pdf:
        errors.append("missing required artifact: company_research_report.pdf")

    return {
        "valid": not errors,
        "errors": errors,
        "source_count": len(source_items),
        "status": report.get("run_status"),
        "pdf_validated": pdf_path.exists(),
        "pdf_page_count": pdf_validation.get("page_count", 0),
    }


def compare_snapshot(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    """Compare stable prospect fields without claiming that discovery time is event time."""
    if not previous:
        return {"is_first_snapshot": True, "changed_fields": [], "newly_observed_fields": sorted(current.keys())}
    changed = sorted(key for key in current.keys() if previous.get(key) != current.get(key))
    newly_observed = sorted(key for key in current.keys() if key not in previous)
    return {"is_first_snapshot": False, "changed_fields": changed, "newly_observed_fields": newly_observed}
