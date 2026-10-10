from src.memory.company_store import CompanyMemoryStore


def test_company_memory_preserves_history_and_requires_source_linked_claims(tmp_path):
    store = CompanyMemoryStore(tmp_path / "company.sqlite3")
    source = {"url": "https://example.com/about", "title": "Official About", "source_category": "official", "retrieved_at": "2020-01-01T00:00:00+00:00"}
    first = store.record_run(
        "ORCHVATE", "India", sources=[source],
        identities=[{"candidate_name": "ORCHVATE LLP", "candidate_id": "AAO-4433", "source_url": source["url"], "match_status": "possible_match", "confidence": "medium", "verification_status": "candidate", "evidence": ["registry listing"]}],
        aliases=[{"alias": "ORCHVATE", "source_url": source["url"], "evidence": "brand name"}],
        claims=[{"subject": "ORCHVATE", "predicate": "headquarters", "object_value": "Kolkata", "claim_status": "secondary_claim", "confidence": "medium", "verification_status": "candidate", "source_url": source["url"], "evidence_excerpt": "Kolkata"}, {"subject": "ORCHVATE", "predicate": "customers", "object_value": "Unknown", "claim_status": "unknown", "confidence": "low", "verification_status": "unknown", "evidence_excerpt": "missing source"}],
    )
    assert first["claims_added"] == 1

    store.record_run(
        "ORCHVATE", "India", sources=[{"url": "https://example.com/news", "title": "News", "source_category": "news"}],
        claims=[{"subject": "ORCHVATE", "predicate": "headquarters", "object_value": "Bengaluru", "claim_status": "secondary_claim", "confidence": "low", "verification_status": "conflicting", "source_url": "https://example.com/news", "evidence_excerpt": "Bengaluru"}],
    )
    context = store.load_context("ORCHVATE", "India", stale_after_days=30)
    assert context["found"] is True
    assert len(context["findings"]) == 2
    assert context["stale_findings"]
    assert context["conflicts"]
    summary = store.summary("ORCHVATE", "India")
    assert summary["findings"] == 2
