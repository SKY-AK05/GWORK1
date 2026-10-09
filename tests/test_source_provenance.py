from src.graph.nodes import (
    _access_status,
    _coverage_records,
    _deterministic_social_queries,
    _enrich_memo_sources,
    _extract_followable_links,
    _extract_social_terms,
    _source_category,
    _source_platform,
)


def test_source_platform_classification():
    assert _source_platform("https://www.linkedin.com/company/orchvate/") == "linkedin"
    assert _source_platform("https://instagram.com/orchvate") == "instagram"
    assert _source_platform("https://www.facebook.com/orchvate/") == "facebook"
    assert _source_platform("https://x.com/orchvate") == "x"
    assert _source_platform("https://www.youtube.com/@orchvate") == "youtube"
    assert _source_platform("https://www.tiktok.com/@orchvate") == "tiktok"
    assert _source_platform("https://find-and-update.company-information.service.gov.uk/company/123") == "registry"
    assert _source_platform("https://example.com/blog.html") == "blog"
    assert _source_category("linkedin") == "social"
    assert _source_category("registry") == "registry"


def test_access_status_is_observational_and_does_not_authenticate():
    assert _access_status("Public company description") == "fetched"
    assert _access_status("Agree & Join\nSign in to see more") == "partial_public"


def test_coverage_records_distinguish_fetched_and_not_attempted():
    search_results = [
        {"url": "https://example.com", "title": "Example"},
        {"url": "https://www.linkedin.com/company/orchvate/", "title": "Orchvate"},
    ]
    fetched_pages = [
        {"url": "https://example.com", "title": "Example", "content": "OK", "retrieved_at": "now"},
    ]
    records = {row["url"]: row for row in _coverage_records(search_results, fetched_pages)}
    assert records["https://example.com"]["access_status"] == "fetched"
    assert records["https://www.linkedin.com/company/orchvate/"]["access_status"] == "not_attempted"


def test_memo_sources_receive_pipeline_provenance_without_identity_inference():
    memo = {
        "sources": [
            {"title": "Orchvate", "url": "https://www.linkedin.com/company/orchvate/", "evidence": ["name"]}
        ]
    }
    state = {
        "source_coverage": [
            {
                "url": "https://www.linkedin.com/company/orchvate/",
                "platform": "linkedin",
                "source_category": "social",
                "discovery_method": "search_result",
                "access_status": "partial_public",
                "retrieved_at": "now",
            }
        ],
        "fetched_pages": [],
    }
    enriched = _enrich_memo_sources(memo, state)
    source = enriched["sources"][0]
    assert source["platform"] == "linkedin"
    assert source["access_status"] == "partial_public"
    assert source["identity_status"] == "unverified"


def test_deterministic_social_queries_are_bounded_to_company_tasks():
    queries = _deterministic_social_queries(
        "Investigate ORCHVATE as a company in the United Kingdom", "comprehensive"
    )
    assert any("linkedin.com/company" in query for query in queries)
    assert any("instagram.com" in query for query in queries)
    assert any("Companies House" in query for query in queries)
    assert _deterministic_social_queries("Compare two software frameworks", "comprehensive") == []


def test_followable_links_prioritize_allowlisted_social_hosts():
    pages = [
        {
            "url": "https://orchvate.example/index.html",
            "content": (
                "[Facebook](https://www.facebook.com/orchvate/) "
                "[Other](https://unrelated.example/profile) "
                "[Blog](https://orchvate.example/blog.html)"
            ),
        }
    ]
    links = _extract_followable_links(pages, max_links=2)
    assert "https://www.facebook.com/orchvate/" in links
    assert "https://unrelated.example/profile" not in links


def test_social_terms_are_extracted_without_claiming_ownership():
    pages = [{"content": "We support #Neurodiversity and mention @orchvate."}]
    assert _extract_social_terms(pages) == ["#Neurodiversity", "@orchvate"]
