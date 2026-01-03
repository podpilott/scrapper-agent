"""LLM-powered lead analysis and qualification."""

import json
from datetime import datetime

from config.settings import settings
from src.generators.llm import LLMClient
from src.models.lead import EnrichedLead, LeadAnalysis
from src.utils.logger import get_logger

logger = get_logger("lead_analyzer")


# Analysis prompts
LEAD_QUALIFICATION_PROMPT = """Analyze this business lead and rate how well it matches the ideal customer profile.

Business Information:
- Name: {name}
- Category: {category}
- Location: {address}
- Rating: {rating}/5 ({review_count} reviews)
- Website: {website}
- Phone: {phone}
- Employee Count: {employee_count}
- Founded: {founded_year}
- Company Description: {company_description}

Website Signals:
- Has Contact Form: {has_contact_form}
- Website Reachable: {website_reachable}
- Social Presence: {social_presence}

Ideal Customer Profile:
{ideal_customer_profile}

Respond in JSON format:
{{
    "fit_score": <0-100>,
    "fit_reasoning": "<why this score>",
    "recommended_approach": "<how to approach this lead>"
}}"""


PAIN_POINT_PROMPT = """Based on this business information, identify potential pain points and personalization hooks.

Business: {name}
Category: {category}
Rating: {rating}/5 ({review_count} reviews)
Location: {address}
Recent News: {recent_news}
Company Description: {company_description}

Think about:
1. What challenges might a {category} business face?
2. What would make them interested in new solutions?
3. What personalization hooks could make outreach more effective?

Respond in JSON format:
{{
    "pain_points": ["<pain point 1>", "<pain point 2>", "<pain point 3>"],
    "personalization_hooks": ["<hook 1>", "<hook 2>", "<hook 3>"],
    "potential_challenges": ["<challenge 1>", "<challenge 2>"]
}}"""


class LeadAnalyzer:
    """Analyze leads using LLM for qualification and insights."""

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        ideal_customer_profile: str | None = None,
    ):
        """Initialize lead analyzer.

        Args:
            llm_client: LLM client instance.
            ideal_customer_profile: Description of ideal customer.
        """
        self.llm = llm_client or LLMClient()
        self.ideal_customer_profile = (
            ideal_customer_profile
            or settings.ideal_customer_profile
            or "Small to medium businesses looking to improve operations and grow"
        )

    def analyze(self, lead: EnrichedLead) -> LeadAnalysis:
        """Perform comprehensive lead analysis.

        Args:
            lead: Enriched lead to analyze.

        Returns:
            LeadAnalysis with insights.
        """
        if not settings.enable_lead_analysis:
            return LeadAnalysis()

        analysis = LeadAnalysis(analyzed_at=datetime.utcnow())

        # Analyze fit
        try:
            fit_data = self._analyze_fit(lead)
            analysis.fit_score = fit_data.get("fit_score", 0)
            analysis.fit_reasoning = fit_data.get("fit_reasoning")
            analysis.recommended_approach = fit_data.get("recommended_approach")
        except Exception as e:
            logger.warning("fit_analysis_failed", name=lead.raw.name, error=str(e))

        # Extract pain points and hooks
        try:
            insights = self._extract_insights(lead)
            analysis.pain_points = insights.get("pain_points", [])
            analysis.personalization_hooks = insights.get("personalization_hooks", [])
            analysis.potential_challenges = insights.get("potential_challenges", [])
        except Exception as e:
            logger.warning("insight_extraction_failed", name=lead.raw.name, error=str(e))

        logger.debug(
            "lead_analyzed",
            name=lead.raw.name,
            fit_score=analysis.fit_score,
            pain_points=len(analysis.pain_points),
        )

        return analysis

    def _analyze_fit(self, lead: EnrichedLead) -> dict:
        """Analyze lead fit against ICP."""
        raw = lead.raw
        intel = lead.company_intel

        # Build social presence summary
        social_links = []
        if lead.social_links.linkedin:
            social_links.append("LinkedIn")
        if lead.social_links.facebook:
            social_links.append("Facebook")
        if lead.social_links.instagram:
            social_links.append("Instagram")

        prompt = LEAD_QUALIFICATION_PROMPT.format(
            name=raw.name,
            category=raw.category,
            address=raw.address,
            rating=raw.rating or "N/A",
            review_count=raw.review_count,
            website=raw.website or "None",
            phone=raw.phone or "None",
            employee_count=intel.employee_count or "Unknown",
            founded_year=intel.founded_year or "Unknown",
            company_description=intel.company_description or "No description available",
            has_contact_form=lead.has_contact_form,
            website_reachable=lead.website_reachable,
            social_presence=", ".join(social_links) if social_links else "None",
            ideal_customer_profile=self.ideal_customer_profile,
        )

        response = self.llm.generate(prompt, max_tokens=300, temperature=0.3)
        return self._parse_json_response(response)

    def _extract_insights(self, lead: EnrichedLead) -> dict:
        """Extract pain points and personalization hooks."""
        raw = lead.raw
        intel = lead.company_intel

        prompt = PAIN_POINT_PROMPT.format(
            name=raw.name,
            category=raw.category,
            rating=raw.rating or "N/A",
            review_count=raw.review_count,
            address=raw.address,
            recent_news="; ".join(intel.recent_news[:3]) if intel.recent_news else "No recent news",
            company_description=intel.company_description or "No description available",
        )

        response = self.llm.generate(prompt, max_tokens=400, temperature=0.5)
        return self._parse_json_response(response)

    def _parse_json_response(self, response: str) -> dict:
        """Parse JSON from LLM response."""
        try:
            # Try to find JSON in the response
            response = response.strip()

            # Handle markdown code blocks
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                response = response.split("```")[1].split("```")[0]

            return json.loads(response)
        except json.JSONDecodeError:
            # Try to extract JSON object
            start = response.find("{")
            end = response.rfind("}") + 1
            if start != -1 and end > start:
                try:
                    return json.loads(response[start:end])
                except json.JSONDecodeError:
                    pass

            logger.warning("json_parse_failed", response=response[:100])
            return {}
