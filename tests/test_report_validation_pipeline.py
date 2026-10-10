"""Acceptance and regression tests for the report generation and data validation pipeline.

Tests proving:
1. "Investigate the name" cannot become a company name.
2. URL fragments and navigation labels cannot become people or job titles.
3. A missing registry match cannot automatically mean the entity does not exist.
4. Registry statuses remain consistent across sections.
5. Unsupported leadership or hiring claims are omitted or labelled unresolved.
6. Repeated paragraphs are removed without deleting distinct findings.
7. Markdown and PDF conclusions agree.
8. Existing tests continue to pass.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from src.validation import (
    extract_canonical_company_name,
    is_invalid_company_name,
    is_valid_person_name,
    clean_person_name,
    is_valid_job_title,
    clean_job_title,
    reconcile_registry_status,
    deduplicate_paragraphs,
    extract_pdf_content,
)
from src.verification.company_intelligence import extract_roles, extract_workforce_signals
from src.exporters.report_generator import build_company_report_markdown, generate_final_reports

REPO_ROOT = Path(__file__).resolve().parent.parent
LTM_DIR = REPO_ROOT / "reports" / "orchvate-india" / "ltm" / "20261010T102024Z"
ORCHVATE_DIR = REPO_ROOT / "reports" / "orchvate-india" / "orchvate" / "20261010T101439Z"


# ------------------------------------------------------------------------------
# Criterion 1: "Investigate the name" cannot become a company name
# ------------------------------------------------------------------------------

def test_investigate_the_name_cannot_become_company_name():
    """Prove that task prompts like 'Investigate the name' never become entity names."""
    invalid_candidates = [
        "Investigate the name",
        "investigate the name",
        "Investigate the name 'ORCHVATE'",
        "The Name",
        "company investigation",
        "Target Entity",
        "None",
        "N/A",
    ]
    for cand in invalid_candidates:
        assert is_invalid_company_name(cand) is True

    # Test extraction from various prompt formulations
    query_1 = "Investigate the name 'LTM' as an open company-identity question in India; do not assume the name identifies one business. Input name: LTM. Target jurisdiction/country: India."
    assert extract_canonical_company_name(query_1) == "LTM"

    query_2 = "Investigate the name 'ORCHVATE' as an open company-identity question in India. Input name: ORCHVATE."
    assert extract_canonical_company_name(query_2) == "ORCHVATE"

    query_3 = "Investigate Acme Robotics in United Kingdom"
    assert extract_canonical_company_name(query_3) == "Acme Robotics"

    # Even with empty state or prompt starting with 'Investigate the name', entity name is extracted cleanly
    report_data = {
        "question": query_1,
        "executive_summary": "Summary text",
        "identity_candidates": [{"name": "Investigate the name", "legal_name": "Investigate the name"}],
    }
    md = build_company_report_markdown(report_data)
    assert "# Company Research Report: LTM" in md
    assert "Investigate the name" not in md.splitlines()[0]
    # Check Section 2 table does not have 'Investigate the name' as legal or brand name
    assert "| **Legal Entity Name** | Investigate the name |" not in md
    assert "| **Brand / Trading Name** | Investigate the name |" not in md


# ------------------------------------------------------------------------------
# Criterion 2: URL fragments and navigation labels cannot become people or job titles
# ------------------------------------------------------------------------------

def test_url_fragments_and_nav_labels_cannot_become_people_or_job_titles():
    """Prove that generic words, URL slugs, and fetch strings are rejected as people/jobs."""
    bad_people = [
        "revenue",
        "board-of",
        "board members",
        "directors",
        "LT-appoints-ex-Infosys-executive-Sanjay-Jalona",
        "ltm",
        "https://example.com/team",
        "solutions-for-startup",
        "overview",
        "contact us",
    ]
    for bad in bad_people:
        assert is_valid_person_name(bad, target_name="LTM") is False

    valid_people = ["Sanjay Jalona", "Panchali Banerjee", "Geethanjali Ganapathy", "Elena Rostova"]
    for valid in valid_people:
        assert is_valid_person_name(valid) is True

    bad_jobs = [
        "Fetched content from https://tracxn.com/d/legal-entities/india/ltimindtree-limited/__Q7yw0JR",
        "https://example.com/jobs",
        "click here to view openings",
        "all rights reserved",
        "tracxn",
    ]
    for bad in bad_jobs:
        assert is_valid_job_title(bad) is False

    valid_jobs = ["Software Engineer", "Supervisor – Text Annotation", "Data Annotator", "VP of Engineering"]
    for valid in valid_jobs:
        assert is_valid_job_title(valid) is True


def test_extraction_functions_ignore_navigation_text_and_url_slugs():
    """Prove extract_roles and extract_workforce_signals ignore junk lines."""
    pages = [
        {
            "url": "https://example.com/about-ltm",
            "content": (
                "LTM leadership profile:\n"
                "revenue — CEO\n"
                "board-of — director\n"
                "board members — director\n"
                "LT-appoints-ex-Infosys-executive-Sanjay-Jalona — CEO\n"
                "Jane Doe — Founder\n"
            ),
            "retrieved_at": "2026-10-10",
        }
    ]
    roles = extract_roles(pages, target_name="LTM")
    extracted_names = [r["person_name"] for r in roles]
    assert "Jane Doe" in extracted_names
    assert "revenue" not in extracted_names
    assert "board-of" not in extracted_names
    assert "board members" not in extracted_names
    assert not any("LT-appoints" in n for n in extracted_names)

    # Scraped aggregator page with 'careers' in nav and URL as title
    agg_pages = [
        {
            "url": "https://tracxn.com/d/companies/orchvate",
            "title": "Fetched content from https://tracxn.com/d/companies/orchvate",
            "content": "Our operations cover remote and hybrid teams in London. Requirements: python, sql.",
            "retrieved_at": "2026-10-10",
        }
    ]
    workforce, hiring = extract_workforce_signals(agg_pages, target_name="ORCHVATE")
    assert len(hiring) == 0  # Ignored because aggregator without dedicated careers path


# ------------------------------------------------------------------------------
# Criterion 3: Missing registry match cannot mean entity does not exist
# ------------------------------------------------------------------------------

def test_missing_registry_match_does_not_infer_non_existence():
    """A failed or empty registry search is not proof of non-existence."""
    status_rec = reconcile_registry_status(
        jurisdiction="India",
        reg_outcome="inconclusive_verification",
        india_verification={"registries": {"MCA COMPANY AND LLP MASTER DATA": {"outcome": "inconclusive_verification"}}},
        has_registration_number=False,
    )
    assert status_rec["official_status"] == "inconclusive_verification"
    assert "not proof of non-existence" in status_rec["official_note"] or "inconclusive" in status_rec["official_note"]
    assert status_rec["reg_number_status"] == "unresolved"


# ------------------------------------------------------------------------------
# Criterion 4: Registry statuses remain consistent across sections
# ------------------------------------------------------------------------------

def test_registry_statuses_remain_consistent_across_sections():
    """Official registry outcome must agree between Section 2 table, text, and Section 11."""
    report_data = {
        "question": "Investigate the name 'ORCHVATE' as an open company-identity question in India. Input name: ORCHVATE. Target jurisdiction/country: India.",
        "identity_candidates": [{
            "legal_name": "ORCHVATE LLP",
            "registration_number": "AAO-4433",
            "jurisdiction": "India",
            "verification_status": "corroborated",
        }],
        "india_verification": {
            "registries": {
                "MCA COMPANY AND LLP MASTER DATA": {"outcome": "inconclusive_verification"}
            }
        },
        "registry_verification": {
            "outcome": "inconclusive_verification"
        }
    }
    md = build_company_report_markdown(report_data, state={"company": "ORCHVATE", "country": "India"})
    # Section 2 table
    assert "| **Registration / CIN / LLPIN** | AAO-4433 | corroborated_secondary |" in md
    assert "| **Official Registry Status** | inconclusive_verification |" in md
    # Section 11 answer 1
    assert "registry verification status: `inconclusive_verification`" in md
    # Must NOT have contradictory confirmed_match or no_match
    assert "| **Official Registry Status** | confirmed_match |" not in md


# ------------------------------------------------------------------------------
# Criterion 5: Unsupported leadership or hiring claims are omitted or labelled unresolved
# ------------------------------------------------------------------------------

def test_unsupported_leadership_and_hiring_labelled_unresolved():
    """When no authentic leadership or hiring is found, report states unresolved honestly."""
    report_data = {
        "question": "Investigate the name 'ORCHVATE' in India. Input name: ORCHVATE.",
        "role_records": [
            {"person_name": "revenue", "role_title": "CEO"},
            {"person_name": "board-of", "role_title": "director"},
        ],
        "hiring_signals": [
            {"position": "Fetched content from https://tracxn.com/...", "department": "General"},
        ],
    }
    md = build_company_report_markdown(report_data, state={"company": "ORCHVATE", "country": "India"})

    # Junk filtered out
    assert "revenue" not in md
    assert "board-of" not in md
    assert "Fetched content from" not in md

    # Explicit honest statements
    assert "No verified leadership records were established" in md
    assert "No active public hiring openings or verified job descriptions were identified" in md
    # Section 11 answers
    assert "No verified leadership records were confirmed from primary official registries" in md
    assert "No active verified job postings found in reviewed sources" in md


# ------------------------------------------------------------------------------
# Criterion 6: Repeated paragraphs are removed without deleting distinct findings
# ------------------------------------------------------------------------------

def test_repeated_paragraphs_deduplicated_between_sections():
    """Sections 4 and 5 must not print the exact same multi-line narrative twice."""
    shared_paragraph = (
        "Orchvate’s business model is best characterized as a social enterprise that monetizes a blend "
        "of data-annotation services, neurodiversity-oriented training, and inclusion consulting."
    )
    distinct_paragraph = (
        "Core product offerings include Computer Vision annotation pipelines, tailored for enterprise AI clients."
    )
    report_data = {
        "question": "Investigate the name 'ORCHVATE' in India. Input name: ORCHVATE.",
        "sections": [
            {
                "title": "Business model and purpose",
                "narrative": shared_paragraph,
            },
            {
                "title": "Products and services",
                "narrative": f"{shared_paragraph}\n\n{distinct_paragraph}",
                "claims": [{"claim": "Data annotation for computer vision", "confidence": "high"}],
            },
        ],
    }
    md = build_company_report_markdown(report_data, state={"company": "ORCHVATE", "country": "India"})
    # Shared paragraph must only appear once in the document
    assert md.count("Orchvate’s business model is best characterized as a social enterprise") == 1
    # Distinct product paragraph must be present
    assert distinct_paragraph in md


# ------------------------------------------------------------------------------
# Criterion 7: Markdown and PDF conclusions agree
# ------------------------------------------------------------------------------

def test_markdown_and_pdf_conclusions_agree(tmp_path):
    """Prove that generated PDF matches canonical Markdown conclusions."""
    report_data = {
        "question": "Investigate the name 'ORCHVATE' as an open company-identity question in India. Input name: ORCHVATE. Target jurisdiction/country: India.",
        "executive_summary": "Orchvate operates in India with focus on neuroinclusive data annotation.",
        "identity_candidates": [{
            "legal_name": "ORCHVATE LLP",
            "registration_number": "AAO-4433",
            "jurisdiction": "India",
            "verification_status": "corroborated",
        }],
        "india_verification": {
            "registries": {
                "MCA COMPANY AND LLP MASTER DATA": {"outcome": "inconclusive_verification"}
            }
        },
        "role_records": [],
        "hiring_signals": [],
    }
    res = generate_final_reports(report_data, tmp_path, state={"company": "ORCHVATE", "country": "India"})
    assert res["pdf_success"] is True

    md_text = Path(res["markdown_path"]).read_text(encoding="utf-8")
    assert "# Company Research Report: ORCHVATE" in md_text

    pdf_ext = extract_pdf_content(Path(res["pdf_path"]))
    pdf_text = pdf_ext["text"]

    # Conclusions agree between MD and PDF
    assert "ORCHVATE" in pdf_text
    assert "AAO-4433" in pdf_text
    assert "inconclusive_verification" in pdf_text
    assert "No verified leadership records were established" in pdf_text


# ------------------------------------------------------------------------------
# Acceptance Testing with Existing Fixtures (LTM and ORCHVATE)
# ------------------------------------------------------------------------------

@pytest.mark.skipif(not LTM_DIR.exists(), reason="LTM fixture directory not found")
def test_ltm_fixture_report_generation_clean():
    """Test generating report from LTM fixture data."""
    json_path = LTM_DIR / "company_research.json"
    meta_path = LTM_DIR / "run_metadata.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    state = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    md = build_company_report_markdown(data, state=state)

    # 1. Company name is LTM, not 'Investigate the name'
    assert "# Company Research Report: LTM" in md
    assert "Investigate the name" not in md.splitlines()[0]

    # 2. Section 7 has NO 'revenue', 'board-of', or URL slugs
    sec7_idx = md.find("## 7. Leadership and Workforce")
    sec8_idx = md.find("## 8. Hiring Activity")
    sec7_text = md[sec7_idx:sec8_idx]
    assert "| revenue |" not in sec7_text
    assert "| board-of |" not in sec7_text
    assert "| board members |" not in sec7_text
    assert "LT-appoints" not in sec7_text

    # 3. Section 8 has NO 'Fetched content from' as a job role
    sec9_idx = md.find("## 9. Recent Developments")
    sec8_text = md[sec8_idx:sec9_idx]
    assert "Fetched content from" not in sec8_text

    # 4. Section 10 has NO raw dict dump
    sec10_idx = md.find("## 10. Risks and Unknowns")
    sec11_idx = md.find("## 11. Direct Answers to the Original Questions")
    sec10_text = md[sec10_idx:sec11_idx]
    assert "{'field':" not in sec10_text


@pytest.mark.skipif(not ORCHVATE_DIR.exists(), reason="ORCHVATE fixture directory not found")
def test_orchvate_fixture_report_generation_clean():
    """Test generating report from ORCHVATE fixture data."""
    json_path = ORCHVATE_DIR / "company_research.json"
    meta_path = ORCHVATE_DIR / "run_metadata.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    state = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    md = build_company_report_markdown(data, state=state)

    # 1. Company name is ORCHVATE
    assert "# Company Research Report: ORCHVATE" in md
    assert "Investigate the name" not in md.splitlines()[0]

    # 2. Section 2 has AAO-4433 or proper LLP details, and NO contradiction
    assert "| **Brand / Trading Name** | ORCHVATE |" in md
    assert "Investigate the name" not in md.splitlines()[18:28]

    # 3. Section 8 has NO 'Fetched content from'
    sec8_idx = md.find("## 8. Hiring Activity")
    sec9_idx = md.find("## 9. Recent Developments")
    sec8_text = md[sec8_idx:sec9_idx]
    assert "Fetched content from" not in sec8_text
