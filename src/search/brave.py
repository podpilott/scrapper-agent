"""Brave Search API integration.

Brave Search is a privacy-focused search engine with a generous free tier.

API Docs: https://api.search.brave.com/app/documentation/web-search
"""

import httpx

from config.settings import settings
from src.utils.logger import get_logger

logger = get_logger("brave")


class BraveSearch:
    """Brave Search API client."""

    BASE_URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self):
        """Initialize Brave Search client."""
        if not settings.brave_api_key:
            raise ValueError("BRAVE_API_KEY is required")
        self.api_key = settings.brave_api_key.get_secret_value()

    async def search(
        self,
        query: str,
        count: int = 5,
        country: str = "us",
        search_lang: str = "en",
        freshness: str | None = None,
    ) -> dict:
        """Execute a Brave search.

        Args:
            query: Search query string.
            count: Number of results (max 20).
            country: Country code for results.
            search_lang: Language code for results.
            freshness: Filter by freshness ("pd" = past day, "pw" = past week,
                       "pm" = past month, "py" = past year).

        Returns:
            Dictionary with search results:
            {
                "query": str,
                "results": [
                    {
                        "title": str,
                        "url": str,
                        "description": str,
                    }
                ]
            }
        """
        params = {
            "q": query,
            "count": min(count, 20),
            "country": country,
            "search_lang": search_lang,
        }

        if freshness:
            params["freshness"] = freshness

        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": self.api_key,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(
                    self.BASE_URL,
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()

                # Normalize response format
                results = []
                web_results = data.get("web", {}).get("results", [])
                for result in web_results:
                    results.append({
                        "title": result.get("title", ""),
                        "url": result.get("url", ""),
                        "content": result.get("description", ""),
                        "score": 1.0,  # Brave doesn't provide relevance scores
                    })

                logger.debug(
                    "brave_search_complete",
                    query=query,
                    results_count=len(results),
                )

                return {
                    "query": query,
                    "results": results,
                    "answer": None,  # Brave doesn't provide AI answers
                }

            except httpx.HTTPError as e:
                logger.error("brave_search_failed", query=query, error=str(e))
                raise

    async def search_company(self, company_name: str, location: str | None = None) -> dict:
        """Search for company information.

        Args:
            company_name: Name of the company.
            location: Optional location to narrow search.

        Returns:
            Search results focused on company info.
        """
        query = f"{company_name} company about"
        if location:
            query += f" {location}"

        return await self.search(query=query, count=5)

    async def search_person(self, name: str, company: str | None = None) -> dict:
        """Search for person contact information.

        Args:
            name: Person's name.
            company: Optional company to narrow search.

        Returns:
            Search results focused on person info.
        """
        query = f"{name}"
        if company:
            query += f" {company}"
        query += " LinkedIn"

        return await self.search(query=query, count=5)

    async def search_news(self, company_name: str) -> dict:
        """Search for recent news about a company.

        Args:
            company_name: Name of the company.

        Returns:
            Search results with recent news.
        """
        query = f"{company_name} news"

        return await self.search(
            query=query,
            count=5,
            freshness="pm",  # Past month
        )
