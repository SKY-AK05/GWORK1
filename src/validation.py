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


# ==============================================================================
# Pre-Report Validation & Sanitization Layer
# ==============================================================================

_INVALID_COMPANY_PATTERNS = [
    re.compile(r"^investigate\b", re.IGNORECASE),
    re.compile(r"^the name\b", re.IGNORECASE),
    re.compile(r"open company-identity", re.IGNORECASE),
    re.compile(r"^company investigation", re.IGNORECASE),
    re.compile(r"^research question", re.IGNORECASE),
    re.compile(r"^target entity", re.IGNORECASE),
    re.compile(r"^candidate entity", re.IGNORECASE),
]

_INVALID_COMPANY_EXACT = {
    "investigate the name", "the name", "company", "entity", "target",
    "target entity", "unnamed", "none", "n/a", "null", "undefined",
    "company investigation", "open identity question", "unknown"
}


def is_invalid_company_name(name: Any) -> bool:
    """Return True if candidate name is prompt text, boilerplate, or a generic placeholder."""
    if not name or not isinstance(name, str):
        return True
    s = re.sub(r"\s+", " ", name).strip()
    if len(s) < 2 or len(s) > 120:
        return True
    lowered = s.lower().strip("'\"`.:;, ")
    if lowered in _INVALID_COMPANY_EXACT:
        return True
    return any(p.search(lowered) for p in _INVALID_COMPANY_PATTERNS)


def extract_canonical_company_name(task_query: str, state: dict[str, Any] | None = None) -> str:
    """Extract and validate the canonical company/target name.

    Guarantees that prompt instructions like 'Investigate the name' NEVER become the entity name.
    """
    if state and state.get("company"):
        cand = str(state["company"]).strip()
        if cand and not is_invalid_company_name(cand):
            return cand

    q = str(task_query or "").strip()
    if not q:
        return "Target Entity"

    # 1. Match explicit "Input name: <name>." or "Input name: <name>;"
    m = re.search(r"Input name:\s*([^.;,\n]+)", q, re.IGNORECASE)
    if m:
        cand = m.group(1).strip().strip("'\"`")
        if cand and not is_invalid_company_name(cand):
            return cand

    # 2. Match "Investigate the name '<name>'" or 'Investigate the name "<name>"'
    m = re.search(r"Investigate the name\s+['\"`]([^'\"`]+)['\"`]", q, re.IGNORECASE)
    if m:
        cand = m.group(1).strip()
        if cand and not is_invalid_company_name(cand):
            return cand

    # 3. Match "Investigate the name <name> as an open"
    m = re.search(r"Investigate the name\s+([A-Za-z0-9\.\- &]+?)\s+as an open", q, re.IGNORECASE)
    if m:
        cand = m.group(1).strip().strip("'\"`")
        if cand and not is_invalid_company_name(cand):
            return cand

    # 4. Match "Investigate <name> in <jurisdiction>"
    m = re.search(r"Investigate\s+([A-Za-z0-9\.\- &]+?)\s+in\s+", q, re.IGNORECASE)
    if m:
        cand = m.group(1).strip().strip("'\"`")
        if cand and not is_invalid_company_name(cand):
            return cand

    # 5. Quoted target name in initial portion
    for match in re.findall(r"['\"`]([A-Za-z0-9\.\- &]{2,40})['\"`]", q[:250]):
        cand = match.strip()
        if cand and not is_invalid_company_name(cand):
            return cand

    return "Target Entity"


_INVALID_PERSON_WORDS = {
    "revenue", "board", "board-of", "board members", "directors", "employees",
    "company", "candidate", "general", "user", "admin", "unnamed", "none",
    "n/a", "null", "founder", "ceo", "director", "manager", "advisor",
    "executive", "solutions", "services", "corporate", "sales", "marketing",
    "operations", "technology", "investigate", "the name", "annual", "report",
    "growth", "headquarters", "overview", "profile", "contact", "about",
    "about us", "home", "privacy", "terms", "careers", "jobs", "team",
    "our team", "leadership", "governance", "committee", "officer", "ltd",
    "limited", "inc", "corp", "llp", "pvt", "private", "holdings", "group"
}


