"""This module provides example tools for web scraping and search functionality.

It includes a basic Tavily search function (as an example)

These tools are intended as free examples to get started. For production use,
consider implementing more robust and specialized tools tailored to your needs.
"""

from typing import Any, Callable, List, cast

from langchain_tavily import TavilySearch
from langgraph.runtime import get_runtime

from react_agent.context import Context


async def search(query: str) -> dict[str, Any] | None:
    """Search for general web results.

    This function performs a search using the Tavily search engine, which is designed
    to provide comprehensive, accurate, and trusted results. It's particularly useful
    for answering questions about current events.
    """
    runtime = get_runtime(Context)
    # Enforce the switch even if a model emits a tool call without tool binding.
    if not runtime.context.search_enabled:
        return {"blocked": True, "error": "本条消息已关闭联网搜索，未请求外部搜索服务。"}
    wrapped = TavilySearch(max_results=runtime.context.max_search_results)
    result = cast(dict[str, Any], await wrapped.ainvoke({"query": query}))
    # Tavily may return an exception object as data instead of raising it.
    if isinstance(result, dict) and result.get("error"):
        return {"status": "error", "error": str(result["error"])[:500], "results": []}
    return result


TOOLS: List[Callable[..., Any]] = [search]
