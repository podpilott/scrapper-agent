"""Email extraction from website content."""

import re
from dataclasses import dataclass

from src.utils.logger import get_logger

logger = get_logger("email_extractor")


@dataclass
class ExtractedEmail:
    """Extracted email with metadata."""

    email: str
    source: str  # "mailto", "text", "pattern"
    confidence: float  # 0.0 - 1.0
    is_generic: bool  # info@, contact@, etc.


class EmailExtractor:
    """Extract and validate email addresses from website content."""

    # Common generic email prefixes
    GENERIC_PREFIXES = {
        "info",
        "contact",
        "hello",
        "hi",
        "support",
        "help",
        "sales",
        "admin",
        "office",
        "mail",
        "enquiries",
        "inquiries",
        "general",
        "team",
    }

    # Email regex pattern
    EMAIL_PATTERN = re.compile(
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    )

    # Patterns to exclude (common false positives)
    EXCLUDE_PATTERNS = {
        r'example\.com$',
        r'test\.com$',
        r'domain\.com$',
        r'email\.com$',
        r'yourwebsite\.com$',
        r'@sentry',
        r'@wix',
        r'@wordpress',
        r'@squarespace',
        r'\.png$',
        r'\.jpg$',
        r'\.gif$',
        r'\.svg$',
    }

    def extract(self, website_data: dict) -> list[ExtractedEmail]:
        """Extract emails from website data.

        Args:
            website_data: Dictionary from WebsiteScraper.

        Returns:
            List of ExtractedEmail objects, sorted by confidence.
        """
        emails = []
        seen = set()

        # Extract from homepage
        homepage = website_data.get("homepage")
        if homepage:
            emails.extend(self._extract_from_page(homepage, seen))

        # Extract from contact pages
        for page in website_data.get("contact_pages", []):
            emails.extend(self._extract_from_page(page, seen))

        # Sort by confidence (highest first)
        emails.sort(key=lambda e: e.confidence, reverse=True)

        return emails

    def _extract_from_page(
        self,
        page_data: dict,
        seen: set,
    ) -> list[ExtractedEmail]:
        """Extract emails from a single page."""
        emails = []
        html = page_data.get("html", "")
        soup = page_data.get("soup")
        source_url = page_data.get("url", "")

        # 1. Extract from mailto links (highest confidence)
        if soup:
            for link in soup.find_all("a", href=True):
                href = link.get("href", "")
                if href.startswith("mailto:"):
                    email = href.replace("mailto:", "").split("?")[0].strip().lower()
                    if self._is_valid_email(email) and email not in seen:
                        seen.add(email)
                        emails.append(
                            ExtractedEmail(
                                email=email,
                                source="mailto",
                                confidence=0.95,
                                is_generic=self._is_generic(email),
                            )
                        )

        # 2. Extract from text content
        text = page_data.get("text", "")
        for match in self.EMAIL_PATTERN.finditer(text):
            email = match.group().lower()
            if self._is_valid_email(email) and email not in seen:
                seen.add(email)
                # Lower confidence for text extraction
                confidence = 0.7 if "contact" in source_url.lower() else 0.5
                emails.append(
                    ExtractedEmail(
                        email=email,
                        source="text",
                        confidence=confidence,
                        is_generic=self._is_generic(email),
                    )
                )

        # 3. Extract from HTML (includes obfuscated emails)
        for match in self.EMAIL_PATTERN.finditer(html):
            email = match.group().lower()
            if self._is_valid_email(email) and email not in seen:
                seen.add(email)
                emails.append(
                    ExtractedEmail(
                        email=email,
                        source="html",
                        confidence=0.4,
                        is_generic=self._is_generic(email),
                    )
                )

        return emails

    def _is_valid_email(self, email: str) -> bool:
        """Check if email is valid and not a false positive."""
        if not email or "@" not in email:
            return False

        # Check against exclude patterns
        for pattern in self.EXCLUDE_PATTERNS:
            if re.search(pattern, email, re.IGNORECASE):
                return False

        # Basic format validation
        parts = email.split("@")
        if len(parts) != 2:
            return False

        local, domain = parts
        if not local or not domain or "." not in domain:
            return False

        return True

    def _is_generic(self, email: str) -> bool:
        """Check if email uses a generic prefix."""
        local = email.split("@")[0].lower()
        return local in self.GENERIC_PREFIXES

    def get_best_email(self, emails: list[ExtractedEmail]) -> str | None:
        """Get the best email from a list.

        Prioritizes:
        1. Personal emails (non-generic) with high confidence
        2. Generic emails with high confidence
        3. Any email with highest confidence

        Args:
            emails: List of ExtractedEmail objects.

        Returns:
            Best email address or None.
        """
        if not emails:
            return None

        # First, try to find a personal (non-generic) email
        personal = [e for e in emails if not e.is_generic and e.confidence >= 0.5]
        if personal:
            return personal[0].email

        # Fall back to any email
        return emails[0].email
