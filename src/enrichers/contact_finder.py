"""Find decision-maker contact info via web search."""

from config.settings import settings
from src.models.lead import DiscoveredContact, RawLead
from src.search import SearchClient
from src.utils.logger import get_logger

logger = get_logger("contact_finder")


class ContactDiscovery:
    """Find owner/manager contact details using web search."""

    def __init__(self):
        """Initialize contact discovery."""
        self.search_client = SearchClient()

    async def find_contacts(
        self,
        lead: RawLead,
        existing_owner: str | None = None,
    ) -> list[DiscoveredContact]:
        """Search for decision-maker contacts.

        Args:
            lead: Raw lead data.
            existing_owner: Owner name if already known from website.

        Returns:
            List of discovered contacts.
        """
        if not settings.enable_contact_discovery:
            return []

        contacts = []
        company_name = lead.name

        # Search patterns for decision makers
        search_queries = [
            f"{company_name} owner founder",
            f"{company_name} CEO director manager",
        ]

        # If we have an owner name, search for their specific info
        if existing_owner:
            search_queries.insert(0, f"{existing_owner} {company_name}")

        for query in search_queries[:2]:  # Limit to 2 searches
            try:
                person_info = await self.search_client.search_person(
                    name=query.split()[0] if existing_owner else "",
                    company=company_name,
                )

                if person_info.linkedin_url or person_info.email:
                    contact = DiscoveredContact(
                        name=person_info.name,
                        role=person_info.role,
                        email=person_info.email,
                        linkedin_url=person_info.linkedin_url,
                        source="web_search",
                    )

                    # Avoid duplicates
                    if not any(c.name == contact.name for c in contacts):
                        contacts.append(contact)

                    logger.debug(
                        "contact_discovered",
                        company=company_name,
                        name=contact.name,
                        role=contact.role,
                        has_linkedin=bool(contact.linkedin_url),
                    )

            except Exception as e:
                logger.warning(
                    "contact_search_failed",
                    company=company_name,
                    query=query,
                    error=str(e),
                )

        return contacts
