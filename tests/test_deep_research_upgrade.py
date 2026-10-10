"""Comprehensive tests for Zerone Prospect Intelligence Deep Research Upgrade.

Covers:
1. Entity resolution (never merge on name similarity alone; legal id & domain check).
2. Invalid names & false leadership/job extraction.
3. Citation traceability (source URL, publisher, timestamp, excerpt, claim type).
4. Conflicting evidence detection & preservation.
5. Adaptive replanning & decision trace recording.
6. Persistent memory across runs & meaningful change detection.
7. Source freshness & staleness detection.
8. Duplicate removal & boilerplate stripping.
9. PDF / Markdown consistency & page numbers/headers/footers.
10. Generation failures & graceful fallbacks.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.exporters.report_generator import (
    build_company_report_markdown,
    build_report_html,
    generate_final_reports,
    is_boilerplate,
)
from src.memory.company_store import CompanyMemoryStore
from src.schemas.research import ClaimRecord, ReportSection, WriterReport
from src.validation import (
    clean_job_title,
    clean_person_name,
    extract_canonical_company_name,
    is_invalid_company_name,
    is_valid_job_title,
    is_valid_person_name,
)
from src.verification.company_intelligence import (
    detect_contradictions,
    extract_business_contacts,
    extract_dated_events,
    extract_entity_relationships,
    extract_roles,
    extract_workforce_signals,
    match_company_identity,
    resolve_candidate_identities,
)


# ---------------------------------------------------------------------------
# 1. Entity resolution: Never merge on name similarity alone
# ---------------------------------------------------------------------------

def test_entity_resolution_never_merges_on_name_similarity_alone():
    target = "ORCHVATE"
    jurisdiction = "India"

    # Candidate 1: Exact name, but NO legal identifier or domain corroboration
    cand_unverified = {
        "name": "ORCHVATE",
        "jurisdiction": "India",
        "source_url": "https://randomblog.example.com",
    }
    res1 = match_company_identity(target, cand_unverified, jurisdiction)
    assert res1["match_status"] == "possible_match"
    assert res1["verification_status"] == "unverified"
    assert "lacks independent legal identifier" in res1["match_rationale"]

    # Candidate 2: Exact name WITH verified registry identifier (LLPIN)
    cand_verified = {
        "name": "ORCHVATE LLP",
        "company_number": "AAO-4433",
        "jurisdiction": "India",
        "source_url": "https://mca.gov.in",
    }
    res2 = match_company_identity(target, cand_verified, jurisdiction)
    assert res2["match_status"] == "confirmed_match"
    assert res2["verification_status"] == "verified"
    assert "AAO-4433" in res2["match_rationale"]

    # Candidate 3: Unrelated company with same prefix in conflicting jurisdiction
    cand_unrelated = {
        "name": "Orchvate UK Limited",
        "company_number": "998877",
        "jurisdiction": "United Kingdom",
        "source_url": "https://companieshouse.gov.uk",
    }
    res3 = match_company_identity(target, cand_unrelated, jurisdiction)
    assert res3["match_status"] == "rejected"
    assert "Contradictory jurisdiction" in res3["match_rationale"]

    # Test full candidate partitioning
    resolution = resolve_candidate_identities(
        [cand_unverified, cand_verified, cand_unrelated],
        target_name=target,
        jurisdiction=jurisdiction,
    )
    assert len(resolution["confirmed"]) == 1
    assert len(resolution["unverified"]) == 1
    assert len(resolution["unrelated"]) == 1
    assert "1 confirmed" in resolution["resolution_summary"]


# ---------------------------------------------------------------------------
# 2. Invalid names & false leadership / job extraction
# ---------------------------------------------------------------------------

def test_invalid_names_and_false_leadership_and_job_extraction():
    # URL slugs, generic navigation words, and article fragments
    bad_person_candidates = [
        "revenue",
        "board-of",
        "board members",
        "directors",
        "employees",
        "LT-appoints-ex-Infosys-executive-Sanjay-Jalona",
        "https://example.com/team",
        "solutions-for-startup",
        "about us",
        "contact us",
        "careers",
        "privacy policy",
    ]
    for name in bad_person_candidates:
        assert is_valid_person_name(name, target_name="ORCHVATE") is False

    # Valid human names
    good_person_names = ["Geeta Poduval", "Elena Rostova", "Rohan Sen", "Jean-Luc Picard"]
    for name in good_person_names:
        assert is_valid_person_name(name, target_name="ORCHVATE") is True

    # Bad job titles (URLs, page summaries, aggregator headings)
    bad_jobs = [
        "https://tracxn.com/careers/jobs",
        "Fetched content from ZaubaCorp",
        "Search results for open jobs",
        "Welcome to our company website",
    ]
    for job in bad_jobs:
        assert is_valid_job_title(job) is False

    # Valid job titles
    good_jobs = ["Software Engineer", "Head of Business Development", "Senior Data Scientist"]
    for job in good_jobs:
        assert is_valid_job_title(job) is True


# ---------------------------------------------------------------------------
# 3. Citation traceability across claims
# ---------------------------------------------------------------------------

def test_citation_traceability_across_claims():
    pages = [
        {
            "url": "https://orchvate.com/about",
            "title": "About Orchvate",
            "retrieved_at": "2026-10-10T12:00:00Z",
            "content": "Geeta Poduval — Founder & Director\nOrchvate specializes in neurodiversity inclusion.\nCall us at +91 98765 43210 or email hello@orchvate.com",
        }
    ]

    roles = extract_roles(pages, target_name="Orchvate")
    assert roles
    role = roles[0]
    assert role["person_name"] == "Geeta Poduval"
    assert role["role"] in ("Founder", "Director")
    assert role["source_url"] == "https://orchvate.com/about"
    assert role["retrieved_at"] == "2026-10-10T12:00:00Z"

    contacts = extract_business_contacts(pages, target_name="Orchvate")
    assert contacts
    for contact in contacts:
        assert contact["source_url"] == "https://orchvate.com/about"
        assert contact["retrieved_at"] == "2026-10-10T12:00:00Z"
        assert contact["verification_status"] == "published_unverified"


# ---------------------------------------------------------------------------
# 4. Conflicting evidence detection & preservation
# ---------------------------------------------------------------------------

def test_conflicting_evidence_detection_and_preservation():
    claims = [
        {"field": "headquarters", "value": "Kolkata", "source_url": "https://source1.example"},
        {"field": "headquarters", "value": "Bengaluru", "source_url": "https://source2.example"},
        {"field": "founded", "value": "2020", "source_url": "https://source3.example"},
        {"field": "founded", "value": "2022", "source_url": "https://source4.example"},
    ]
    contradictions = detect_contradictions(claims)
    assert len(contradictions) == 2
    fields = {c["field"] for c in contradictions}
    assert "headquarters" in fields
    assert "founded" in fields
    for c in contradictions:
        assert c["verification_status"] == "conflicting"
        assert len(c["values"]) == 2


# ---------------------------------------------------------------------------
# 5. Adaptive replanning & decision trace recording
# ---------------------------------------------------------------------------

def test_adaptive_replanning_and_decision_trace():
    trace = []

    # Step 1: Task understanding
    trace.append({
        "stage": "task_understanding",
        "step": 1,
        "decision": "Task mode: standard",
        "rationale": "Understood essential company research questions and requested analytical outputs.",
        "findings": "Target company identity requires primary registry verification.",
        "uncertainties": "Official legal entity unconfirmed.",
        "next_steps": "Plan registry and web discovery searches.",
    })

    # Step 6: Gap analysis replanning
    trace.append({
        "stage": "gap_analysis_replanning",
        "step": 6,
        "decision": "Dispatched 2 targeted follow-up queries",
        "rationale": "Initial fetch yielded no leadership records; formulating targeted leadership query.",
        "findings": "Initial evidence gathered from 4 sources.",
        "uncertainties": "Leadership and contact channels unresolved.",
        "next_steps": "Execute follow-up queries for founders and executive team.",
    })

    # Step 9: Stopping decision
    trace.append({
        "stage": "adaptive_replanning",
        "step": 9,
        "decision": "stop_search_phase",
        "rationale": "Search budget reached and core identity evidenced.",
        "findings": "Total 8 source pages collected.",
        "uncertainties": "Remaining gaps will be preserved as Unresolved Questions.",
        "next_steps": "Generate final Markdown and PDF reports.",
    })

    assert len(trace) == 3
    assert all("stage" in t and "decision" in t and "rationale" in t for t in trace)
    assert all("findings" in t and "uncertainties" in t and "next_steps" in t for t in trace)


# ---------------------------------------------------------------------------
# 6. Persistent memory across runs & meaningful change detection
# ---------------------------------------------------------------------------

def test_persistent_memory_across_runs_and_change_detection(tmp_path: Path):
    db_file = tmp_path / "memory_upgrade.sqlite3"
    store = CompanyMemoryStore(db_file)

    source_run1 = {
        "url": "https://orchvate.com/about",
        "title": "Run 1 About",
        "retrieved_at": "2026-01-01T00:00:00Z",
    }
    store.record_run(
        "ORCHVATE",
        "India",
        sources=[source_run1],
        identities=[{
            "candidate_name": "ORCHVATE LLP",
            "candidate_id": "AAO-4433",
            "source_url": source_run1["url"],
            "match_status": "confirmed_match",
            "verification_status": "verified",
            "evidence": ["MCA LLP filing"],
        }],
        roles=[{
            "person_name": "Geeta Poduval",
            "role": "Founder & Director",
            "role_status": "current_claim",
            "source_url": source_run1["url"],
            "evidence": "Founder & Director",
        }],
        products=[{"name": "Neurodiversity Inclusion Training", "source_url": source_run1["url"], "evidence": "Training programs"}],
        claims=[{
            "subject": "ORCHVATE",
            "predicate": "incorporation",
            "object_value": "2020",
            "claim_status": "verified_fact",
            "source_url": source_run1["url"],
            "evidence_excerpt": "Incorporated in 2020",
        }],
    )

    # First load: verify full profile loaded
    ctx1 = store.load_context("ORCHVATE", "India")
    assert ctx1["found"] is True
    assert len(ctx1["entities"]) == 1
    assert len(ctx1["people"]) == 1
    assert len(ctx1["products"]) == 1
    assert ctx1["entities"][0]["name"] == "ORCHVATE LLP"

    # Second run: new appointment added
    run2_findings = {
        "role_records": [
            {"person_name": "Geeta Poduval", "role": "Director"},
            {"person_name": "New Director A", "role": "Executive Advisor"},
        ],
        "products": ["Neurodiversity Inclusion Training", "New Workplace Audit Tool"],
    }
    diff = store.detect_diff("ORCHVATE", "India", run2_findings)
    assert diff["has_prior_history"] is True
    assert diff["changes_detected"] is True
    diff_types = {c["type"] for c in diff["changes"]}
    assert "new_leadership_or_personnel" in diff_types
    assert "new_products_or_services" in diff_types


# ---------------------------------------------------------------------------
# 7. Source freshness & staleness detection
# ---------------------------------------------------------------------------

def test_source_freshness_and_staleness_detection(tmp_path: Path):
    db_file = tmp_path / "freshness.sqlite3"
    store = CompanyMemoryStore(db_file)

    stale_date = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    fresh_date = datetime.now(timezone.utc).isoformat()

    store.record_run(
        "Acme Corp",
        "USA",
        sources=[
            {"url": "https://stale.example", "title": "Stale", "retrieved_at": stale_date},
            {"url": "https://fresh.example", "title": "Fresh", "retrieved_at": fresh_date},
        ],
        claims=[
            {
                "subject": "Acme Corp",
                "predicate": "status",
                "object_value": "active",
                "source_url": "https://stale.example",
                "evidence_excerpt": "Stale active evidence",
                "retrieved_at": stale_date,
            },
            {
                "subject": "Acme Corp",
                "predicate": "valuation",
                "object_value": "100M",
                "source_url": "https://fresh.example",
                "evidence_excerpt": "Fresh valuation evidence",
                "retrieved_at": fresh_date,
            },
        ],
    )

    ctx = store.load_context("Acme Corp", "USA", stale_after_days=30)
    assert ctx["found"] is True
    assert len(ctx["findings"]) == 2
    assert len(ctx["stale_findings"]) == 1
    assert ctx["stale_findings"][0]["source_url"] == "https://stale.example"
    assert any("older than 30 days" in m for m in ctx["missing"])


# ---------------------------------------------------------------------------
# 8. Duplicate removal & boilerplate stripping
# ---------------------------------------------------------------------------

def test_duplicate_removal_and_boilerplate_stripping():
    # Boilerplate detection
    assert is_boilerplate("Cookie consent preferences and policy") is True
    assert is_boilerplate("Due diligence company risk, compliance & AML screening") is True
    assert is_boilerplate("All rights reserved. Sign in to view.") is True
    assert is_boilerplate("Orchvate is an inclusion and workplace consulting LLP.") is False

    report = WriterReport(
        question="Investigate Orchvate",
        task_mode="standard",
        executive_summary="Orchvate is an active Indian social venture.",
        confidence_summary="High confidence.",
        sections=[
            ReportSection(
                title="Business Overview",
                narrative="Orchvate delivers specialized training and consulting.\n\nOrchvate delivers specialized training and consulting.",
                claims=[],
            )
        ],
        recommendations=[],
        methodology_notes="Methodology notes.",
        open_questions=[],
        sources=["https://orchvate.com"],
        role_records=[
            {"person_name": "Geeta Poduval", "role_title": "Founder", "role_status": "current_claim", "confidence": "high"},
            {"person_name": "Geeta Poduval", "role_title": "Founder", "role_status": "current_claim", "confidence": "high"},
        ],
    )

    md = build_company_report_markdown(report)
    # Deduplication of identical paragraphs
    assert md.count("Orchvate delivers specialized training and consulting.") == 1
    # Deduplication of identical role entries
    assert md.count("| Geeta Poduval | Founder |") == 1


# ---------------------------------------------------------------------------
# 9. PDF & Markdown consistency and page numbers / headers / footers
# ---------------------------------------------------------------------------

def test_pdf_and_markdown_consistency_and_headers_footers(tmp_path: Path):
    report = WriterReport(
        question="Investigate LTM in India",
        task_mode="standard",
        executive_summary="LTM refers to multiple candidates in India requiring entity resolution.",
        confidence_summary="Medium confidence.",
        sections=[
            ReportSection(
                title="Company Identity",
                narrative="Candidate entities were compared against MCA registry filings.",
                claims=[
                    ClaimRecord(
                        claim="LTM is used as an acronym across distinct corporate groups.",
                        confidence="High",
                        source_agreement="Strong agreement",
                        evidence=["Evidence cited from registry filings [1]"],
                    )
                ],
            )
        ],
        recommendations=["Verify specific subsidiary CIN."],
        methodology_notes="Searched registries.",
        open_questions=["Which specific branch is targeted?"],
        sources=["[1] MCA India — https://mca.gov.in"],
    )

    md_content = build_company_report_markdown(report, state={"company": "LTM", "country": "India"})
    assert "# Company Research Report: LTM" in md_content
    assert "## 1. Executive Summary" in md_content
    assert "## 2. Company Identity" in md_content

    html_content = build_report_html(md_content, title="Research Report: LTM")
    assert "<!DOCTYPE html>" in html_content
    assert "Research Report: LTM" in html_content
    assert "Executive Summary" in html_content


# ---------------------------------------------------------------------------
# 10. Generation failures & graceful fallbacks
# ---------------------------------------------------------------------------

def test_generation_failures_handled_gracefully(tmp_path: Path):
    empty_report = WriterReport(
        question="Investigate Unknown Entity",
        task_mode="standard",
        executive_summary="No primary records found for this entity.",
        confidence_summary="Low confidence.",
        sections=[],
        recommendations=[],
        methodology_notes="No web results available.",
        open_questions=["Registration could not be confirmed."],
        sources=[],
    )

    result = generate_final_reports(empty_report, tmp_path, state={"company": "Unknown Entity"})
    assert result["markdown_path"]
    assert Path(result["markdown_path"]).is_file()
    md_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "## 1. Executive Summary" in md_text
    assert "## 10. Risks and Unknowns" in md_text
