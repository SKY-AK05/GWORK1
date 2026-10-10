"""LangChain-compatible web page fetcher tool.

Wraps the existing `fetch_url` utility (Firecrawl → Crawl4AI fallback)
behind a standard BaseTool interface. Graph nodes call this via `ainvoke`.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from src.utils.url_utils import fetch_url


class WebFetchInput(BaseModel):
    url: str = Field(description="The URL of the webpage to fetch")


class WebFetchTool(BaseTool):
    """Fetch a webpage and return its markdown content.

    Returns a dict with keys: url, title, content, success.
    """

    name: str = "web_fetch"
    description: str = (
        "Fetch a single webpage and return its title and markdown content. "
        "Returns a dict with url, title, content, and success keys."
    )
    args_schema: Type[BaseModel] = WebFetchInput

    def _run(self, url: str) -> dict:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(self._arun(url=url))

    async def _arun(self, url: str) -> dict:
        try:
            result = await fetch_url(url)
            if result is None:
                return {
                    "url": url,
                    "title": "",
                    "content": "",
                    "success": False,
                    "error_type": "backend_or_blocked",
                }
            return {
                "url": url,
                "title": result.title or f"Fetched from {url}",
                "content": result.markdown or "",
                "success": True,
            }
        except Exception as exc:
            error_text = str(exc)
            if isinstance(exc, asyncio.TimeoutError) or "timeout" in error_text.lower():
                error_type = "timeout"
            elif re.search(r"\b(401|403|429)\b", error_text):
                error_type = "access_or_rate_limited"
            else:
                error_type = "exception"
            return {
                "url": url,
                "title": "",
                "content": "",
                "success": False,
                "error": error_text[:300],
                "error_type": error_type,
            }
