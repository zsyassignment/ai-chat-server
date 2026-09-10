"""Tavily-backed web search used as an Agent tool."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from app.core.config import Settings


@dataclass
class WebSearchResult:
    results: List[Dict[str, Any]] = field(default_factory=list)
    answer: str = ""
    error: str = ""


class TavilyWebSearch:
    """Thin, replaceable adapter around Tavily's hosted Search API."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: Any = None

    @property
    def enabled(self) -> bool:
        return bool(self.settings.tavily_api_key)

    def status(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "provider": "tavily",
            "max_results": self.settings.web_search_max_results,
        }

    def search(self, query: str, max_results: int | None = None) -> WebSearchResult:
        if not self.enabled:
            return WebSearchResult(error="TAVILY_API_KEY is not configured")
        try:
            client = self._load_client()
            payload = client.search(
                query=query,
                search_depth="advanced",
                topic="general",
                max_results=max_results or self.settings.web_search_max_results,
                include_answer="basic",
                include_raw_content=False,
            )
            results = []
            for item in payload.get("results", []):
                url = str(item.get("url", "")).strip()
                if not url:
                    continue
                results.append({
                    "title": str(item.get("title", "Untitled")),
                    "url": url,
                    "content": str(item.get("content", ""))[:2000],
                    "score": float(item.get("score", 0.0) or 0.0),
                    "source": "tavily",
                })
            return WebSearchResult(results=results, answer=str(payload.get("answer", "") or ""))
        except Exception as exc:
            return WebSearchResult(error=str(exc))

    def _load_client(self):
        if self._client is None:
            from tavily import TavilyClient

            self._client = TavilyClient(api_key=self.settings.tavily_api_key)
        return self._client
