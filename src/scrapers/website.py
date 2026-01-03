"""Website content scraper for lead enrichment."""

import asyncio
import json
import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from src.utils.logger import get_logger
from src.utils.rate_limit import RateLimiter

logger = get_logger("website")


class WebsiteScraper:
    """Scraper for extracting content from business websites."""

    # Common pages to check for contact info (expanded)
    CONTACT_PATHS = [
        # English
        "/contact",
        "/contact-us",
        "/contactus",
        "/about",
        "/about-us",
        "/aboutus",
        "/team",
        "/our-team",
        "/people",
        "/company",
        "/leadership",
        "/founders",
        "/management",
        "/staff",
        "/our-story",
        "/company/about",
        "/company/team",
        # Indonesian
        "/hubungi-kami",
        "/kontak",
        "/tentang-kami",
        "/tentang",
        "/tim-kami",
    ]

    def __init__(self, timeout: float = 10.0, requests_per_minute: int = 20):
        """Initialize the website scraper.

        Args:
            timeout: Request timeout in seconds.
            requests_per_minute: Rate limit for requests.
        """
        self.timeout = timeout
        self.rate_limiter = RateLimiter(requests_per_minute)
        self.client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()

    async def scrape_website(self, url: str) -> dict:
        """Scrape a website and its key pages.

        Args:
            url: Website URL to scrape.

        Returns:
            Dictionary with page content:
            {
                "homepage": {"html": str, "text": str, "soup": BeautifulSoup},
                "contact_pages": [...],
                "all_text": str,
                "reachable": bool,
                "team_members": [...],
                "structured_data": {...},
            }
        """
        result = {
            "homepage": None,
            "contact_pages": [],
            "all_text": "",
            "reachable": False,
            "team_members": [],
            "structured_data": None,
        }

        await self.rate_limiter.acquire()

        try:
            # Fetch homepage
            homepage_data = await self._fetch_page(url)
            if homepage_data:
                result["homepage"] = homepage_data
                result["reachable"] = True
                result["all_text"] = homepage_data.get("text", "")

                # Extract JSON-LD structured data from homepage
                result["structured_data"] = self._extract_jsonld(homepage_data.get("soup"))

                # Find and fetch contact/about pages
                contact_pages = await self._fetch_contact_pages(url, homepage_data)
                result["contact_pages"] = contact_pages

                # Combine all text and extract team members from all pages
                all_soups = [homepage_data.get("soup")]
                for page_data in contact_pages:
                    result["all_text"] += "\n" + page_data.get("text", "")
                    all_soups.append(page_data.get("soup"))

                    # Check for JSON-LD in contact pages too
                    if not result["structured_data"]:
                        result["structured_data"] = self._extract_jsonld(page_data.get("soup"))

                # Extract team members from all pages
                result["team_members"] = self._extract_team_members(all_soups)

        except Exception as e:
            logger.warning("website_scrape_failed", url=url, error=str(e))

        return result

    async def _fetch_page(self, url: str) -> dict | None:
        """Fetch a single page and parse it.

        Args:
            url: Page URL.

        Returns:
            Dictionary with html, text, and soup, or None if failed.
        """
        try:
            response = await self.client.get(url)
            response.raise_for_status()

            html = response.text
            soup = BeautifulSoup(html, "lxml")

            # Extract text content
            # Remove script and style elements
            for element in soup(["script", "style", "nav", "footer", "header"]):
                element.decompose()

            text = soup.get_text(separator=" ", strip=True)

            return {
                "url": str(response.url),
                "html": html,
                "text": text,
                "soup": soup,
            }

        except httpx.HTTPStatusError as e:
            logger.debug("page_http_error", url=url, status=e.response.status_code)
        except httpx.RequestError as e:
            logger.debug("page_request_error", url=url, error=str(e))
        except Exception as e:
            logger.debug("page_parse_error", url=url, error=str(e))

        return None

    async def _fetch_contact_pages(self, base_url: str, homepage_data: dict) -> list[dict]:
        """Find and fetch contact-related pages.

        Args:
            base_url: Website base URL.
            homepage_data: Parsed homepage data.

        Returns:
            List of parsed page data dictionaries.
        """
        pages_to_fetch = set()

        # Add common paths
        parsed = urlparse(base_url)
        base = f"{parsed.scheme}://{parsed.netloc}"

        for path in self.CONTACT_PATHS:
            pages_to_fetch.add(urljoin(base, path))

        # Look for contact links in homepage
        soup = homepage_data.get("soup")
        if soup:
            for link in soup.find_all("a", href=True):
                href = link.get("href", "").lower()
                link_text = link.get_text(strip=True).lower()

                if any(
                    keyword in href or keyword in link_text
                    for keyword in ["contact", "about", "team", "people"]
                ):
                    full_url = urljoin(base_url, link["href"])
                    # Only include same-domain links
                    if urlparse(full_url).netloc == parsed.netloc:
                        pages_to_fetch.add(full_url)

        # Limit number of pages to fetch
        pages_to_fetch = list(pages_to_fetch)[:5]

        # Fetch pages concurrently with rate limiting
        results = []
        for page_url in pages_to_fetch:
            await self.rate_limiter.acquire()
            page_data = await self._fetch_page(page_url)
            if page_data:
                results.append(page_data)

        return results

    def _extract_jsonld(self, soup: BeautifulSoup | None) -> dict | None:
        """Extract JSON-LD structured data from page.

        Args:
            soup: BeautifulSoup object of the page.

        Returns:
            Dictionary with organization/business info, or None.
        """
        if not soup:
            return None

        try:
            # Find all JSON-LD scripts
            scripts = soup.find_all("script", type="application/ld+json")

            for script in scripts:
                try:
                    data = json.loads(script.string or "{}")

                    # Handle @graph format
                    if "@graph" in data:
                        for item in data["@graph"]:
                            if item.get("@type") in [
                                "Organization",
                                "LocalBusiness",
                                "Corporation",
                                "Restaurant",
                                "Store",
                            ]:
                                return self._parse_jsonld_org(item)
                    # Direct type
                    elif data.get("@type") in [
                        "Organization",
                        "LocalBusiness",
                        "Corporation",
                        "Restaurant",
                        "Store",
                    ]:
                        return self._parse_jsonld_org(data)

                except json.JSONDecodeError:
                    continue

        except Exception as e:
            logger.debug("jsonld_extraction_failed", error=str(e))

        return None

    def _parse_jsonld_org(self, data: dict) -> dict:
        """Parse organization data from JSON-LD.

        Args:
            data: JSON-LD organization object.

        Returns:
            Simplified dictionary with key fields.
        """
        result = {}

        # Basic info
        if data.get("name"):
            result["name"] = data["name"]
        if data.get("description"):
            result["description"] = data["description"]
        if data.get("url"):
            result["url"] = data["url"]
        if data.get("telephone"):
            result["phone"] = data["telephone"]
        if data.get("email"):
            result["email"] = data["email"]

        # Address
        address = data.get("address", {})
        if isinstance(address, dict):
            result["address"] = {
                "street": address.get("streetAddress"),
                "city": address.get("addressLocality"),
                "region": address.get("addressRegion"),
                "postal": address.get("postalCode"),
                "country": address.get("addressCountry"),
            }

        # Founder/CEO
        founder = data.get("founder") or data.get("foundingMember")
        if founder:
            if isinstance(founder, list):
                founder = founder[0] if founder else None
            if isinstance(founder, dict):
                result["founder"] = {
                    "name": founder.get("name"),
                    "role": "Founder",
                }
            elif isinstance(founder, str):
                result["founder"] = {"name": founder, "role": "Founder"}

        # Social links
        same_as = data.get("sameAs", [])
        if same_as:
            result["social_links"] = same_as if isinstance(same_as, list) else [same_as]

        return result

    def _extract_team_members(self, soups: list[BeautifulSoup | None]) -> list[dict]:
        """Extract team member information from pages.

        Args:
            soups: List of BeautifulSoup objects.

        Returns:
            List of team member dictionaries.
        """
        team_members = []
        seen_names = set()

        for soup in soups:
            if not soup:
                continue

            try:
                # Method 1: Look for common team member patterns
                # Team cards/sections often have specific classes or structures
                team_containers = soup.find_all(
                    ["div", "section", "article"],
                    class_=re.compile(r"team|member|staff|people|leadership", re.I),
                )

                for container in team_containers:
                    members = self._extract_members_from_container(container)
                    for member in members:
                        if member.get("name") and member["name"].lower() not in seen_names:
                            seen_names.add(member["name"].lower())
                            team_members.append(member)

                # Method 2: Look for vcard/hcard microformat
                vcards = soup.find_all(class_=re.compile(r"vcard|h-card", re.I))
                for vcard in vcards:
                    member = self._extract_member_from_vcard(vcard)
                    if member and member.get("name") and member["name"].lower() not in seen_names:
                        seen_names.add(member["name"].lower())
                        team_members.append(member)

            except Exception as e:
                logger.debug("team_extraction_failed", error=str(e))

        return team_members[:20]  # Limit to 20 members

    def _extract_members_from_container(self, container) -> list[dict]:
        """Extract team members from a container element.

        Args:
            container: BeautifulSoup element.

        Returns:
            List of member dictionaries.
        """
        members = []

        # Look for individual member cards within the container
        member_cards = container.find_all(
            ["div", "article", "li"],
            class_=re.compile(r"member|person|card|profile|bio", re.I),
        )

        if not member_cards:
            # Try finding by structure: heading + paragraph patterns
            member_cards = [container]

        for card in member_cards:
            member = {}

            # Look for name in headings
            for tag in ["h1", "h2", "h3", "h4", "h5", "strong", "b"]:
                name_elem = card.find(tag)
                if name_elem:
                    name = name_elem.get_text(strip=True)
                    # Filter out obvious non-names
                    if name and len(name) < 50 and not any(
                        kw in name.lower()
                        for kw in ["team", "about", "contact", "our", "meet"]
                    ):
                        member["name"] = name
                        break

            if not member.get("name"):
                continue

            # Look for role/title
            role_patterns = [
                re.compile(r"title|role|position|job|designation", re.I),
            ]
            for pattern in role_patterns:
                role_elem = card.find(class_=pattern)
                if role_elem:
                    member["role"] = role_elem.get_text(strip=True)
                    break

            # Look for email
            email_link = card.find("a", href=re.compile(r"mailto:"))
            if email_link:
                href = email_link.get("href", "")
                member["email"] = href.replace("mailto:", "").split("?")[0]

            # Look for LinkedIn
            linkedin_link = card.find("a", href=re.compile(r"linkedin\.com"))
            if linkedin_link:
                member["linkedin"] = linkedin_link.get("href")

            if member.get("name"):
                members.append(member)

        return members

    def _extract_member_from_vcard(self, vcard) -> dict | None:
        """Extract member info from vcard/hcard format.

        Args:
            vcard: BeautifulSoup element with vcard class.

        Returns:
            Member dictionary or None.
        """
        member = {}

        # Name
        fn = vcard.find(class_=re.compile(r"fn|p-name", re.I))
        if fn:
            member["name"] = fn.get_text(strip=True)

        # Title/Role
        title = vcard.find(class_=re.compile(r"title|role|p-job-title", re.I))
        if title:
            member["role"] = title.get_text(strip=True)

        # Email
        email = vcard.find(class_=re.compile(r"email|u-email", re.I))
        if email:
            if email.name == "a":
                href = email.get("href", "")
                member["email"] = href.replace("mailto:", "").split("?")[0]
            else:
                member["email"] = email.get_text(strip=True)

        return member if member.get("name") else None
