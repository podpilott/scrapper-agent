"""Main pipeline orchestrator."""

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

import phonenumbers

from config.settings import settings
from src.enrichers import (
    CompanyEnricher,
    ContactDiscovery,
    ContactExtractor,
    EmailExtractor,
    SocialExtractor,
)
from src.generators import LLMClient, OutreachGenerator
from src.models.lead import EnrichedLead, FinalLead, RawLead, ScoredLead
from src.processors import LeadAnalyzer, LeadScorer
from src.scrapers import SerpAPIMapsScraper, WebsiteScraper
from src.utils.logger import get_logger, setup_logging

logger = get_logger("pipeline")


@dataclass
class PipelineResult:
    """Result from a pipeline run."""

    query: str
    total_scraped: int = 0
    total_enriched: int = 0
    total_scored: int = 0
    total_qualified: int = 0
    total_with_outreach: int = 0

    leads: list[FinalLead] = field(default_factory=list)

    run_id: str = field(default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S"))
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None

    @property
    def duration_seconds(self) -> float | None:
        if self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None


class Pipeline:
    """Main pipeline orchestrating the full lead generation process."""

    def __init__(
        self,
        max_results: int | None = None,
        min_score: int | None = None,
        skip_enrichment: bool = False,
        skip_outreach: bool = False,
        product_context: str | None = None,
        progress_callback: Callable[[str, int, int], None] | None = None,
        lead_callback: Callable[["FinalLead"], None] | None = None,
    ):
        """Initialize the pipeline.

        Args:
            max_results: Maximum leads to scrape.
            min_score: Minimum score for qualified leads.
            skip_enrichment: Skip website enrichment step.
            skip_outreach: Skip outreach message generation.
            product_context: Your product/service description for outreach.
            progress_callback: Callback for progress updates (step, current, total).
            lead_callback: Callback for each lead processed (for streaming).
        """
        self.max_results = max_results if max_results is not None else settings.max_results_per_query
        self.min_score = min_score if min_score is not None else settings.min_score_for_outreach
        self.skip_enrichment = skip_enrichment
        self.skip_outreach = skip_outreach
        self.product_context = product_context
        self.progress_callback = progress_callback
        self.lead_callback = lead_callback

        # Initialize components - SerpAPI scraper
        if not settings.serpapi_key:
            raise ValueError("SERPAPI_KEY is required. Get one at https://serpapi.com")

        self.maps_scraper = SerpAPIMapsScraper(
            max_results=self.max_results,
            fetch_details=settings.serpapi_fetch_details,
        )
        logger.info("using_serpapi_scraper", fetch_details=settings.serpapi_fetch_details)
        self.website_scraper = WebsiteScraper()
        self.email_extractor = EmailExtractor()
        self.social_extractor = SocialExtractor()
        self.contact_extractor = ContactExtractor()
        self.scorer = LeadScorer()

        # New enrichers for search-based intelligence
        self.company_enricher = CompanyEnricher()
        self.contact_discovery = ContactDiscovery()
        self.lead_analyzer = LeadAnalyzer(
            ideal_customer_profile=settings.ideal_customer_profile or None,
        )

        # Setup logging
        setup_logging()

    def _progress(self, step: str, current: int, total: int) -> None:
        """Report progress if callback is set."""
        if self.progress_callback:
            self.progress_callback(step, current, total)

    async def run(self, query: str) -> PipelineResult:
        """Run the full pipeline.

        Args:
            query: Search query (e.g., "coffee shops in Tokyo").

        Returns:
            PipelineResult with all data and export paths.
        """
        result = PipelineResult(query=query)
        logger.info("pipeline_started", query=query)

        try:
            # Step 1: Scrape Google Maps
            logger.info("step_1_scraping")
            raw_leads = await self.maps_scraper.scrape(query)
            result.total_scraped = len(raw_leads)
            self._progress("Scraping Google Maps", len(raw_leads), len(raw_leads))

            if not raw_leads:
                logger.warning("no_leads_scraped")
                return result

            # Step 2: Enrich leads
            if not self.skip_enrichment:
                logger.info("step_2_enriching")
                enriched_leads = await self._enrich_leads(raw_leads)
            else:
                enriched_leads = [self._minimal_enrichment(lead) for lead in raw_leads]

            result.total_enriched = len(enriched_leads)

            # Step 3: Score leads
            logger.info("step_3_scoring")
            scored_leads = self.scorer.score_batch(enriched_leads)
            result.total_scored = len(scored_leads)

            # Step 4: Filter by minimum score
            qualified_leads = self.scorer.filter_by_min_score(scored_leads, self.min_score)
            result.total_qualified = len(qualified_leads)
            self._progress("Scoring leads", len(qualified_leads), len(scored_leads))

            # Step 5: Generate outreach
            if not self.skip_outreach and qualified_leads:
                logger.info("step_5_outreach")
                final_leads = await self._generate_outreach(qualified_leads)
                result.total_with_outreach = len(final_leads)
            else:
                final_leads = []
                for lead in qualified_leads:
                    final_lead = FinalLead(scored_lead=lead)
                    final_leads.append(final_lead)
                    # Call lead callback for streaming (even without outreach)
                    if self.lead_callback:
                        self.lead_callback(final_lead)

            result.leads = final_leads

            result.completed_at = datetime.utcnow()
            logger.info(
                "pipeline_completed",
                total_leads=len(final_leads),
                duration=result.duration_seconds,
            )

        except Exception as e:
            logger.error("pipeline_failed", error=str(e))
            raise

        finally:
            # Cleanup
            await self.website_scraper.close()

        return result

    async def _enrich_leads(self, raw_leads: list[RawLead]) -> list[EnrichedLead]:
        """Enrich leads with website data."""
        enriched = []

        for i, raw_lead in enumerate(raw_leads):
            self._progress("Enriching leads", i + 1, len(raw_leads))

            try:
                enriched_lead = await self._enrich_single(raw_lead)
                enriched.append(enriched_lead)
            except Exception as e:
                logger.warning("enrichment_failed", name=raw_lead.name, error=str(e))
                # Add minimal enrichment on failure
                enriched.append(self._minimal_enrichment(raw_lead))

        return enriched

    async def _enrich_single(self, raw_lead: RawLead) -> EnrichedLead:
        """Enrich a single lead with website, search, and LLM analysis."""
        emails = []
        primary_email = None
        social_links = None
        owner_name = None
        whatsapp = None
        website_reachable = False
        has_contact_form = False
        team_members = []
        structured_data = None

        # Enrich from website if available
        if raw_lead.website:
            website_data = await self.website_scraper.scrape_website(raw_lead.website)
            website_reachable = website_data.get("reachable", False)

            if website_reachable:
                # Extract emails
                extracted_emails = self.email_extractor.extract(website_data)
                emails = [e.email for e in extracted_emails]
                primary_email = self.email_extractor.get_best_email(extracted_emails)

                # Extract social links
                social_links = self.social_extractor.extract(website_data)

                # Extract contacts
                contacts = self.contact_extractor.extract(website_data)
                owner_name = self.contact_extractor.get_owner_name(contacts)

                # Extract team members (NEW)
                team_members = website_data.get("team_members", [])

                # Extract structured data (NEW)
                structured_data = website_data.get("structured_data")

                # Check for contact form in page content
                all_text = website_data.get("all_text", "").lower()
                has_contact_form = any(
                    keyword in all_text
                    for keyword in ["contact form", "get in touch", "send message", "hubungi kami"]
                )

                # Try to get owner from structured data if not found
                if not owner_name and structured_data:
                    founder = structured_data.get("founder")
                    if founder and isinstance(founder, dict):
                        owner_name = founder.get("name")

        # Generate WhatsApp link from phone
        if raw_lead.phone:
            whatsapp = self._phone_to_whatsapp(raw_lead.phone, raw_lead.address)

        # Create base enriched lead
        enriched = EnrichedLead(
            raw=raw_lead,
            emails=emails,
            primary_email=primary_email,
            social_links=social_links or SocialExtractor().extract({}),
            owner_name=owner_name,
            whatsapp=whatsapp,
            website_reachable=website_reachable,
            has_contact_form=has_contact_form,
            team_members=team_members,
            structured_data=structured_data,
        )

        # NEW: Search-based company enrichment
        if settings.enable_company_enrichment:
            try:
                company_intel = await self.company_enricher.enrich(raw_lead)
                enriched.company_intel = company_intel
                logger.debug(
                    "company_enrichment_complete",
                    name=raw_lead.name,
                    has_news=bool(company_intel.recent_news),
                )
            except Exception as e:
                logger.warning(
                    "company_enrichment_failed",
                    name=raw_lead.name,
                    error=str(e),
                )

        # NEW: Search-based contact discovery
        if settings.enable_contact_discovery:
            try:
                discovered = await self.contact_discovery.find_contacts(
                    raw_lead, owner_name
                )
                enriched.discovered_contacts = discovered

                # Use discovered contact info if we don't have it
                if not enriched.social_links.linkedin and discovered:
                    for contact in discovered:
                        if contact.linkedin_url:
                            enriched.social_links.linkedin = contact.linkedin_url
                            break

                logger.debug(
                    "contact_discovery_complete",
                    name=raw_lead.name,
                    contacts_found=len(discovered),
                )
            except Exception as e:
                logger.warning(
                    "contact_discovery_failed",
                    name=raw_lead.name,
                    error=str(e),
                )

        # NEW: LLM-powered lead analysis
        if settings.enable_lead_analysis:
            try:
                # Run analysis in thread pool since it's synchronous
                analysis = await asyncio.to_thread(
                    self.lead_analyzer.analyze, enriched
                )
                enriched.analysis = analysis
                logger.debug(
                    "lead_analysis_complete",
                    name=raw_lead.name,
                    fit_score=analysis.fit_score,
                    pain_points=len(analysis.pain_points),
                )
            except Exception as e:
                logger.warning(
                    "lead_analysis_failed",
                    name=raw_lead.name,
                    error=str(e),
                )

        return enriched

    def _minimal_enrichment(self, raw_lead: RawLead) -> EnrichedLead:
        """Create minimal enrichment for a lead (no website data)."""
        whatsapp = None
        if raw_lead.phone:
            whatsapp = self._phone_to_whatsapp(raw_lead.phone, raw_lead.address)

        return EnrichedLead(
            raw=raw_lead,
            whatsapp=whatsapp,
        )

    def _phone_to_whatsapp(self, phone: str, address: str | None = None) -> str | None:
        """Convert phone number to WhatsApp format.

        Args:
            phone: Phone number string (may be local or international format).
            address: Business address to help determine country code.

        Returns:
            Phone in international format without + (e.g., "6285100443035") or None.
        """
        # Detect region from address
        region = self._detect_region_from_address(address) if address else None

        try:
            # Try to parse with region hint first
            if region:
                parsed = phonenumbers.parse(phone, region)
                if phonenumbers.is_valid_number(parsed):
                    return phonenumbers.format_number(
                        parsed,
                        phonenumbers.PhoneNumberFormat.E164,
                    ).replace("+", "")

            # Try to parse as international (no region hint)
            parsed = phonenumbers.parse(phone, None)
            if phonenumbers.is_valid_number(parsed):
                return phonenumbers.format_number(
                    parsed,
                    phonenumbers.PhoneNumberFormat.E164,
                ).replace("+", "")
        except Exception:
            pass

        # Fallback: strip non-digits
        digits = re.sub(r"[^\d]", "", phone)
        if len(digits) >= 10:
            return digits

        return None

    def _detect_region_from_address(self, address: str) -> str | None:
        """Detect ISO 3166-1 alpha-2 region code from address.

        Args:
            address: Full address string (typically includes country at end).

        Returns:
            Two-letter region code (e.g., "ID" for Indonesia) or None.
        """
        if not address:
            return None

        address_lower = address.lower()

        # Common country patterns and their region codes
        country_map = {
            # Indonesia
            "indonesia": "ID",
            "yogyakarta": "ID",
            "jakarta": "ID",
            "bandung": "ID",
            "surabaya": "ID",
            "bali": "ID",
            "semarang": "ID",
            "medan": "ID",
            "makassar": "ID",
            "denpasar": "ID",
            # Singapore
            "singapore": "SG",
            # Malaysia
            "malaysia": "MY",
            "kuala lumpur": "MY",
            # Thailand
            "thailand": "TH",
            "bangkok": "TH",
            # Philippines
            "philippines": "PH",
            "manila": "PH",
            # Vietnam
            "vietnam": "VN",
            "ho chi minh": "VN",
            "hanoi": "VN",
            # Japan
            "japan": "JP",
            "tokyo": "JP",
            "osaka": "JP",
            # South Korea
            "south korea": "KR",
            "korea": "KR",
            "seoul": "KR",
            # China
            "china": "CN",
            "beijing": "CN",
            "shanghai": "CN",
            # India
            "india": "IN",
            "mumbai": "IN",
            "delhi": "IN",
            "bangalore": "IN",
            # Australia
            "australia": "AU",
            "sydney": "AU",
            "melbourne": "AU",
            # USA
            "united states": "US",
            "usa": "US",
            "u.s.a": "US",
            # UK
            "united kingdom": "GB",
            "england": "GB",
            "london": "GB",
        }

        # Check for country/city matches (check longer strings first)
        for pattern, code in sorted(country_map.items(), key=lambda x: -len(x[0])):
            if pattern in address_lower:
                return code

        return None

    async def _generate_outreach(
        self,
        scored_leads: list[ScoredLead],
    ) -> list[FinalLead]:
        """Generate outreach messages for leads."""
        llm_client = LLMClient()
        generator = OutreachGenerator(
            llm_client=llm_client,
            product_context=self.product_context,
        )

        final_leads = []
        for i, lead in enumerate(scored_leads):
            self._progress("Generating outreach", i + 1, len(scored_leads))
            try:
                # Run synchronous LLM call in thread pool to avoid blocking event loop
                final_lead = await asyncio.to_thread(generator.generate, lead)
                final_leads.append(final_lead)
                # Call lead callback for streaming
                if self.lead_callback:
                    self.lead_callback(final_lead)
            except Exception as e:
                logger.warning(
                    "outreach_failed",
                    name=lead.lead.raw.name,
                    error=str(e),
                )
                final_lead = FinalLead(scored_lead=lead)
                final_leads.append(final_lead)
                # Still call callback for failed leads
                if self.lead_callback:
                    self.lead_callback(final_lead)

        return final_leads


def run_pipeline(
    query: str,
    max_results: int | None = None,
    min_score: int | None = None,
    skip_enrichment: bool = False,
    skip_outreach: bool = False,
    product_context: str | None = None,
) -> PipelineResult:
    """Convenience function to run the pipeline synchronously.

    Args:
        query: Search query.
        max_results: Maximum leads to scrape.
        min_score: Minimum score for qualified leads.
        skip_enrichment: Skip website enrichment.
        skip_outreach: Skip outreach generation.
        product_context: Your product/service description.

    Returns:
        PipelineResult with all data.
    """
    pipeline = Pipeline(
        max_results=max_results,
        min_score=min_score,
        skip_enrichment=skip_enrichment,
        skip_outreach=skip_outreach,
        product_context=product_context,
    )

    return asyncio.run(pipeline.run(query))
