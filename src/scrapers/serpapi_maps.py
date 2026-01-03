"""Google Maps scraper using SerpAPI."""

import asyncio
from datetime import datetime

import httpx

from config.settings import settings
from src.models.lead import RawLead
from src.utils.logger import get_logger

logger = get_logger("serpapi")


class SerpAPIMapsScraper:
    """Scraper using SerpAPI for Google Maps data.

    SerpAPI provides structured access to Google Maps data without browser automation.
    This avoids IP blocking issues common with Playwright in cloud environments.

    API Docs: https://serpapi.com/google-maps-api
    Place Details: https://serpapi.com/google-maps-place-details-api
    """

    BASE_URL = "https://serpapi.com/search"
    # Parallel requests for place details (balance speed vs rate limits)
    MAX_CONCURRENT_DETAILS = 5
    # Error codes that trigger key rotation
    ROTATABLE_STATUS_CODES = (401, 402, 429, 500, 502, 503)

    def __init__(self, max_results: int | None = None, fetch_details: bool = True):
        """Initialize the SerpAPI scraper.

        Args:
            max_results: Maximum number of results to fetch. Defaults to settings value.
            fetch_details: Whether to fetch detailed info for each place (uses extra API credits).
        """
        self.max_results = max_results or settings.max_results_per_query
        self.fetch_details = fetch_details
        self.api_keys = settings.get_serpapi_keys()
        if not self.api_keys:
            raise ValueError("SERPAPI_KEY is required when use_serpapi=true")
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
                "rotating_serpapi_key",
                new_index=self.current_key_index,
                total_keys=len(self.api_keys),
            )
            return True
        return False

    def _should_rotate(self, status_code: int) -> bool:
        """Check if the error status code should trigger key rotation."""
        return status_code in self.ROTATABLE_STATUS_CODES

    async def _request_with_fallback(
        self, client: httpx.AsyncClient, params: dict
    ) -> dict | None:
        """Make a request with automatic key rotation on failure.

        Args:
            client: HTTP client.
            params: Request parameters (api_key will be set automatically).

        Returns:
            Response JSON or None if all keys failed.
        """
        attempts = 0
        max_attempts = len(self.api_keys)

        while attempts < max_attempts:
            params["api_key"] = self._get_current_key()
            attempts += 1

            try:
                response = await client.get(self.BASE_URL, params=params)

                # Check for rotatable errors before raising
                if response.status_code >= 400:
                    if self._should_rotate(response.status_code):
                        logger.warning(
                            "serpapi_key_error",
                            status=response.status_code,
                            key_index=self.current_key_index,
                        )
                        if self._rotate_key():
                            continue
                    # No more keys or non-rotatable error
                    response.raise_for_status()

                data = response.json()

                # SerpAPI sometimes returns error in body with 200 status
                if "error" in data:
                    error_msg = data["error"]
                    # Check if it's a quota/auth error
                    if any(x in error_msg.lower() for x in ["invalid", "quota", "limit", "key"]):
                        logger.warning(
                            "serpapi_key_error_in_body",
                            error=error_msg,
                            key_index=self.current_key_index,
                        )
                        if self._rotate_key():
                            continue
                    return None

                return data

            except httpx.HTTPError as e:
                status = getattr(getattr(e, 'response', None), 'status_code', 500)
                logger.warning(
                    "serpapi_request_error",
                    error=str(e),
                    status=status,
                    key_index=self.current_key_index,
                )
                if self._should_rotate(status) and self._rotate_key():
                    continue
                raise

        logger.error("all_serpapi_keys_exhausted", total_keys=len(self.api_keys))
        return None

    async def scrape(self, query: str) -> list[RawLead]:
        """Scrape Google Maps via SerpAPI.

        Args:
            query: Search query (e.g., "coffee shops in Tokyo").

        Returns:
            List of RawLead objects.
        """
        logger.info(
            "starting_serpapi_scrape",
            query=query,
            max_results=self.max_results,
            fetch_details=self.fetch_details,
        )

        all_results = []
        start = 0

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Step 1: Collect all search results first
            while len(all_results) < self.max_results:
                params = {
                    "engine": "google_maps",
                    "q": query,
                    "type": "search",
                    "start": start,
                }

                data = await self._request_with_fallback(client, params)
                if data is None:
                    break

                local_results = data.get("local_results", [])
                if not local_results:
                    logger.info("no_more_results", start=start)
                    break

                # Add results up to max
                for result in local_results:
                    if len(all_results) >= self.max_results:
                        break
                    all_results.append(result)

                start += len(local_results)
                if len(local_results) < 20:
                    break

            # Step 2: Fetch place details in parallel (if enabled)
            if self.fetch_details and all_results:
                all_results = await self._fetch_all_details(client, all_results)

        # Step 3: Parse all results into leads
        leads = []
        for result in all_results:
            lead = self._parse_result(result, query)
            if lead:
                leads.append(lead)
                logger.debug("lead_extracted", name=lead.name)

        logger.info("serpapi_scrape_complete", query=query, leads_found=len(leads))
        return leads

    async def _fetch_all_details(
        self, client: httpx.AsyncClient, results: list[dict]
    ) -> list[dict]:
        """Fetch place details for all results in parallel batches.

        Args:
            client: HTTP client.
            results: List of search results.

        Returns:
            Results with detailed data merged in.
        """
        semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_DETAILS)

        async def fetch_with_semaphore(idx: int, result: dict) -> tuple[int, dict]:
            async with semaphore:
                data_id = result.get("data_id")
                if data_id:
                    detailed = await self._fetch_place_details(client, data_id)
                    if detailed:
                        return idx, self._merge_results(result, detailed)
                return idx, result

        # Fetch all details concurrently
        tasks = [fetch_with_semaphore(i, r) for i, r in enumerate(results)]
        completed = await asyncio.gather(*tasks)

        # Rebuild results in original order
        enriched = [None] * len(results)
        for idx, result in completed:
            enriched[idx] = result

        logger.info("place_details_fetched", count=len(results))
        return enriched

    async def _fetch_place_details(self, client: httpx.AsyncClient, data_id: str) -> dict | None:
        """Fetch detailed place information using Place Details API.

        This uses an additional API credit but provides much more data.

        Args:
            client: HTTP client.
            data_id: The data_id from the search result.

        Returns:
            Detailed place data or None if fetch fails.
        """
        params = {
            "engine": "google_maps_place_details",
            "data_id": data_id,
        }

        try:
            data = await self._request_with_fallback(client, params)
            if data is None:
                return None

            # Place details returns data at top level or in place_results
            if "place_results" in data:
                return data["place_results"]
            # Sometimes data is at the top level (title, phone, etc.)
            if "title" in data or "phone" in data:
                return data
            return None

        except httpx.HTTPError as e:
            logger.debug("place_details_fetch_failed", data_id=data_id, error=str(e))
            return None

    def _merge_results(self, basic: dict, detailed: dict) -> dict:
        """Merge basic search result with detailed place data.

        Detailed data takes priority for overlapping fields.

        Args:
            basic: Basic search result.
            detailed: Detailed place result.

        Returns:
            Merged result dictionary.
        """
        merged = basic.copy()

        # Fields from detailed result that enhance data quality
        detail_fields = [
            "phone", "website", "address", "rating", "reviews",
            "hours", "operating_hours", "price", "gps_coordinates",
            "description", "photos", "images", "user_reviews",
            "service_options", "about", "amenities",
        ]

        for field in detail_fields:
            if field in detailed and detailed[field]:
                merged[field] = detailed[field]

        return merged

    def _parse_result(self, result: dict, query: str) -> RawLead | None:
        """Parse a SerpAPI result into a RawLead.

        Args:
            result: Single result from SerpAPI local_results.
            query: Original search query.

        Returns:
            RawLead object or None if parsing fails.
        """
        try:
            # Extract GPS coordinates
            gps = result.get("gps_coordinates", {})
            latitude = gps.get("latitude")
            longitude = gps.get("longitude")

            # Parse business hours - try multiple formats
            business_hours = None
            is_open_now = None

            # Try operating_hours first (structured format)
            operating_hours = result.get("operating_hours")
            if operating_hours and isinstance(operating_hours, dict):
                business_hours = operating_hours
            else:
                # Fallback to hours field
                hours_data = result.get("hours")
                if hours_data:
                    if isinstance(hours_data, str):
                        # Sometimes hours come as a simple string like "Open 24 hours"
                        business_hours = {"info": hours_data}
                    elif isinstance(hours_data, list):
                        # Parse structured hours list
                        business_hours = {}
                        for hour_entry in hours_data:
                            if isinstance(hour_entry, dict):
                                day = hour_entry.get("day", "")
                                hours_str = hour_entry.get("hours", "")
                                if day and hours_str:
                                    business_hours[day] = hours_str
                    elif isinstance(hours_data, dict):
                        business_hours = hours_data

            # Check open_state for is_open_now
            open_state = result.get("open_state")
            if open_state:
                open_state_lower = open_state.lower()
                if "open" in open_state_lower:
                    is_open_now = True
                elif "closed" in open_state_lower:
                    is_open_now = False

            # Parse price level
            price = result.get("price")
            price_level = None
            if price:
                # SerpAPI returns price as "$", "$$", "$$$", "$$$$"
                if isinstance(price, str) and price.startswith("$"):
                    price_level = price

            # Extract categories (multiple types if available)
            categories = []
            primary_type = result.get("type", "Unknown")
            types_list = result.get("types", [])
            if types_list and isinstance(types_list, list):
                categories = types_list
            elif primary_type and primary_type != "Unknown":
                categories = [primary_type]

            # Count photos from multiple sources
            photos_count = 0
            # From thumbnail
            if result.get("thumbnail"):
                photos_count = 1
            # From photos array (Place Details API)
            photos = result.get("photos", [])
            if photos and isinstance(photos, list):
                photos_count = max(photos_count, len(photos))
            # From images array (alternative field name)
            images = result.get("images", [])
            if images and isinstance(images, list):
                photos_count = max(photos_count, len(images))

            # Build maps URL
            place_id = result.get("place_id")
            data_cid = result.get("data_cid")
            if place_id:
                maps_url = f"https://www.google.com/maps/place/?q=place_id:{place_id}"
            elif data_cid:
                maps_url = f"https://www.google.com/maps?cid={data_cid}"
            elif latitude and longitude:
                maps_url = f"https://www.google.com/maps/search/?api=1&query={latitude},{longitude}"
            else:
                maps_url = None

            return RawLead(
                place_id=place_id or data_cid or f"serpapi_{result.get('position', 0)}",
                name=result.get("title", "Unknown"),
                phone=result.get("phone"),
                website=result.get("website"),
                address=result.get("address", "Unknown"),
                latitude=latitude,
                longitude=longitude,
                category=primary_type,
                categories=categories,
                rating=result.get("rating"),
                review_count=result.get("reviews", 0) or 0,
                price_level=price_level,
                business_hours=business_hours,
                is_open_now=is_open_now,
                photos_count=photos_count,
                is_claimed=None,  # Not available in SerpAPI basic results
                years_in_business=None,  # Not available in SerpAPI basic results
                search_query=query,
                maps_url=maps_url,
                scraped_at=datetime.utcnow(),
            )

        except Exception as e:
            logger.warning("parse_result_failed", error=str(e), result=result)
            return None
