"""
title: Web Researcher
author: airpods
author_url: https://github.com/radicazz/airpods
version: 0.1.0
description: Automatically searches the web and injects context when queries need current information.
"""

from pydantic import BaseModel, Field
from typing import Optional
import re
import requests
from datetime import datetime


class Filter:
    class Valves(BaseModel):
        priority: int = Field(
            default=0, description="Priority level for the filter operations."
        )
        searxng_instance: str = Field(
            default="https://search.brave.com/api/search",
            description="Search API endpoint (SearXNG or similar).",
        )
        trigger_patterns: list[str] = Field(
            default=[
                r"what (is|are) the latest",
                r"current (news|events|price|status)",
                r"recent (developments|updates)",
                r"search (for|the web)",
                r"find information about",
                r"look up",
            ],
            description="Regex patterns that trigger web search.",
        )
        max_results: int = Field(
            default=5, description="Maximum number of search results to include."
        )
        auto_search: bool = Field(
            default=True, description="Automatically search when patterns detected."
        )
        include_snippets: bool = Field(
            default=True, description="Include result snippets in context."
        )
        search_timeout: int = Field(
            default=10, description="Request timeout in seconds."
        )

    def __init__(self):
        self.valves = self.Valves()

    def _should_search(self, content: str) -> bool:
        """Check if message requires web search."""
        content_lower = content.lower()
        return any(
            re.search(pattern, content_lower)
            for pattern in self.valves.trigger_patterns
        )

    def _extract_query(self, content: str) -> str:
        """Extract search query from user message."""
        # Remove common filler words and extract the core query
        query = re.sub(
            r"(please|can you|could you|search for|look up|find|tell me about)",
            "",
            content,
            flags=re.IGNORECASE,
        ).strip()
        return query[:200]  # Limit query length

    def _search_web(self, query: str) -> list[dict]:
        """Perform web search using SearXNG or similar."""
        try:
            # This is a simplified example - you'd need to configure your own search API
            # Using DuckDuckGo HTML scraping as fallback (not ideal for production)
            url = "https://html.duckduckgo.com/html/"
            params = {"q": query}
            headers = {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
            }

            response = requests.post(
                url, data=params, headers=headers, timeout=self.valves.search_timeout
            )
            response.raise_for_status()

            results = []
            html = response.text

            # Parse results (simplified - would need better parsing)
            title_pattern = r'<a class="result__a"[^>]*>(.*?)</a>'
            snippet_pattern = r'<a class="result__snippet"[^>]*>(.*?)</a>'

            titles = re.findall(title_pattern, html)
            snippets = re.findall(snippet_pattern, html)

            for i, (title, snippet) in enumerate(
                zip(titles[: self.valves.max_results], snippets)
            ):
                title_clean = re.sub(r"<[^>]+>", "", title).strip()
                snippet_clean = re.sub(r"<[^>]+>", "", snippet).strip()

                if title_clean and snippet_clean:
                    results.append({"title": title_clean, "snippet": snippet_clean})

            return results
        except Exception as e:
            print(f"Web search error: {e}")
            return []

    def _format_search_results(self, results: list[dict], query: str) -> str:
        """Format search results into context."""
        if not results:
            return f"No web results found for: {query}"

        formatted = f"🔍 **Web Search Results for '{query}':**\n"
        formatted += (
            f"(Retrieved: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')})\n\n"
        )

        for i, result in enumerate(results, 1):
            formatted += f"{i}. **{result['title']}**\n"
            if self.valves.include_snippets:
                formatted += f"   {result['snippet']}\n\n"

        return formatted

    def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        if not self.valves.auto_search:
            return body

        messages = body.get("messages", [])
        last_user_msg = None

        for message in reversed(messages):
            if message.get("role") == "user":
                last_user_msg = message
                break

        if not last_user_msg:
            return body

        content = last_user_msg.get("content", "")

        if not self._should_search(content):
            return body

        query = self._extract_query(content)
        results = self._search_web(query)

        if results:
            search_context = self._format_search_results(results, query)
            context_msg = f"\n\n{search_context}\n\nUse the above search results to provide an accurate, up-to-date answer."

            system_msg = next((m for m in messages if m.get("role") == "system"), None)
            if system_msg:
                system_msg["content"] += context_msg
            else:
                messages.insert(0, {"role": "system", "content": context_msg})

            body["messages"] = messages

        return body
