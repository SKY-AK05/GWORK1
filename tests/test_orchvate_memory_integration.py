import asyncio
import json

from src.graph.nodes import persist_company_memory_node
from src.memory.company_store import CompanyMemoryStore


def test_orchvate_india_persistence_keeps_partial_identity_and_citation_links(tmp_path):
    db = tmp_path / "orchvate.sqlite3"
    state = {
        "memory_company_name": "ORCHVATE",
        "memory_jurisdiction": "India",
        "memory_db_path": str(db),
        "task": "Investigate ORCHVATE as an open company-identity question in India.",
        "identity_candidates": [{
            "candidate_name": "ORCHVATE LLP", "candidate_id": "AAO-4433",
            "match_status": "possible_match", "confidence": "medium",
            "verification_status": "candidate", "source_url": "https://registry.example/orchvate",
            "evidence": ["Secondary registry listing"],
        }],
        "entity_relationships": [{
            "relationship_type": "brand", "related_name": "orchvate.com",
            "confidence": "low", "verification_status": "candidate",
            "source_url": "https://orchvate.com", "evidence": "Domain lead; official ownership unresolved",
        }],
        "role_records": [], "dated_events": [], "workforce_signals": [], "hiring_signals": [],
        "fetched_pages": [],
        "memo": {"sources": [{"url": "https://registry.example/orchvate", "title": "Registry source", "source_category": "secondary", "retrieved_at": "2026-10-10T00:00:00+00:00"}]},
        "report": {"claim_ledger": [{
            "subject": "ORCHVATE LLP", "predicate": "registration_status", "object_value": "active",
            "claim_status": "secondary_claim", "confidence": "medium", "verification_status": "candidate",
            "source_url": "https://registry.example/orchvate", "evidence_excerpt": "Registry source reports active status.",
        }, {
            "subject": "ORCHVATE", "predicate": "website_ownership", "object_value": "unknown",
            "claim_status": "unknown", "confidence": "low", "verification_status": "unknown",
            "evidence_excerpt": "No source URL; should not be persisted as a claim.",
        }], "business_analysis": {}},
    }
    result = asyncio.run(persist_company_memory_node(state))
    assert result["durable_memory_status"]["claims_added"] == 1

    context = CompanyMemoryStore(db).load_context("ORCHVATE", "India")
    assert context["found"] is True
    assert len(context["findings"]) == 1
    claim = context["findings"][0]
    assert claim["source_url"] == "https://registry.example/orchvate"
    assert claim["evidence_excerpt"]
    assert claim["verification_status"] == "candidate"
