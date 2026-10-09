from src.verification.company_intelligence import (
    classify_registry_outcome,
    classify_role_status,
    detect_contradictions,
    extract_business_contacts,
    extract_dated_events,
    extract_roles,
    match_company_identity,
    search_companies_house,
)


def test_identity_matching_distinguishes_confirmed_possible_and_rejected():
    confirmed = match_company_identity(
        "ORCHVATE", {"name": "Orchvate Ltd", "company_number": "123", "jurisdiction": "United Kingdom"}, "United Kingdom"
    )
    possible = match_company_identity("ORCHVATE", {"name": "Orchvate Services", "jurisdiction": "United Kingdom"}, "United Kingdom")
    rejected = match_company_identity("ORCHVATE", {"name": "Orchid Ventures", "jurisdiction": "United Kingdom"}, "United Kingdom")
    assert confirmed["match_status"] == "confirmed_match"
    assert possible["match_status"] == "possible_match"
    assert rejected["match_status"] == "rejected"
    assert confirmed["verification_status"] == "verified"


def test_registry_outcomes_are_explicit_about_completed_searches():
    assert classify_registry_outcome(attempted=True, records=[], error=None)["outcome"] == "no_match_in_completed_searches"
    assert classify_registry_outcome(attempted=False, records=[], error=None)["outcome"] == "inconclusive_verification"
    assert classify_registry_outcome(
        attempted=True, records=[{"match_status": "possible_match"}], error=None
    )["outcome"] == "possible_match"


def test_companies_house_client_avoids_network_without_key():
    import asyncio
    result = asyncio.run(search_companies_house("ORCHVATE", api_key=""))
    assert result["outcome"] == "inconclusive_verification"
    assert "not configured" in result["error"]


def test_role_status_distinguishes_current_claim_from_historical():
    assert classify_role_status("Alex Smith — CEO") == "current_claim"
    assert classify_role_status("Former CEO Alex Smith") == "historical"


def test_dated_events_keep_date_and_source_provenance():
    events = extract_dated_events([
        {"url": "https://example.com/news", "retrieved_at": "now", "content": "Founded in March 2020 after a partnership."}
    ])
    assert events[0]["event_type"] == "founded"
    assert events[0]["event_date"] == "March 2020"
    assert events[0]["source_url"] == "https://example.com/news"
    assert events[0]["verification_status"] == "candidate"


def test_contradictions_are_preserved_without_selecting_a_winner():
    contradictions = detect_contradictions([
        {"field": "headquarters", "value": "Bengaluru", "source_url": "https://a.example"},
        {"field": "headquarters", "value": "London", "source_url": "https://b.example"},
    ])
    assert len(contradictions) == 1
    assert contradictions[0]["field"] == "headquarters"
    assert contradictions[0]["verification_status"] == "conflicting"
    assert len(contradictions[0]["values"]) == 2


def test_contacts_are_published_unverified_and_never_confirmed_as_deliverable():
    contacts = extract_business_contacts([
        {
            "url": "https://orchvate.example/contact",
            "retrieved_at": "now",
            "content": "Email us at hello@orchvate.example or visit https://orchvate.example/contact.",
        }
    ])
    assert any(item["contact_type"] == "email" for item in contacts)
    assert all(item["verification_status"] == "published_unverified" for item in contacts)
    assert all(item["source_url"] == "https://orchvate.example/contact" for item in contacts)


def test_role_extraction_keeps_page_retrieval_provenance():
    roles = extract_roles([
        {
            "url": "https://example.com/team",
            "retrieved_at": "now",
            "content": "Jane Doe — Founder\nFormer CEO Alex Smith",
        }
    ])
    assert roles
    assert any(item["role_status"] == "current_claim" for item in roles)
    assert all(item["source_url"] == "https://example.com/team" for item in roles)
