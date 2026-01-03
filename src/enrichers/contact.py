"""Contact/owner name extraction from website content."""

import re

from src.utils.logger import get_logger

logger = get_logger("contact_extractor")


class ContactExtractor:
    """Extract owner/contact names from website content."""

    # Role indicators that suggest ownership
    OWNER_ROLES = {
        "owner",
        "founder",
        "co-founder",
        "ceo",
        "chief executive",
        "president",
        "director",
        "principal",
        "proprietor",
        "managing director",
    }

    # Role indicators for any contact
    CONTACT_ROLES = OWNER_ROLES | {
        "manager",
        "general manager",
        "head",
        "lead",
        "partner",
        "chef",  # For restaurants
        "chef patron",
    }

    # Patterns to find names near roles
    NAME_PATTERNS = [
        # "John Smith, Owner"
        r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s*[,\-–—]\s*(?:' + '|'.join(CONTACT_ROLES) + ')',
        # "Owner: John Smith"
        r'(?:' + '|'.join(CONTACT_ROLES) + r')\s*[:\-–—]\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)',
        # "Meet John Smith, our Owner"
        r'(?:meet|about)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)',
    ]

    def extract(self, website_data: dict) -> list[dict]:
        """Extract contact names from website data.

        Args:
            website_data: Dictionary from WebsiteScraper.

        Returns:
            List of dictionaries with name and role.
        """
        contacts = []
        seen_names = set()

        # Prioritize about/team pages
        pages = website_data.get("contact_pages", [])
        if website_data.get("homepage"):
            pages.append(website_data["homepage"])

        # Sort pages to prioritize about/team pages
        pages = sorted(
            pages,
            key=lambda p: self._page_priority(p.get("url", "")),
            reverse=True,
        )

        for page in pages:
            text = page.get("text", "")
            soup = page.get("soup")

            # Method 1: Pattern matching
            for pattern in self.NAME_PATTERNS:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    name = match.group(1).strip()
                    if self._is_valid_name(name) and name not in seen_names:
                        seen_names.add(name)
                        role = self._extract_role(match.group(0))
                        contacts.append({"name": name, "role": role})

            # Method 2: Look for structured data (schema.org)
            if soup:
                schema_contacts = self._extract_from_schema(soup)
                for contact in schema_contacts:
                    if contact["name"] not in seen_names:
                        seen_names.add(contact["name"])
                        contacts.append(contact)

        # Prioritize owners
        contacts.sort(
            key=lambda c: (
                1 if c.get("role", "").lower() in self.OWNER_ROLES else 0
            ),
            reverse=True,
        )

        return contacts

    def _page_priority(self, url: str | None) -> int:
        """Get priority score for a page based on URL."""
        if not url:
            return 0
        url_lower = url.lower()
        if "team" in url_lower or "people" in url_lower:
            return 3
        if "about" in url_lower:
            return 2
        if "contact" in url_lower:
            return 1
        return 0

    def _is_valid_name(self, name: str) -> bool:
        """Check if extracted text is a valid name."""
        if not name:
            return False

        # Must have at least two parts (first and last name)
        parts = name.split()
        if len(parts) < 2:
            return False

        # Must not be too long (likely a sentence)
        if len(parts) > 4:
            return False

        # Each part should be title case
        for part in parts:
            if not part[0].isupper():
                return False

        # Exclude common false positives
        false_positives = {
            "read more",
            "learn more",
            "contact us",
            "about us",
            "our team",
            "meet the team",
            "terms of service",
            "privacy policy",
        }
        if name.lower() in false_positives:
            return False

        return True

    def _extract_role(self, match_text: str) -> str | None:
        """Extract role from matched text."""
        match_lower = match_text.lower()
        for role in self.CONTACT_ROLES:
            if role in match_lower:
                return role.title()
        return None

    def _extract_from_schema(self, soup) -> list[dict]:
        """Extract contacts from schema.org structured data."""
        contacts = []

        # Look for JSON-LD
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                import json
                data = json.loads(script.string)
                contacts.extend(self._parse_schema_data(data))
            except (json.JSONDecodeError, AttributeError):
                continue

        return contacts

    def _parse_schema_data(self, data: dict | list) -> list[dict]:
        """Parse schema.org data for person information."""
        contacts = []

        if isinstance(data, list):
            for item in data:
                contacts.extend(self._parse_schema_data(item))
        elif isinstance(data, dict):
            schema_type = data.get("@type", "")

            if schema_type == "Person":
                name = data.get("name")
                if name and self._is_valid_name(name):
                    contacts.append({
                        "name": name,
                        "role": data.get("jobTitle"),
                    })

            # Check for nested person data
            for key, value in data.items():
                if isinstance(value, (dict, list)):
                    contacts.extend(self._parse_schema_data(value))

        return contacts

    def get_owner_name(self, contacts: list[dict]) -> str | None:
        """Get the most likely owner name from contacts.

        Args:
            contacts: List of contact dictionaries.

        Returns:
            Owner name or None.
        """
        if not contacts:
            return None

        # First, look for explicit owner/founder
        for contact in contacts:
            role = (contact.get("role") or "").lower()
            if role in self.OWNER_ROLES:
                return contact["name"]

        # Fall back to first contact
        return contacts[0]["name"] if contacts else None
