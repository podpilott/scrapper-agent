"""Tavily Search API integration.

Tavily is an AI-optimized search engine that returns structured,
relevant results ideal for LLM applications.

API Docs: https://docs.tavily.com/
"""

import httpx

from config.settings import settings
from src.utils.logger import get_logger

logger = get_logger("tavily")


class TavilySearch:
    """Tavily Search API client."""

    BASE_URL = "https://api.tavily.com/search"

    def __init__(self):
        """Initialize Tavily client."""
        if not settings.tavily_api_key:
            raise ValueError("TAVILY_API_KEY is required")
        self.api_key = settings.tavily_api_key.get_secret_value()

    async def search(
        self,
        query: str,
        search_depth: str = "basic",
        max_results: int = 5,
        include_answer: bool = True,
        include_raw_content: bool = False,
    ) -> dict:
        """Execute a Tavily search.

        Args:
            query: Search query string.
            search_depth: "basic" (faster) or "advanced" (more thorough).
            max_results: Maximum number of results to return.
            include_answer: Include AI-generated answer summary.
            include_raw_content: Include raw HTML content of pages.

        Returns:
            Dictionary with search results:
            {
                "query": str,
                "answer": str,  # AI summary if include_answer=True
                "results": [
                    {
                        "title": str,
                        "url": str,
                        "content": str,  # Extracted text
                        "score": float,  # Relevance score
                    }
                ]
            }
        """
        payload = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": search_depth,
            "max_results": max_results,
            "include_answer": include_answer,
            "include_raw_content": include_raw_content,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(self.BASE_URL, json=payload)
                response.raise_for_status()
                data = response.json()

                logger.debug(
                    "tavily_search_complete",
                    query=query,
                    results_count=len(data.get("results", [])),
                )

                return data

            except httpx.HTTPError as e:
                logger.error("tavily_search_failed", query=query, error=str(e))
                raise

    async def search_company(self, company_name: str, location: str | None = None) -> dict:
        """Search for company information.

        Args:
            company_name: Name of the company.
            location: Optional location to narrow search.

        Returns:
            Search results focused on company info.
        """
        query = f"{company_name} company information"
        if location:
            query += f" {location}"

        return await self.search(
            query=query,
            search_depth="advanced",
            max_results=5,
            include_answer=True,
        )

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
        query += " LinkedIn contact"

        return await self.search(
            query=query,
            search_depth="basic",
            max_results=5,
            include_answer=False,
        )

    async def search_news(self, company_name: str, days: int = 30) -> dict:
        """Search for recent news about a company.

        Args:
            company_name: Name of the company.
            days: How recent the news should be.

        Returns:
            Search results with recent news.
        """
        query = f"{company_name} news latest updates"

        return await self.search(
            query=query,
            search_depth="basic",
            max_results=5,
            include_answer=True,
        )
