import os
import asyncio
from typing import Optional
import tempfile
from dotenv import load_dotenv
load_dotenv(verbose=True)

import httpx
try:
    from markitdown._base_converter import DocumentConverterResult
except ImportError:
    class DocumentConverterResult:
        def __init__(self, markdown: str = "", title: str = ""):
            self.markdown = markdown
            self.title = title

try:
    from crawl4ai import AsyncWebCrawler
except ImportError:
    AsyncWebCrawler = None

try:
    from firecrawl import AsyncFirecrawlApp
except ImportError:
    AsyncFirecrawlApp = None
from src.logger import logger

# Default timeout for web fetching (in seconds)
DEFAULT_FETCH_TIMEOUT = 15  # 15 seconds per fetch attempt


def is_probable_pdf_url(url: str) -> bool:
    """Best-effort heuristic for URLs that should skip HTML-oriented crawlers."""
    lowered = url.lower()
    pdf_signals = [
        ".pdf",
        "/pdf/",
        "/doi/pdf/",
        "download=pdf",
        "content-type=application/pdf",
        "mimetype=application/pdf",
        "/servlets/purl/",
    ]
    return any(signal in lowered for signal in pdf_signals)


async def fetch_pdf_url(url: str, timeout: int = DEFAULT_FETCH_TIMEOUT) -> Optional[DocumentConverterResult]:
    """Download a remote PDF and convert it to markdown locally."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
    except Exception:
        return None

    content_type = response.headers.get("content-type", "").lower()
    content = response.content
    if "application/pdf" not in content_type and not content.startswith(b"%PDF"):
        return None

    def _convert_pdf_bytes() -> Optional[DocumentConverterResult]:
        from src.tool.default_tools.markdown.mdconvert import MarkitdownConverter

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as temp_file:
            temp_file.write(content)
            temp_file.flush()
            converter = MarkitdownConverter()
            return converter.convert(temp_file.name)

    try:
        return await asyncio.to_thread(_convert_pdf_bytes)
    except Exception:
        return None

async def firecrawl_fetch_url(url: str, timeout: int = DEFAULT_FETCH_TIMEOUT):
    """Fetch content using Firecrawl with timeout."""
    if AsyncFirecrawlApp is None:
        return None
    try:
        app = AsyncFirecrawlApp(api_key=os.getenv("FIRECRAWL_API_KEY", None))

        # Wrap the scrape call with timeout
        response = await asyncio.wait_for(
            app.scrape(url),
            timeout=timeout
        )

        result = response.markdown
        return result
    except asyncio.TimeoutError:
        return None
    except Exception:
        return None

async def fetch_crawl4ai_url(url: str, timeout: int = DEFAULT_FETCH_TIMEOUT):
    """Fetch content from a given URL using the crawl4ai library with timeout."""
    if AsyncWebCrawler is None:
        return None
    try:
        async with AsyncWebCrawler() as crawler:
            # Wrap the arun call with timeout
            response = await asyncio.wait_for(
                crawler.arun(url=url),
                timeout=timeout
            )

            if response:
                result = response.markdown
                return result
            else:
                return None
    except asyncio.TimeoutError:
        return None
    except Exception:
        return None

async def fetch_url(url: str, timeout: int = DEFAULT_FETCH_TIMEOUT) -> Optional[DocumentConverterResult]:
    """Fetch content from a URL using Firecrawl and Crawl4AI with timeout.
    
    Args:
        url: The URL to fetch
        timeout: Timeout in seconds for each fetch attempt (default: 15)
    
    Returns:
        DocumentConverterResult if successful, None otherwise
    """
    failure_reasons = []
    try:
        if is_probable_pdf_url(url):
            logger.info(f"| 📄 Detected PDF-like URL, using direct PDF fetch: {url}")
            pdf_result = await fetch_pdf_url(url, timeout=timeout)
            if pdf_result:
                return pdf_result
            failure_reasons.append("PDF fetch attempted but did not detect/convert a valid PDF")

        # Try Firecrawl first with timeout
        if AsyncFirecrawlApp is None:
            failure_reasons.append("Firecrawl backend unavailable (python package `firecrawl` not installed)")
        elif not os.getenv("FIRECRAWL_API_KEY"):
            failure_reasons.append("Firecrawl backend unavailable (FIRECRAWL_API_KEY not set)")
        else:
            firecrawl_result = await firecrawl_fetch_url(url, timeout=timeout)
            if firecrawl_result:
                return DocumentConverterResult(
                    markdown=firecrawl_result,
                    title=f"Fetched content from {url}",
                )
            failure_reasons.append("Firecrawl fetch failed (timeout, blocked, or scrape error)")

        # Fallback to Crawl4AI with timeout
        if AsyncWebCrawler is None:
            failure_reasons.append("Crawl4AI backend unavailable (python package `crawl4ai` not installed)")
        else:
            crawl4ai_result = await fetch_crawl4ai_url(url, timeout=timeout)
            if crawl4ai_result:
                return DocumentConverterResult(
                    markdown=crawl4ai_result,
                    title=f"Fetched content from {url}",
                )
            failure_reasons.append("Crawl4AI fetch failed (timeout, missing browser, or crawl error)")

        pdf_result = await fetch_pdf_url(url, timeout=timeout)
        if pdf_result:
            logger.info(f"| 📄 Falling back to direct PDF fetch after generic fetch failure: {url}")
            return pdf_result
        failure_reasons.append("Final PDF fallback failed")

    except Exception:
        failure_reasons.append("Unexpected exception in fetch_url")
        return None
    
    if failure_reasons:
        logger.warning(
            "| ⚠️ fetch_url failed for %s. Reasons tried: %s",
            url,
            "; ".join(failure_reasons),
        )
    return None
