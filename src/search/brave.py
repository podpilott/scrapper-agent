"""Brave Search API integration.

Brave Search is a privacy-focused search engine with a generous free tier.

API Docs: https://api.search.brave.com/app/documentation/web-search
"""

import httpx

from config.settings import settings
from src.utils.logger import get_logger

logger = get_logger("brave")


class BraveSearch:
    """Brave Search API client with multi-key fallback support."""

    BASE_URL = "https://api.search.brave.com/res/v1/web/search"
    # Error codes that trigger key rotation
    ROTATABLE_STATUS_CODES = (401, 402, 429, 500, 502, 503)

    def __init__(self):
        """Initialize Brave Search client."""
        self.api_keys = settings.get_brave_keys()
        if not self.api_keys:
            raise ValueError("BRAVE_API_KEY is required")
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
                "rotating_brave_key",
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
        count: int = 5,
        country: str = "us",
        search_lang: str = "en",
        freshness: str | None = None,
    ) -> dict:
        """Execute a Brave search with automatic key rotation on failure.

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

        attempts = 0
        max_attempts = len(self.api_keys)
        last_error = None

        while attempts < max_attempts:
            headers = {
                "Accept": "application/json",
                "X-Subscription-Token": self._get_current_key(),
            }
            attempts += 1

            async with httpx.AsyncClient(timeout=30.0) as client:
                try:
                    response = await client.get(
                        self.BASE_URL,
                        params=params,
                        headers=headers,
                    )

                    # Check for rotatable errors before raising
                    if response.status_code >= 400:
                        if self._should_rotate(response.status_code):
                            logger.warning(
                                "brave_key_error",
                                status=response.status_code,
                                key_index=self.current_key_index,
                            )
                            if self._rotate_key():
                                continue
                        # No more keys or non-rotatable error
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
                    last_error = e
                    status = getattr(getattr(e, 'response', None), 'status_code', 500)
                    logger.warning(
                        "brave_request_error",
                        error=str(e),
                        status=status,
                        key_index=self.current_key_index,
                    )
                    if self._should_rotate(status) and self._rotate_key():
                        continue
                    raise

        logger.error("all_brave_keys_exhausted", total_keys=len(self.api_keys))
        if last_error:
            raise last_error
        raise RuntimeError("All Brave API keys exhausted")

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
