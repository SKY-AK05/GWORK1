import asyncio

from src.graph.nodes import _split_fetch_results
from src.schemas.research import ResearchMemo, WriterReport
from src.tools.web_search import WebSearchTool
from src.tool.types import ToolExtra, ToolResponse


class FlakyBackend:
    name = "flaky_provider"

    def __init__(self):
        self.calls = 0

    async def __call__(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return ToolResponse(success=False, message="temporary timeout token=secret")
        return ToolResponse(
            success=True,
            message="ok",
            extra=ToolExtra(data={"search_items": [{"url": "https://example.com", "title": "Example", "description": "snippet"}]}),
        )


class AlwaysFailBackend:
    name = "failing_provider"

    def __init__(self):
        self.calls = 0

    async def __call__(self, **kwargs):
        self.calls += 1
        raise TimeoutError("provider timeout")


def test_search_backend_retries_once_and_records_success_without_secret():
    tool = WebSearchTool()
    backend = FlakyBackend()
    results = asyncio.run(tool._try_backend(backend, query="ORCHVATE"))
    assert results[0]["url"] == "https://example.com"
    assert backend.calls == 2
    assert tool.last_attempts[0]["status"] == "failed"
    assert tool.last_attempts[-1]["status"] == "success"
    assert "secret" not in str(tool.last_attempts)


def test_search_backend_has_strict_retry_limit_and_timeout_reason():
    tool = WebSearchTool()
    backend = AlwaysFailBackend()
    results = asyncio.run(tool._try_backend(backend, query="ORCHVATE"))
    assert results == []
    assert backend.calls == 2
    assert len(tool.last_attempts) == 2
    assert all(item["reason"] == "timeout" for item in tool.last_attempts)
    assert tool.last_attempts[-1]["retryable"] is False


def test_split_fetch_results_preserves_pages_and_failure_records():
    pages, failures = _split_fetch_results([
        {"url": "https://ok.example", "title": "OK", "content": "content"},
        {"_fetch_failure": True, "url": "https://blocked.example", "failure_type": "access_or_rate_limited", "reason": "403"},
    ])
    assert [page["url"] for page in pages] == ["https://ok.example"]
    assert failures == [{"url": "https://blocked.example", "failure_type": "access_or_rate_limited", "reason": "403"}]


def test_schemas_accept_incomplete_run_failure_records():
    memo = ResearchMemo(
        question="ORCHVATE", search_plan=["ORCHVATE"], summary="incomplete", sources=[], open_questions=["retry"],
        search_failures=[{"provider": "ddgs", "reason": "timeout"}], fetch_failures=[], run_status="blocked"
    )
    report = WriterReport(
        question="ORCHVATE", executive_summary="incomplete", sections=[], recommendations=[],
        methodology_notes="blocked", confidence_summary="insufficient", open_questions=["retry"], sources=[],
        search_failures=memo.search_failures, fetch_failures=[], run_status="blocked"
    )
    assert memo.run_status == "blocked"
    assert report.search_failures[0]["reason"] == "timeout"
