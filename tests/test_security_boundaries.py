import asyncio

from src.utils.url_utils import fetch_url, is_safe_public_url


def test_public_url_guard_rejects_unsafe_targets():
    assert is_safe_public_url("https://example.com/path")
    assert not is_safe_public_url("file:///etc/passwd")
    assert not is_safe_public_url("http://127.0.0.1:8080/")
    assert not is_safe_public_url("http://169.254.169.254/latest/meta-data/")
    assert not is_safe_public_url("http://user:password@example.com/")
    assert not is_safe_public_url("http://service.local/")


def test_fetch_url_blocks_unsafe_target_before_optional_backends(monkeypatch):
    called = False

    async def unexpected(*args, **kwargs):
        nonlocal called
        called = True
        return None

    monkeypatch.setattr("src.utils.url_utils.fetch_crawl4ai_url", unexpected)
    monkeypatch.setattr("src.utils.url_utils.fetch_pdf_url", unexpected)
    result = asyncio.run(fetch_url("http://127.0.0.1:9/"))
    assert result is None
    assert called is False


def test_retrieved_content_is_not_executed_as_code():
    # The crawler boundary returns data only; no shell/eval path is exposed.
    assert "exec(" not in open("src/utils/url_utils.py", encoding="utf-8").read()
    assert "subprocess" not in open("src/utils/url_utils.py", encoding="utf-8").read()
