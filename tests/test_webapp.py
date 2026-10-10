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