def clean_person_name(name: Any) -> str:
    """Normalize and strip non-name prefixes/punctuation from a candidate person name."""
    if not name or not isinstance(name, str):
        return ""
    s = re.sub(r"^(?:former|ex-|past|previously|mr\.|ms\.|mrs\.|dr\.)\s+", "", name.strip(), flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip(".,;:|/\\-_'\"` ")
    return s


def is_valid_person_name(name: Any, target_name: str | None = None) -> bool:
    """Validate whether candidate text represents a legitimate person's name."""
    if not name or not isinstance(name, str):
        return False
    cleaned = clean_person_name(name)
    if len(cleaned) < 3 or len(cleaned) > 50:
        return False
    lowered = cleaned.lower()
    if lowered in _INVALID_PERSON_WORDS:
        return False
    if target_name and lowered == target_name.lower():
        return False
    # Reject URL fragments, file extensions, emails, domain names, query strings
    if any(ch in cleaned for ch in ("/", "\\", "@", ":", "=", "?", "#", "%", "<", ">")):
        return False
    if any(token in lowered for token in (
        "http", "www.", ".com", ".org", ".in", ".io", "appoints", "announces",
        "fetched content", "click here", "read more", "article", "press release"
    )):
        return False
    # Reject URL slugs joined by multiple hyphens (e.g. LT-appoints-ex-Infosys-executive-Sanjay-Jalona)
    if cleaned.count("-") > 1:
        return False
    # Human names should not contain digits
    if any(ch.isdigit() for ch in cleaned):
        return False

    tokens = [t.strip(".,") for t in cleaned.split() if t.strip(".,")]
    if not tokens or len(tokens) > 5:
        return False
    # Single generic words are not people names
    if len(tokens) == 1 and (lowered in _INVALID_PERSON_WORDS or len(cleaned) < 4):
        return False
    if all(t.lower() in _INVALID_PERSON_WORDS for t in tokens):
        return False
    # Check capitalization of tokens
    for t in tokens:
        if not t:
            continue
        if not (t[0].isupper() or t in ("van", "von", "de", "der", "da", "di")):
            return False
    return True


_JOB_ROLE_INDICATORS = {
    "engineer", "developer", "manager", "director", "lead", "specialist",
    "analyst", "supervisor", "annotator", "officer", "associate", "consultant",
    "intern", "designer", "architect", "scientist", "coordinator", "head",
    "operator", "executive", "administrator", "counsel", "recruiter",
    "trainer", "agent", "worker", "programmer"
}

_INVALID_JOB_PREFIXES = (
    "fetched content from", "http://", "https://", "www.", "click here",
    "welcome to", "about us", "home", "search results", "sign in"
)


def clean_job_title(title: Any) -> str:
    """Normalize and clean candidate job title string."""
    if not title or not isinstance(title, str):
        return ""
    t = re.sub(r"\s+", " ", str(title)).strip(".,;:|/\\-_'\"` ")
    # If title has format 'Careers — Software Engineer', extract role part
    if "—" in t or " - " in t:
        parts = re.split(r"\s*[—\-]\s*", t)
        for part in reversed(parts):
            p_clean = part.strip()
            if any(ind in p_clean.lower() for ind in _JOB_ROLE_INDICATORS):
                return p_clean
    return t


def is_valid_job_title(title: Any) -> bool:
    """Validate whether candidate text represents a legitimate job role/title."""
    if not title or not isinstance(title, str):
        return False
    cleaned = clean_job_title(title)
    if len(cleaned) < 3 or len(cleaned) > 80:
        return False
    lowered = cleaned.lower()
    if any(lowered.startswith(p) for p in _INVALID_JOB_PREFIXES):
        return False
    if any(token in lowered for token in ("http://", "https://", "www.", ".com", ".org", "tracxn", "wikipedia", "zaubacorp", "thecompanycheck")):
        return False
    return any(ind in lowered for ind in _JOB_ROLE_INDICATORS)


def reconcile_registry_status(
    jurisdiction: str,
    reg_outcome: str | None = None,
    india_verification: dict[str, Any] | None = None,
    has_registration_number: bool = False,
    is_foreign_check: bool = False,
) -> dict[str, str]:
    """Reconcile registry outcomes across sections.

    Guarantees:
    - Inconclusive official checks are labeled 'inconclusive_verification', not 'confirmed_match'.
    - Missing search results are labeled 'no_match_in_completed_searches' without claiming non-existence.
    - Foreign registry outcomes do not override domestic jurisdiction status.
    - Registration identifier rows never pair 'Not confirmed' with 'confirmed_match'.
    """
    jur = (jurisdiction or "India").lower()

    if "india" in jur:
        india_registries = (india_verification or {}).get("registries", {})
        mca_info = india_registries.get("MCA COMPANY AND LLP MASTER DATA") or india_registries.get("mca") or {}
        mca_outcome = mca_info.get("outcome") if isinstance(mca_info, dict) else str(mca_info)

        has_india_confirmed = any(
            (v.get("outcome") if isinstance(v, dict) else str(v)) == "confirmed_match"
            for v in india_registries.values()
        )

        if has_india_confirmed:
            official_status = "confirmed_match"
            official_note = "Confirmed in official Indian government registry"
        elif mca_outcome == "no_match_in_completed_searches":
            official_status = "no_match_in_completed_searches"
            official_note = "Completed registry search returned no match; not proof of non-existence"
        else:
            official_status = "inconclusive_verification"
            official_note = "Direct authoritative MCA/ROC extract unretrieved / inconclusive; secondary databases reviewed"
    else:
        raw = (reg_outcome or "inconclusive_verification").lower()
        if "confirmed" in raw:
            official_status = "confirmed_match"
            official_note = "Verified in official national registry"
        elif "no_match" in raw:
            official_status = "no_match_in_completed_searches"
            official_note = "No matching company record in completed registry search; not proof of non-existence"
        else:
            official_status = "inconclusive_verification"
            official_note = "Authoritative registry verification inconclusive"

    if has_registration_number:
        reg_number_status = "corroborated_secondary"
    else:
        reg_number_status = "unresolved"

    return {
        "official_status": official_status,
        "official_note": official_note,
        "reg_number_status": reg_number_status,
    }


def deduplicate_paragraphs(paragraphs: list[str]) -> list[str]:
    """Remove exact or near-identical duplicate paragraphs while preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for p in paragraphs:
        cleaned = re.sub(r"\s+", " ", p).strip()
        if not cleaned:
            continue
        norm_sig = re.sub(r"[^a-z0-9]", "", cleaned.lower())
        if len(norm_sig) > 60:
            norm_sig = norm_sig[:120]
        if norm_sig in seen:
            continue
        seen.add(norm_sig)
        result.append(cleaned)
    return result

