from src.graph.nodes import _build_prospect_record
from src.schemas.research import ResearchMemo, ResearchSource, WriterReport


def test_prospect_record_contains_required_storage_fields_and_evidence():
    source = ResearchSource(
        title="Official site",
        url="https://example.com",
        evidence=["The company describes its service."],
        platform="website",
        source_category="official",
        discovery_method="search_result",
        access_status="fetched",
        identity_status="candidate",
        retrieved_at="2026-10-10T00:00:00+00:00",
    )
    memo = ResearchMemo(
        question="Investigate ACME as a company in the United Kingdom.",
        search_plan=["ACME UK official website"],
        summary="A public brand was found.",
        sources=[source],
        open_questions=["What is the legal entity name?"],
    )
    report = WriterReport(
        question=memo.question,
        executive_summary="A public brand was found, but legal registration is unresolved.",
        sections=[],
        recommendations=[],
        methodology_notes="Test fixture.",
        confidence_summary="Medium.",
        open_questions=memo.open_questions,
        sources=["[1] Official site — https://example.com"],
    )
    record = _build_prospect_record(
        {
            "task": memo.question,
            "identity_candidates": [{"candidate_name": "ACME", "match_status": "possible_match"}],
            "registry_verification": {"outcome": "inconclusive_verification", "records": []},
        },
        report,
        memo,
    )
    assert record.brand_name == "ACME"
    assert record.official_domain == "example.com"
    assert record.jurisdiction == "United Kingdom"
    assert record.identity_match_status == "possible_match"
    assert record.evidence[0]["source_url"] == "https://example.com"
