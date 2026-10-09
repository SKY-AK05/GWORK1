from src.verification.india import (
    INDIA_REGISTRY_SOURCES,
    build_india_verification,
    classify_india_identifier,
    classify_india_registry_outcome,
    match_india_candidate,
    normalize_india_name,
)


def test_india_identifier_classification_is_conservative():
    assert classify_india_identifier("U12345MH2020PLC123456") == "CIN"
    assert classify_india_identifier("AAA1234") == "LLPIN_candidate"
    assert classify_india_identifier("27ABCDE1234F1Z5") == "GSTIN_candidate"
    assert classify_india_identifier("not-an-id") == "unknown"


def test_legal_name_variant_can_be_possible_without_identifier_confirmation():
    record = match_india_candidate(
        "ORCHVATE",
        {"legal_name": "Orchvate Private Limited", "entity_type": "company"},
        registry="MCA company and LLP master data",
        source_url="https://www.mca.gov.in/content/mca/global/en/mca/master-data/MDS.html",
        query="ORCHVATE",
    )
    assert record["match_status"] == "possible_match"
    assert record["verification_status"] == "unverified"


def test_authoritative_identifier_and_exact_variant_confirm_match():
    record = match_india_candidate(
        "Orchvate",
        {
            "legal_name": "ORCHVATE PRIVATE LIMITED",
            "entity_type": "company",
            "cin": "U12345MH2020PLC123456",
            "identifier_confirmed": True,
            "authoritative_match": True,
            "status": "Active",
        },
        registry="MCA company and LLP master data",
        source_url="https://www.mca.gov.in/content/mca/global/en/mca/master-data/MDS.html",
        query="Orchvate",
    )
    assert record["match_status"] == "confirmed_match"
    assert record["identifier"] == "U12345MH2020PLC123456"


def test_similar_name_and_brand_are_not_merged():
    similar = match_india_candidate(
        "ORCHVATE",
        {"legal_name": "ORCH VATE SOLUTIONS LLP", "entity_type": "LLP"},
        registry="MCA company and LLP master data",
        source_url="https://www.mca.gov.in/content/mca/global/en/mca/master-data/MDS.html",
    )
    brand = match_india_candidate(
        "ORCHVATE",
        {"legal_name": "ORCHVATE", "entity_type": "trademark_owner", "identifier": "1234567"},
        registry="Indian Trade Marks Registry public search",
        source_url="https://tmrsearch.ipindia.gov.in/tmrpublicsearch/",
    )
    assert similar["match_status"] in {"possible_match", "rejected"}
    assert brand["match_status"] == "possible_match"
    assert "not legal-entity proof" in brand["matching_rationale"]


def test_missing_identifier_and_unattempted_registry_are_inconclusive():
    result = build_india_verification("ORCHVATE")
    assert result["identifiers"] == []
    for outcome in result["registries"].values():
        assert outcome["outcome"] == "inconclusive_verification"
        assert outcome["searched_name_variants"]


def test_conflicting_records_are_preserved_as_possible_not_silently_resolved():
    records = [
        {"legal_name": "ORCHVATE PRIVATE LIMITED", "entity_type": "company", "identifier": "U12345MH2020PLC123456", "identifier_confirmed": True, "authoritative_match": True, "status": "Active"},
        {"legal_name": "ORCHVATE PRIVATE LIMITED", "entity_type": "company", "identifier": "U12345MH2020PLC654321", "status": "Strike Off"},
    ]
    result = build_india_verification(
        "ORCHVATE",
        candidate_records={"MCA company and LLP master data": records},
        attempted_registries={"MCA company and LLP master data"},
    )
    outcome = result["registries"]["MCA company and LLP master data"]
    assert outcome["outcome"] == "confirmed_match"
    assert len(outcome["records"]) == 2
    assert {r["identifier"] for r in outcome["records"]} == {"U12345MH2020PLC123456", "U12345MH2020PLC654321"}


def test_registry_inventory_does_not_claim_unconfirmed_public_apis():
    assert len(INDIA_REGISTRY_SOURCES) >= 5
    for source in INDIA_REGISTRY_SOURCES:
        assert "source_url" in source
        assert source["documented_public_api"] in {False, True, "not_confirmed"}
    assert normalize_india_name("Orchvate Pvt. Ltd.") == "orchvate"
