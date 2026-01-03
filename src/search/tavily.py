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
    """Tavily Search API client with multi-key fallback support."""

    BASE_URL = "https://api.tavily.com/search"
    # Error codes that trigger key rotation
    ROTATABLE_STATUS_CODES = (401, 402, 429, 500, 502, 503)

    def __init__(self):
        """Initialize Tavily client."""
        self.api_keys = settings.get_tavily_keys()
        if not self.api_keys:
            raise ValueError("TAVILY_API_KEY is required")
        self.current_key_index = 0

    def _get_current_key(self) -> str:
        """Get the current API key."""
        return self.api_keys[self.current_key_index]

    def _rotate_key(self) -> bool:
        """Try to rotate to the next API key.

        Returns:
            True if rotated to a new key, False if no more keys available.
        """
        if self.current_key_index < len(self.api_keys) - 1:
            self.current_key_index += 1
            logger.warning(
                "rotating_tavily_key",
                new_index=self.current_key_index,
                total_keys=len(self.api_keys),
            )
            return True
        return False

    def _should_rotate(self, status_code: int) -> bool:
        """Check if the error status code should trigger key rotation."""
        return status_code in self.ROTATABLE_STATUS_CODES

    async def search(
        self,
        query: str,
        search_depth: str = "basic",
        max_results: int = 5,
        include_answer: bool = True,
        include_raw_content: bool = False,
    ) -> dict:
        """Execute a Tavily search with automatic key rotation on failure.

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
        attempts = 0
        max_attempts = len(self.api_keys)
        last_error = None

        while attempts < max_attempts:
            payload = {
                "api_key": self._get_current_key(),
                "query": query,
                "search_depth": search_depth,
                "max_results": max_results,
                "include_answer": include_answer,
                "include_raw_content": include_raw_content,
            }
            attempts += 1

            async with httpx.AsyncClient(timeout=30.0) as client:
                try:
                    response = await client.post(self.BASE_URL, json=payload)

                    # Check for rotatable errors before raising
                    if response.status_code >= 400:
                        if self._should_rotate(response.status_code):
                            logger.warning(
                                "tavily_key_error",
                                status=response.status_code,
                                key_index=self.current_key_index,
                            )
                            if self._rotate_key():
                                continue
                        # No more keys or non-rotatable error
                        response.raise_for_status()

                    data = response.json()

                    logger.debug(
                        "tavily_search_complete",
                        query=query,
                        results_count=len(data.get("results", [])),
                    )

                    return data

                except httpx.HTTPError as e:
                    last_error = e
                    status = getattr(getattr(e, 'response', None), 'status_code', 500)
                    logger.warning(
                        "tavily_request_error",
                        error=str(e),
                        status=status,
                        key_index=self.current_key_index,
                    )
                    if self._should_rotate(status) and self._rotate_key():
                        continue
                    raise

        logger.error("all_tavily_keys_exhausted", total_keys=len(self.api_keys))
        if last_error:
            raise last_error
        raise RuntimeError("All Tavily API keys exhausted")

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
