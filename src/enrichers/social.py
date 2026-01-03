"""Social media link extraction from website content."""

import re
from urllib.parse import urlparse

from src.models.lead import SocialLinks
from src.utils.logger import get_logger

logger = get_logger("social_extractor")


class SocialExtractor:
    """Extract social media links from website content."""

    # Social media URL patterns
    PATTERNS = {
        "linkedin": [
            r'linkedin\.com/company/[\w-]+',
            r'linkedin\.com/in/[\w-]+',
        ],
        "facebook": [
            r'facebook\.com/[\w.-]+',
            r'fb\.com/[\w.-]+',
        ],
        "instagram": [
            r'instagram\.com/[\w.-]+',
        ],
        "twitter": [
            r'twitter\.com/[\w]+',
            r'x\.com/[\w]+',
        ],
        "youtube": [
            r'youtube\.com/(?:channel|c|user)/[\w-]+',
            r'youtube\.com/@[\w-]+',
        ],
        "tiktok": [
            r'tiktok\.com/@[\w.-]+',
        ],
    }

    # Pages to exclude (not actual profiles)
    EXCLUDE_PATHS = {
        "sharer",
        "share",
        "intent",
        "login",
        "signup",
        "help",
        "about",
        "legal",
        "privacy",
        "terms",
        "tr",  # Facebook tracking pixel
        "rsrc.php",  # Facebook resource file
        "plugins",
        "dialog",
        "watch",  # Generic YouTube watch (not a channel)
    }

    # Invalid profile names (tracking/resource files)
    INVALID_PROFILES = {
        "tr",
        "rsrc.php",
        "plugins",
        "sharer.php",
        "dialog",
        "watch",
        "embed",
        "api",
        "sdk",
        "pixel",
        "events",
    }

    def extract(self, website_data: dict) -> SocialLinks:
        """Extract social media links from website data.

        Args:
            website_data: Dictionary from WebsiteScraper.

        Returns:
            SocialLinks object with extracted profiles.
        """
        found = {
            "linkedin": None,
            "facebook": None,
            "instagram": None,
            "twitter": None,
            "youtube": None,
            "tiktok": None,
        }

        # Collect all HTML content
        html_content = ""

        homepage = website_data.get("homepage")
        if homepage:
            html_content += homepage.get("html", "") or ""

        for page in website_data.get("contact_pages", []):
            html_content += page.get("html", "") or ""

        # Extract links from HTML
        for platform, patterns in self.PATTERNS.items():
            for pattern in patterns:
                matches = re.findall(pattern, html_content, re.IGNORECASE)
                for match in matches:
                    url = self._normalize_url(match, platform)
                    if url and self._is_valid_profile(url):
                        found[platform] = url
                        break  # Take first valid match

                if found[platform]:
                    break

        return SocialLinks(**found)

    def _normalize_url(self, match: str, platform: str) -> str | None:
        """Normalize extracted URL to full format."""
        if not match:
            return None

        # Add https:// if not present
        if not match.startswith("http"):
            match = f"https://{match}"

        try:
            # Clean up trailing slashes and query params
            parsed = urlparse(match)
            path = parsed.path.rstrip("/")

            # Reconstruct clean URL
            return f"{parsed.scheme}://{parsed.netloc}{path}"
        except Exception:
            return None

    def _is_valid_profile(self, url: str) -> bool:
        """Check if URL is a valid profile and not a share/intent/tracker link."""
        if not url:
            return False

        try:
            parsed = urlparse(url)
            path_parts = parsed.path.lower().split("/")

            # Check for excluded paths
            for part in path_parts:
                if part in self.EXCLUDE_PATHS:
                    return False

            # Must have a path (not just domain)
            if not parsed.path or parsed.path == "/":
                return False

            # Get the profile/page name (last non-empty path segment)
            profile_name = None
            for part in reversed(path_parts):
                if part:
                    profile_name = part
                    break

            # Check if profile name is invalid
            if profile_name and profile_name.lower() in self.INVALID_PROFILES:
                return False

            # Profile name should have reasonable length (not a tracking ID)
            if profile_name and (len(profile_name) < 2 or len(profile_name) > 100):
                return False

            return True
        except Exception:
            return False

    def extract_handles(self, social_links: SocialLinks) -> dict[str, str | None]:
        """Extract usernames/handles from social URLs.

        Args:
            social_links: SocialLinks object.

        Returns:
            Dictionary of platform -> handle.
        """
        handles = {}

        if social_links.instagram:
            match = re.search(r'instagram\.com/([\w.-]+)', social_links.instagram)
            handles["instagram"] = f"@{match.group(1)}" if match else None

        if social_links.twitter:
            match = re.search(r'(?:twitter|x)\.com/([\w]+)', social_links.twitter)
            handles["twitter"] = f"@{match.group(1)}" if match else None

        if social_links.tiktok:
            match = re.search(r'tiktok\.com/@([\w.-]+)', social_links.tiktok)
            handles["tiktok"] = f"@{match.group(1)}" if match else None

        return handles
