"""LangChain-compatible web search tool.

Search priority:
  1. Tavily   — primary (best quality; requires TAVILY_API_KEY)
  2. Firecrawl — secondary (requires FIRECRAWL_API_KEY)
  3. DDGS      — last resort (free, no key required)

A backend is skipped silently if its API key is missing or if it raises an
error (including quota / credit exhaustion). The next backend in the chain
is tried automatically.
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any, List, Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr

from src.tool.default_tools.search import DDGSSearch, FirecrawlSearch, TavilySearch
from src.tool.types import ToolResponse


class WebSearchInput(BaseModel):
    query: str = Field(description="The search query to run")
    num_results: int = Field(default=5, description="Number of results to return")
    lang: str = Field(default="en", description="Language code")
    country: str = Field(default="us", description="Country code")
    filter_year: Optional[int] = Field(default=None, description="Filter results by year")


class WebSearchTool(BaseTool):
    """Search the web and return a list of {url, title, snippet} dicts.

    Tries backends in order: Tavily → Firecrawl → DDGS.
    Each backend is skipped if its API key is absent or if it returns an error.
    """

    name: str = "web_search"
    description: str = (
        "Search the web for real-time information. "
        "Returns a list of {url, title, snippet} dicts."
    )
    args_schema: Type[BaseModel] = WebSearchInput

    _tavily: TavilySearch = PrivateAttr()
    _firecrawl: FirecrawlSearch = PrivateAttr()
    _ddgs: DDGSSearch = PrivateAttr()
    _last_attempts: list = PrivateAttr(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        self._tavily = TavilySearch()
        self._firecrawl = FirecrawlSearch()
        self._ddgs = DDGSSearch()

    @property
    def last_attempts(self) -> list:
        """Diagnostics for the most recent query; credentials are never retained."""
        return list(self._last_attempts)

    # ------------------------------------------------------------------ #
    # BaseTool interface
    # ------------------------------------------------------------------ #

    def _run(
        self,
        query: str,
        num_results: int = 5,
        lang: str = "en",
        country: str = "us",
        filter_year: Optional[int] = None,
    ) -> List[dict]:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            self._arun(query=query, num_results=num_results, lang=lang,
                       country=country, filter_year=filter_year)
        )

    async def _arun(
        self,
        query: str,
        num_results: int = 5,
        lang: str = "en",
        country: str = "us",
        filter_year: Optional[int] = None,
    ) -> List[dict]:
        self._last_attempts = []
        kwargs = dict(query=query, num_results=num_results,
                      lang=lang, country=country, filter_year=filter_year)

        # 1. Tavily (primary)
        if os.getenv("TAVILY_API_KEY"):
            results = await self._try_backend(self._tavily, **kwargs)
            if results:
                return results

        # 2. Firecrawl (secondary)
        if os.getenv("FIRECRAWL_API_KEY"):
            results = await self._try_backend(self._firecrawl, **kwargs)
            if results:
                return results

        # 3. DDGS (free fallback — always attempted)
        return await self._try_backend(self._ddgs, **kwargs)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _safe_error(value: Any) -> str:
        text = re.sub(r"(?i)(api[_ -]?key|authorization|bearer|token)[=: ]+[^ ,;]+", r"\1=[REDACTED]", str(value))
        return text[:300]

    async def _try_backend(self, backend: Any, **kwargs) -> List[dict]:
        provider_name = getattr(backend, "name", backend.__class__.__name__)
        for attempt in range(1, 3):
            try:
                response: ToolResponse = await asyncio.wait_for(backend(**kwargs), timeout=20.0)
                if not response.success or not response.extra:
                    self._last_attempts.append({
                        "provider": provider_name, "attempt": attempt, "status": "failed",
                        "reason": self._safe_error(response.message), "retryable": attempt < 2,
                    })
                    if attempt < 2:
                        await asyncio.sleep(0.25 * (2 ** (attempt - 1)))
                    continue
                search_items = response.extra.data.get("search_items", []) if response.extra.data else []
                results: List[dict] = []
                for item in search_items:
                    url = item.url if hasattr(item, "url") else item.get("url", "")
                    title = item.title if hasattr(item, "title") else item.get("title", "")
                    snippet = (item.description if hasattr(item, "description") else item.get("description", "")) or ""
                    if url:
                        results.append({"url": url, "title": title, "snippet": snippet})
                self._last_attempts.append({
                    "provider": provider_name, "attempt": attempt,
                    "status": "success" if results else "empty", "result_count": len(results),
                    "retryable": False,
                })
                return results
            except asyncio.TimeoutError:
                reason = "timeout"
            except Exception as exc:
                reason = self._safe_error(exc)
            self._last_attempts.append({
                "provider": provider_name, "attempt": attempt, "status": "failed",
                "reason": reason, "retryable": attempt < 2,
            })
            if attempt < 2:
                await asyncio.sleep(0.25 * (2 ** (attempt - 1)))
        return []
