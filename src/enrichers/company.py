"""Company intelligence enrichment via web search."""

from datetime import datetime

from config.settings import settings
from src.models.lead import CompanyIntelligence, RawLead
from src.search import SearchClient
from src.utils.logger import get_logger

logger = get_logger("company_enricher")


class CompanyEnricher:
    """Enrich leads with company intelligence from web search."""

    def __init__(self):
        """Initialize company enricher."""
        self.search_client = SearchClient()

    async def enrich(self, lead: RawLead) -> CompanyIntelligence:
        """Search for and extract company intelligence.

        Args:
            lead: Raw lead data.

        Returns:
            CompanyIntelligence with extracted data.
        """
        if not settings.enable_company_enrichment:
            return CompanyIntelligence()

        company_name = lead.name
        location = self._extract_location(lead.address)

        intel = CompanyIntelligence(enriched_at=datetime.utcnow())

        try:
            # Search for company info
            company_info = await self.search_client.search_company(
                company_name=company_name,
                location=location,
            )

            intel.employee_count = company_info.employee_count
            intel.founded_year = company_info.founded_year
            intel.company_description = company_info.description
            intel.industry = company_info.industry
            intel.source_urls = company_info.source_urls or []

            logger.debug(
                "company_intel_extracted",
                company=company_name,
                employees=intel.employee_count,
                founded=intel.founded_year,
            )

        except Exception as e:
            logger.warning(
                "company_search_failed",
                company=company_name,
                error=str(e),
            )

        # Search for recent news
        try:
            news = await self.search_client.search_news(
                company_name=company_name,
                max_results=3,
            )
            intel.recent_news = news

        except Exception as e:
            logger.warning(
                "news_search_failed",
                company=company_name,
                error=str(e),
            )

        return intel

    def _extract_location(self, address: str | None) -> str | None:
        """Extract city/region from full address.

        Args:
            address: Full address string.

        Returns:
            City or region name.
        """
        if not address:
            return None

        # Split by comma and get relevant parts
        parts = [p.strip() for p in address.split(",")]

        # Usually city is 2nd or 3rd from end
        if len(parts) >= 2:
            # Return city (usually before country)
            return parts[-2] if len(parts) >= 2 else parts[0]

        return None
