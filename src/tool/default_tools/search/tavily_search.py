from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from pydantic import Field

try:
    from tavily import AsyncTavilyClient
except ImportError:
    AsyncTavilyClient = None

from src.tool.default_tools.search.types import SearchItem
from src.tool.types import Tool, ToolResponse, ToolExtra
from src.logger import logger
from src.registry import TOOL


@TOOL.register_module(force=True)
class TavilySearch(Tool):
    """Search backend using the Tavily Search API."""

    name: str = "tavily_search"
    description: str = (
        "a search engine using Tavily. "
        "useful for when you need to answer questions about current events. "
        "input should be a search query."
    )
    metadata: Dict[str, Any] = Field(default={}, description="The metadata of the tool")
    api_key: Optional[str] = Field(default=None, description="Tavily API key")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.api_key = os.getenv("TAVILY_API_KEY")

    async def _perform_search(
        self,
        query: str,
        num_results: int = 5,
        **kwargs,
    ) -> List[SearchItem]:
        if AsyncTavilyClient is None:
            raise ImportError("tavily-python is required: pip install tavily-python")
        if not self.api_key:
            raise ValueError("TAVILY_API_KEY environment variable is not set")

        client = AsyncTavilyClient(api_key=self.api_key)
        response = await client.search(
            query=query,
            max_results=num_results,
            include_answer=False,
            include_raw_content=False,
        )

        results: List[SearchItem] = []
        for item in response.get("results", []):
            url = item.get("url", "")
            if url:
                results.append(
                    SearchItem(
                        title=item.get("title", ""),
                        url=url,
                        description=item.get("content", "") or "",
                    )
                )
        return results

    async def __call__(
        self,
        query: str,
        num_results: Optional[int] = 5,
        lang: Optional[str] = "en",
        country: Optional[str] = "us",
        filter_year: Optional[int] = None,
        **kwargs,
    ) -> ToolResponse:
        try:
            search_items = await self._perform_search(query, num_results=num_results)

            results_json = json.dumps(
                [
                    {
                        "title": item.title,
                        "url": item.url,
                        "description": item.description or "",
                    }
                    for item in search_items
                ],
                ensure_ascii=False,
                indent=4,
            )

            return ToolResponse(
                success=True,
                message=f"Tavily search results for query: {query}\n\n{results_json}",
                extra=ToolExtra(
                    data={
                        "query": query,
                        "num_results": len(search_items),
                        "search_items": search_items,
                        "engine": "tavily",
                    }
                ),
            )

        except Exception as e:
            logger.error(f"Error in Tavily search: {e}")
            return ToolResponse(
                success=False,
                message=f"Error in Tavily search: {str(e)}",
            )
