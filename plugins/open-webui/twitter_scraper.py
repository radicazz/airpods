"""
title: Twitter/X Scraper
author: airpods
author_url: https://github.com/radicazz/airpods
version: 0.1.0
description: Scrapes Twitter/X tweets based on user queries and injects results into conversation.
"""

from pydantic import BaseModel, Field
from typing import Optional
import re
import requests


class Filter:
    class Valves(BaseModel):
        priority: int = Field(
            default=0, description="Priority level for the filter operations."
        )
        nitter_instance: str = Field(
            default="https://nitter.net",
            description="Nitter instance URL for scraping (privacy-friendly Twitter frontend).",
        )
        trigger_keywords: list[str] = Field(
            default=["twitter", "tweet", "tweets", "x.com", "@"],
            description="Keywords that trigger Twitter scraping.",
        )
        max_tweets: int = Field(
            default=10, description="Maximum number of tweets to fetch."
        )
        auto_scrape: bool = Field(
            default=True, description="Automatically scrape when keywords detected."
        )
        include_replies: bool = Field(
            default=False, description="Include reply tweets in results."
        )
        scrape_timeout: int = Field(
            default=10, description="Request timeout in seconds."
        )

    def __init__(self):
        self.valves = self.Valves()

    def _should_scrape_twitter(self, content: str) -> bool:
        """Check if message contains Twitter-related keywords."""
        content_lower = content.lower()
        return any(keyword in content_lower for keyword in self.valves.trigger_keywords)

    def _extract_twitter_username(self, content: str) -> Optional[str]:
        """Extract Twitter username from message."""
        patterns = [
            r"@(\w+)",
            r"twitter\.com/(\w+)",
            r"x\.com/(\w+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, content)
            if match:
                return match.group(1)
        return None

    def _extract_search_query(self, content: str) -> Optional[str]:
        """Extract search query from message."""
        patterns = [
            r'tweets about ["\']?([^"\']+)["\']?',
            r'search twitter for ["\']?([^"\']+)["\']?',
            r'find tweets ["\']?([^"\']+)["\']?',
        ]
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    def _scrape_user_tweets(self, username: str) -> list[dict]:
        """Scrape tweets from a user via Nitter."""
        try:
            url = f"{self.valves.nitter_instance}/{username}"
            response = requests.get(url, timeout=self.valves.scrape_timeout)
            response.raise_for_status()

            tweets = []
            html = response.text

            # Simple regex parsing (not robust, but works for demo)
            tweet_pattern = r'<div class="tweet-content[^"]*"[^>]*>(.*?)</div>'
            date_pattern = r'<span class="tweet-date"[^>]*>(.*?)</span>'

            tweet_matches = re.findall(tweet_pattern, html, re.DOTALL)
            date_matches = re.findall(date_pattern, html, re.DOTALL)

            for i, (tweet_html, date) in enumerate(
                zip(tweet_matches[: self.valves.max_tweets], date_matches)
            ):
                # Strip HTML tags
                tweet_text = re.sub(r"<[^>]+>", "", tweet_html).strip()
                if tweet_text:
                    tweets.append(
                        {"username": username, "text": tweet_text, "date": date.strip()}
                    )

            return tweets
        except Exception as e:
            print(f"Twitter scraping error: {e}")
            return []

    def _search_tweets(self, query: str) -> list[dict]:
        """Search tweets via Nitter."""
        try:
            url = f"{self.valves.nitter_instance}/search"
            params = {"q": query}
            response = requests.get(
                url, params=params, timeout=self.valves.scrape_timeout
            )
            response.raise_for_status()

            # Similar parsing logic as user tweets
            tweets = []
            # Simplified for demo - would need better parsing
            return tweets
        except Exception as e:
            print(f"Twitter search error: {e}")
            return []

    def _format_tweets(self, tweets: list[dict]) -> str:
        """Format tweets into readable text."""
        if not tweets:
            return "No tweets found."

        formatted = "📱 **Twitter Feed:**\n\n"
        for i, tweet in enumerate(tweets, 1):
            formatted += (
                f"{i}. @{tweet['username']} ({tweet.get('date', 'unknown date')})\n"
            )
            formatted += f"   {tweet['text']}\n\n"
        return formatted

    def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        if not self.valves.auto_scrape:
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

        if not self._should_scrape_twitter(content):
            return body

        tweets = []
        username = self._extract_twitter_username(content)
        search_query = self._extract_search_query(content)

        if username:
            tweets = self._scrape_user_tweets(username)
        elif search_query:
            tweets = self._search_tweets(search_query)

        if tweets:
            tweet_data = self._format_tweets(tweets)
            system_context = f"\n\n{tweet_data}\n\nUse this Twitter data to answer the user's question."

            system_msg = next((m for m in messages if m.get("role") == "system"), None)
            if system_msg:
                system_msg["content"] += system_context
            else:
                messages.insert(0, {"role": "system", "content": system_context})

            body["messages"] = messages

        return body
