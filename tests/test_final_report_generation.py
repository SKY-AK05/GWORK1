"""Comprehensive unit and integration tests for automatic Markdown and PDF report generation."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.exporters.report_generator import (
    build_company_report_markdown,
    build_report_html,
    generate_final_reports,
    retry_pdf_generation,
    is_boilerplate,
)
from src.schemas.research import ClaimRecord, ReportSection, WriterReport
from src.validation import validate_product_artifacts, extract_pdf_content, validate_pdf_artifact


def _build_sample_report(company: str = "Acme Robotics", jurisdiction: str = "United Kingdom") -> WriterReport:
    """Build a generic structured report fixture."""
    return WriterReport(
        question=f"Investigate {company} in {jurisdiction}",
        task_mode="standard",
        executive_summary=f"{company} is an active technology enterprise developing autonomous warehouse systems in {jurisdiction}.",
        confidence_summary="High confidence on core entity identity and leadership; medium confidence on commercial contract scale.",
        sections=[
            ReportSection(
                title="Business Model and Operations",
                narrative=f"{company} operates a robotics-as-a-service model delivering logistics automation.",
                claims=[
                    ClaimRecord(
                        claim=f"{company} manufactures modular autonomous mobile robots.",
                        confidence="High",
                        source_agreement="Strong agreement",
                        evidence=[f"Confirmed via official company catalog [1] and press release [2]"],
                    )
                ],
                key_statistics=["500+ deployed units"],
            ),
            ReportSection(
                title="Products, Offerings and Services",
                narrative="Core offerings include heavy-payload AGVs and automated fleet dispatch software.",
                claims=[
                    ClaimRecord(
                        claim="Fleet dispatch system runs on proprietary edge computing units.",
                        confidence="Medium",
                        source_agreement="Mixed",
                        evidence=["Reported in technical trade review [3]"],
                    )
                ],
            ),
            ReportSection(
                title="Customer and Enterprise Partnerships",
                narrative="Serves tier-1 logistics operators and e-commerce distribution centers across Europe.",
                claims=[],
            ),
        ],
        recommendations=["Engage head of procurement for enterprise software evaluation."],
        methodology_notes="Searched national corporate registries, public news releases, and official web documentation.",
        open_questions=["Exact gross margin per deployed unit remains undisclosed in public filings."],
        sources=[
            "[1] Acme Robotics Official Website — https://acmerobotics.example.com",
            "[2] Robotics Weekly Funding Announcement — https://roboticsweekly.example.com/acme",
            "[3] Logistics Tech Review — https://logisticstech.example.com/review",
        ],
        registry_verification={"outcome": "confirmed_match", "status": "active"},
        identity_candidates=[
            {
                "name": f"{company} Ltd",
                "entity_type": "Private Limited",
                "jurisdiction": jurisdiction,
                "registration_number": "12345678",
                "match_status": "confirmed_match",
                "verification_status": "corroborated",
            }
        ],
        role_records=[
            {
                "person_name": "Elena Rostova",
                "role_title": "Chief Executive Officer & Co-Founder",
                "role_status": "current_claim",
                "confidence": "high",
                "source_url": "https://acmerobotics.example.com/team",
            },
            {
                "person_name": "Marcus Vance",
                "role_title": "Chief Technology Officer",
                "role_status": "current_claim",
                "confidence": "high",
                "source_url": "https://acmerobotics.example.com/team",
            },
        ],
        dated_events=[
            {
                "date": "2025-06-15",
                "description": f"{company} deployed 100 autonomous units at Manchester Distribution Hub.",
                "category": "Deployment",
                "source_url": "https://roboticsweekly.example.com/acme",
            }
        ],
        workforce_signals=[
            {"description": "Engineering team reported between 40-60 specialized systems engineers."}
        ],
        hiring_signals=[
            {
                "position": "Senior Embedded Systems Engineer",
                "department": "Robotics Engineering",
                "location": "London, UK",
                "arrangement": "Hybrid",
                "source_url": "https://acmerobotics.example.com/careers",
            }
        ],
        business_analysis={
            "purpose": "Automate industrial material handling through intelligent robotics.",
            "business_model": "Robotics-as-a-Service (RaaS) subscription plus maintenance contracts.",
            "target_markets": "Global 3PL operators, retail fulfillment, and manufacturing assembly.",
        },
        contradictions=[],
        business_contacts=[
            {"type": "press", "value": "press@acmerobotics.example.com"},
            {"type": "sales", "value": "sales@acmerobotics.example.com"},
        ],
    )


def test_markdown_report_structure_and_sections():
    """Verify that all 12 required sections are present and conclusion is placed first."""
    report = _build_sample_report("Acme Robotics", "United Kingdom")
    md = build_company_report_markdown(report, state={"company": "Acme Robotics", "country": "United Kingdom"})

    # Check 12 required sections
    assert "## 1. Executive Summary" in md
    assert "## 2. Company Identity" in md
    assert "## 3. Entity Comparison" in md
    assert "## 4. Business Overview" in md
    assert "## 5. Products and Services" in md
    assert "## 6. Customers and Partnerships" in md
    assert "## 7. Leadership and Workforce" in md
    assert "## 8. Hiring Activity" in md
    assert "## 9. Recent Developments" in md
    assert "## 10. Risks and Unknowns" in md
    assert "## 11. Direct Answers to the Original Questions" in md
    assert "## 12. Source References" in md

    # Check conclusion is first in Executive Summary
    summary_idx = md.index("## 1. Executive Summary")
    identity_idx = md.index("## 2. Company Identity")
    exec_text = md[summary_idx:identity_idx]
    assert "Acme Robotics is an active technology enterprise" in exec_text

    # Check uncertainty and confidence tags
    assert "[Verified Fact]" in md or "[Secondary Source]" in md


def test_clean_evidence_and_duplicate_removal():
    """Verify that crawler boilerplate, raw JSON dicts, and duplicate entries are stripped."""
    assert is_boilerplate("Get unrestricted viewing across everything we track") is True
    assert is_boilerplate("Due Diligence Company risk, compliance & transaction readiness") is True
    assert is_boilerplate("Cookie Policy and Preferences") is True
    assert is_boilerplate("Acme Robotics manufactures autonomous robots") is False

    report = _build_sample_report()
    # Inject crawler boilerplate and duplicate roles
    report.role_records.append({
        "person_name": "solutions-for-startup",
        "role_title": "founder",
        "role_status": "current_claim",
        "confidence": "medium",
    })
    report.role_records.append({
        "person_name": "Elena Rostova",  # Duplicate
        "role_title": "Chief Executive Officer & Co-Founder",
        "role_status": "current_claim",
        "confidence": "high",
    })
    report.business_contacts.append({
        "type": "aggregator",
        "value": "info@tracxn.com",  # Aggregator email
    })

    md = build_company_report_markdown(report)

    # Scraped junk must not appear
    assert "solutions-for-startup" not in md
    assert "info@tracxn.com" not in md

    # Duplicate person must only be listed once
    assert md.count("Elena Rostova") == 1


def test_missing_data_handled_gracefully():
    """Verify that reports handle missing data without failing or omitting sections."""
    minimal_report = WriterReport(
        question="Investigate Minimal Corp",
        task_mode="standard",
        executive_summary="Minimal Corp is an early-stage venture with limited public footprint.",
        confidence_summary="Low confidence due to sparse records.",
        sections=[],
        recommendations=[],
        methodology_notes="Public search conducted.",
        open_questions=["Entity registration could not be verified."],
        sources=[],
    )

    md = build_company_report_markdown(minimal_report, state={"company": "Minimal Corp"})

    # All sections should be present even with empty data
    assert "## 1. Executive Summary" in md
    assert "## 2. Company Identity" in md
    assert "## 7. Leadership and Workforce" in md
    assert "## 8. Hiring Activity" in md
    assert "## 9. Recent Developments" in md
    assert "## 12. Source References" in md
    assert "No active public hiring openings" in md


def test_full_markdown_and_pdf_generation(tmp_path: Path):
    """Verify end-to-end generation of both company_research_report.md and company_research_report.pdf."""
    report = _build_sample_report("Acme Robotics", "United Kingdom")
    res = generate_final_reports(report, tmp_path, state={"company": "Acme Robotics", "country": "United Kingdom"})

    md_path = tmp_path / "company_research_report.md"
    pdf_path = tmp_path / "company_research_report.pdf"

    assert md_path.is_file()
    assert md_path.stat().st_size > 500

    assert res["pdf_success"] is True
    assert pdf_path.is_file()
    assert pdf_path.stat().st_size > 1000

    # Validate PDF content extraction and section agreement
    pdf_eval = validate_pdf_artifact(pdf_path, expected_company="Acme Robotics")
    assert pdf_eval["valid"] is True
    assert pdf_eval["page_count"] >= 1
    assert pdf_eval["extracted_chars"] > 1000

    # Also check compatibility files
    assert (tmp_path / "final_report.md").is_file()
    assert (tmp_path / "final_report.pdf").is_file()


def test_pdf_failure_handling_and_retry(tmp_path: Path):
    """Verify that PDF generation failure preserves the Markdown report and allows retry."""
    report = _build_sample_report("Failover Corp", "India")

    # Mock Playwright failure
    with patch("src.exporters.report_generator.render_pdf_with_playwright", side_effect=RuntimeError("Playwright crashed")):
        with patch("src.exporters.report_generator.render_pdf_fallback", side_effect=RuntimeError("No LaTeX")):
            res = generate_final_reports(report, tmp_path, state={"company": "Failover Corp"})

    # Markdown must be intact
    assert (tmp_path / "company_research_report.md").is_file()
    assert res["pdf_success"] is False
    assert "Playwright crashed" in res["pdf_error"]

    # Now test retry works when engine is unmocked
    retry_res = retry_pdf_generation(tmp_path)
    assert retry_res["pdf_success"] is True
    assert (tmp_path / "company_research_report.pdf").is_file()


def test_multiple_company_runs_generic_fixtures(tmp_path: Path):
    """Verify report generation is generic across multiple companies without hardcoded assumptions."""
    companies = [
        ("Orchvate", "India", "social enterprise neurodiversity"),
        ("Zomato", "India", "food delivery logistics"),
        ("Acme Robotics", "United Kingdom", "autonomous warehouse systems"),
    ]

    for comp_name, country, summary_desc in companies:
        comp_dir = tmp_path / comp_name.lower().replace(" ", "_")
        report = WriterReport(
            question=f"Investigate {comp_name} in {country}",
            task_mode="standard",
            executive_summary=f"{comp_name} is an active enterprise focusing on {summary_desc} in {country}.",
            confidence_summary="High confidence.",
            sections=[],
            recommendations=[],
            methodology_notes="Authoritative registry query.",
            open_questions=[],
            sources=[f"[1] Official Site — https://{comp_name.lower().replace(' ', '')}.com"],
        )
        res = generate_final_reports(report, comp_dir, state={"company": comp_name, "country": country})
        assert res["pdf_success"] is True

        md_content = (comp_dir / "company_research_report.md").read_text(encoding="utf-8")
        assert f"# Company Research Report: {comp_name}" in md_content
        assert summary_desc in md_content
        assert (comp_dir / "company_research_report.pdf").is_file()


def test_artifact_validation_integration(tmp_path: Path):
    """Verify validate_product_artifacts checks both Markdown and PDF artifacts."""
    report = _build_sample_report("Valid Corp", "India")
    generate_final_reports(report, tmp_path, state={"company": "Valid Corp", "country": "India"})

    # Create dummy companion manifests
    (tmp_path / "company_research.json").write_text(json.dumps({
        "schema_version": "1.0", "run_id": "r-1", "question": "q", "executive_summary": "sum",
        "sections": [], "sources": [], "run_status": "completed",
    }), encoding="utf-8")
    (tmp_path / "sources.json").write_text(json.dumps({
        "schema_version": "1.0", "sources": [{"url": "https://example.com"}]
    }), encoding="utf-8")
    (tmp_path / "run_metadata.json").write_text(json.dumps({
        "report_paths": {
            "markdown": str(tmp_path / "company_research_report.md"),
            "pdf": str(tmp_path / "company_research_report.pdf"),
        }
    }), encoding="utf-8")

    validation = validate_product_artifacts(tmp_path, require_pdf=True)
    assert validation["valid"] is True
    assert validation["pdf_validated"] is True
    assert validation["pdf_page_count"] >= 1
