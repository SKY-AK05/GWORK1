import json
from pathlib import Path

from webapp.discovery import discover_companies
from webapp.server import ALLOWED_ARTIFACTS
from src.utils.url_utils import is_safe_public_url


def test_blank_name_requires_narrowing_filter():
    result = discover_companies("", "India")
    assert result["status"] == "needs_filter"
    assert "narrowing filter" in result["error"]


def test_orchvate_discovery_returns_distinct_source_backed_candidates():
    result = discover_companies("Orch", "India")
    assert result["status"] in {"ready", "partial"}
    assert len(result["candidates"]) >= 2
    ids = {item["candidate_id"] for item in result["candidates"]}
    assert len(ids) == len(result["candidates"])
    assert all(item["source_url"].startswith("https://") for item in result["candidates"])
    assert any(item["registration_number"] == "AAO-4433" for item in result["candidates"])
    assert len(result["identity_groups"]) == 1
    group = result["identity_groups"][0]
    assert group["resolution"] == "possible_same_company"
    assert len(group["records"]) == 2
    assert group["canonical_candidate"]["registration_number"] == "AAO-4433"
    assert group["evidence_gaps"]


def test_unknown_company_uses_bounded_search_or_actionable_provider_error():
    result = discover_companies("Asterion", "Singapore")
    assert result["status"] in {"ready", "partial"}
    assert result["page_size"] <= 20


def test_unsafe_known_website_is_not_retained():
    result = discover_companies("Orchvate", "India", website="http://127.0.0.1:8000")
    assert all(item.get("website") != "http://127.0.0.1:8000" for item in result["candidates"])


def test_ssrf_boundary_and_artifact_allowlist():
    assert is_safe_public_url("https://example.com")
    assert not is_safe_public_url("http://127.0.0.1:8000")
    assert not is_safe_public_url("file:///etc/passwd")
    assert "company_research.json" in ALLOWED_ARTIFACTS
    assert "../../.env" not in ALLOWED_ARTIFACTS


def test_multi_source_same_company_resolution():
    from webapp.discovery import _link_identity_records, _candidate

    candidates = [
        _candidate(
            "LTIMindtree is now LTM | It's time to Outcreate", "India",
            source="https://www.ltm.com", source_title="LTIMindtree is now LTM | It's time to Outcreate",
            description="LTM is an AI-centric global technology services company and the Business Creativity partner to the world's largest enterprises.",
        ),
        _candidate(
            "LTM - LinkedIn", "India",
            source="https://www.linkedin.com/company/ltmindtree", source_title="LTM - LinkedIn",
            description="LTM — a Larsen & Toubro company — is an AI-centric global technology services company.",
        ),
        _candidate(
            "LTIMindtree - Wikipedia", "India",
            source="https://en.wikipedia.org/wiki/LTIMindtree", source_title="LTIMindtree - Wikipedia",
            description="LTM Limited (formerly LTIMindtree Limited) is an Indian multinational IT services company based in Mumbai. A subsidiary of Larsen & Toubro.",
        ),
        _candidate(
            "LTM: AI-Centric Technology & Business Creativity Partner", "India",
            source="https://www.ltm.com/about-us", source_title="LTM: AI-Centric Technology & Business Creativity Partner",
            description="LTM is an AI-centric global technology services company...",
        ),
    ]

    groups = _link_identity_records(candidates, query="LTM")
    assert len(groups) == 1
    group = groups[0]
    assert group["resolution"] == "confirmed_same_company"
    assert "Same company confirmed" in group["resolution_label"]
    assert len(group["records"]) == 4
    # Explains to the user why they are linked
    assert "Verified as the same corporate entity across 4 sources" in group["resolution_reason"]
    assert "ltm.com" in group["resolution_reason"]
    # Canonical clean entity
    assert "LTM" in group["canonical_candidate"]["legal_name"]
    assert "ltm.com" in (group["canonical_candidate"]["website"] or "")


def test_distinct_companies_are_not_merged():
    from webapp.discovery import _link_identity_records, _candidate

    candidates = [
        _candidate(
            "Apex Auto Components Ltd", "India",
            source="https://apexauto.in", source_title="Apex Auto Components Ltd",
            description="Automotive equipment and transmission parts manufacturer in Pune.",
        ),
        _candidate(
            "Apex Laboratories Pvt Ltd", "India",
            source="https://apexlab.com", source_title="Apex Laboratories Pvt Ltd",
            description="Pharmaceuticals and healthcare formulations in Chennai.",
        ),
    ]

    groups = _link_identity_records(candidates, query="Apex")
    assert len(groups) == 2
    for g in groups:
        assert g["resolution"] == "distinct_record"
        assert "Distinct corporate record" in g["resolution_reason"]

