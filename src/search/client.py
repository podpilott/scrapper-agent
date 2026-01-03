"""Unified search client supporting multiple providers.

Provides a consistent interface for web search across Tavily and Brave,
with automatic fallback and provider selection.
"""

from dataclasses import dataclass
from typing import Literal

from config.settings import settings
from src.utils.logger import get_logger

logger = get_logger("search")


@dataclass
class SearchResult:
    """Standardized search result."""

    title: str
    url: str
    content: str
    score: float = 1.0


@dataclass
class CompanyInfo:
    """Company information extracted from search."""

    name: str
    description: str | None = None
    employee_count: int | None = None
    founded_year: int | None = None
    industry: str | None = None
    recent_news: list[str] | None = None
    source_urls: list[str] | None = None


@dataclass
class PersonInfo:
    """Person contact information from search."""

    name: str
    role: str | None = None
    company: str | None = None
    linkedin_url: str | None = None
    email: str | None = None
    source_urls: list[str] | None = None


class SearchClient:
    """Unified search client with provider abstraction.

    Supports automatic fallback between providers and consistent result format.
    """

    def __init__(
        self,
        provider: Literal["tavily", "brave", "auto"] | None = None,
    ):
        """Initialize the search client.

        Args:
            provider: Search provider to use. "auto" tries Tavily first, then Brave.
        """
        self.provider = provider or settings.search_provider
        self._tavily = None
        self._brave = None

    def _get_tavily(self):
        """Lazy-load Tavily client."""
        if self._tavily is None:
            from src.search.tavily import TavilySearch
            self._tavily = TavilySearch()
        return self._tavily

    def _get_brave(self):
        """Lazy-load Brave client."""
        if self._brave is None:
            from src.search.brave import BraveSearch
            self._brave = BraveSearch()
        return self._brave

    async def search(
        self,
        query: str,
        max_results: int = 5,
    ) -> list[SearchResult]:
        """Execute a search query.

        Args:
            query: Search query string.
            max_results: Maximum results to return.

        Returns:
            List of SearchResult objects.
        """
        providers_to_try = self._get_provider_order()

        for provider_name in providers_to_try:
            try:
                if provider_name == "tavily":
                    data = await self._get_tavily().search(
                        query=query,
                        max_results=max_results,
                    )
                else:
                    data = await self._get_brave().search(
                        query=query,
                        count=max_results,
                    )

                results = [
                    SearchResult(
                        title=r.get("title", ""),
                        url=r.get("url", ""),
                        content=r.get("content", r.get("description", "")),
                        score=r.get("score", 1.0),
                    )
                    for r in data.get("results", [])
                ]

                logger.info(
                    "search_complete",
                    provider=provider_name,
                    query=query[:50],
                    results=len(results),
                )

                return results

            except Exception as e:
                logger.warning(
                    "search_provider_failed",
                    provider=provider_name,
                    error=str(e),
                )
                continue

        logger.error("all_search_providers_failed", query=query[:50])
        return []

    async def search_with_answer(
        self,
        query: str,
        max_results: int = 5,
    ) -> tuple[list[SearchResult], str | None]:
        """Execute search and get AI-generated answer (Tavily only).

        Args:
            query: Search query string.
            max_results: Maximum results to return.

        Returns:
            Tuple of (results list, answer string or None).
        """
        try:
            data = await self._get_tavily().search(
                query=query,
                max_results=max_results,
                include_answer=True,
            )

            results = [
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    content=r.get("content", ""),
                    score=r.get("score", 1.0),
                )
                for r in data.get("results", [])
            ]

            return results, data.get("answer")

        except Exception as e:
            logger.warning("search_with_answer_failed", error=str(e))
            # Fallback to regular search
            results = await self.search(query, max_results)
            return results, None

    async def search_company(
        self,
        company_name: str,
        location: str | None = None,
    ) -> CompanyInfo:
        """Search for company information.

        Args:
            company_name: Name of the company to search.
            location: Optional location to narrow results.

        Returns:
            CompanyInfo with extracted data.
        """
        query = f"{company_name} company"
        if location:
            query += f" {location}"

        results, answer = await self.search_with_answer(
            query=f"{query} about employees founded",
            max_results=5,
        )

        # Extract info from results
        company_info = CompanyInfo(
            name=company_name,
            description=answer,
            source_urls=[r.url for r in results],
        )

        # Parse employee count from content
        import re
        for result in results:
            content = result.content.lower()

            # Employee count patterns
            emp_match = re.search(r"(\d+[\d,]*)\s*(?:employees?|staff|workers)", content)
            if emp_match and not company_info.employee_count:
                try:
                    company_info.employee_count = int(emp_match.group(1).replace(",", ""))
                except ValueError:
                    pass

            # Founded year
            founded_match = re.search(r"(?:founded|established|started)\s*(?:in\s*)?(\d{4})", content)
            if founded_match and not company_info.founded_year:
                try:
                    year = int(founded_match.group(1))
                    if 1800 <= year <= 2030:
                        company_info.founded_year = year
                except ValueError:
                    pass

        return company_info

    async def search_person(
        self,
        name: str,
        company: str | None = None,
    ) -> PersonInfo:
        """Search for person contact information.

        Args:
            name: Person's name.
            company: Optional company affiliation.

        Returns:
            PersonInfo with contact details.
        """
        query = f"{name}"
        if company:
            query += f" {company}"
        query += " LinkedIn"

        results = await self.search(query=query, max_results=5)

        person_info = PersonInfo(
            name=name,
            company=company,
            source_urls=[r.url for r in results],
        )

        # Extract LinkedIn URL
        for result in results:
            if "linkedin.com/in/" in result.url:
                person_info.linkedin_url = result.url
                break

        # Try to extract role from content
        import re
        for result in results:
            content = result.content

            # Role patterns
            role_patterns = [
                r"(?:CEO|CTO|CFO|COO|CMO|Founder|Co-Founder|Owner|Director|Manager|President)",
                r"(?:Chief\s+\w+\s+Officer)",
            ]

            for pattern in role_patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match and not person_info.role:
                    person_info.role = match.group(0)
                    break

        return person_info

    async def search_news(
        self,
        company_name: str,
        max_results: int = 5,
    ) -> list[str]:
        """Search for recent news about a company.

        Args:
            company_name: Name of the company.
            max_results: Maximum news items to return.

        Returns:
            List of news headlines/summaries.
        """
        providers_to_try = self._get_provider_order()

        for provider_name in providers_to_try:
            try:
                if provider_name == "tavily":
                    data = await self._get_tavily().search_news(company_name)
                else:
                    data = await self._get_brave().search_news(company_name)

                news = []
                for result in data.get("results", [])[:max_results]:
                    title = result.get("title", "")
                    if title:
                        news.append(title)

                return news

            except Exception as e:
                logger.warning(
                    "news_search_failed",
                    provider=provider_name,
                    error=str(e),
                )
                continue

        return []

    def _get_provider_order(self) -> list[str]:
        """Get ordered list of providers to try.

        Returns:
            List of provider names in order of preference.
        """
        if self.provider == "auto":
            providers = []
            # Prefer Tavily if configured (better for AI)
            if settings.tavily_api_key:
                providers.append("tavily")
            if settings.brave_api_key:
                providers.append("brave")
            return providers
        else:
            return [self.provider]
