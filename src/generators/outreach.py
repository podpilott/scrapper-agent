"""Outreach message generator using LLM."""

from config.prompts import DEFAULT_PRODUCT_CONTEXT, get_prompts
from src.generators.llm import LLMClient
from src.models.lead import FinalLead, OutreachMessages, ScoredLead
from src.utils.logger import get_logger

logger = get_logger("outreach")


class OutreachGenerator:
    """Generate personalized outreach messages for leads."""

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        product_context: str | None = None,
        language: str = "en",
    ):
        """Initialize the outreach generator.

        Args:
            llm_client: LLM client instance. Creates new one if not provided.
            product_context: Description of your product/service for personalization.
            language: Language for AI-generated messages ('en' or 'id').
        """
        self.llm = llm_client or LLMClient()
        self.language = language

        # Load language-specific prompts
        prompts = get_prompts(language)
        self.email_outreach_prompt = prompts.EMAIL_OUTREACH_PROMPT
        self.email_subject_prompt = prompts.EMAIL_SUBJECT_PROMPT
        self.linkedin_message_prompt = prompts.LINKEDIN_MESSAGE_PROMPT
        self.whatsapp_message_prompt = prompts.WHATSAPP_MESSAGE_PROMPT
        self.cold_call_script_prompt = prompts.COLD_CALL_SCRIPT_PROMPT

        self.product_context = product_context or prompts.DEFAULT_PRODUCT_CONTEXT

    def generate(self, scored_lead: ScoredLead) -> FinalLead:
        """Generate all outreach messages for a lead.

        Args:
            scored_lead: ScoredLead to generate messages for.

        Returns:
            FinalLead with outreach messages.
        """
        lead = scored_lead.lead
        raw = lead.raw
        intel = lead.company_intel
        analysis = lead.analysis

        # Build company intel summary
        intel_parts = []
        if intel.employee_count:
            intel_parts.append(f"Employees: {intel.employee_count}")
        if intel.founded_year:
            intel_parts.append(f"Founded: {intel.founded_year}")
        if intel.company_description:
            intel_parts.append(f"About: {intel.company_description[:150]}")
        company_intel = "\n".join(intel_parts) if intel_parts else "No additional company info available"

        # Prepare context with new intelligence
        context = {
            "business_name": raw.name,
            "category": raw.category,
            "rating": raw.rating or "N/A",
            "review_count": raw.review_count,
            "address": raw.address,
            "website": raw.website or "N/A",
            "owner_name": lead.owner_name or "Business Owner",
            "owner_info": f"Owner/Contact: {lead.owner_name}" if lead.owner_name else "",
            "product_context": self.product_context,
            # New intelligence fields
            "company_intel": company_intel,
            "pain_points": ", ".join(analysis.pain_points[:3]) if analysis.pain_points else "General business growth challenges",
            "personalization_hooks": ", ".join(analysis.personalization_hooks[:3]) if analysis.personalization_hooks else "Strong local presence",
            "personalization_hook": analysis.personalization_hooks[0] if analysis.personalization_hooks else "business growth",
            "recent_news": "; ".join(intel.recent_news[:2]) if intel.recent_news else "No recent news",
            "recommended_approach": analysis.recommended_approach or "Professional and consultative",
        }

        logger.info("generating_outreach", name=raw.name, has_analysis=bool(analysis.pain_points))

        # Generate messages for each channel
        outreach = OutreachMessages(
            email_subject=self._generate_email_subject(context),
            email_body=self._generate_email_body(context),
            linkedin_message=self._generate_linkedin(context),
            whatsapp_message=self._generate_whatsapp(context),
            cold_call_script=self._generate_cold_call(context),
        )

        return FinalLead(scored_lead=scored_lead, outreach=outreach)

    def _generate_email_subject(self, context: dict) -> str:
        """Generate email subject line."""
        try:
            prompt = self.email_subject_prompt.format(**context)
            return self.llm.generate(prompt, max_tokens=60, temperature=0.7)
        except Exception as e:
            logger.warning("email_subject_failed", error=str(e))
            return f"Partnership opportunity for {context['business_name']}"

    def _generate_email_body(self, context: dict) -> str:
        """Generate email body."""
        try:
            prompt = self.email_outreach_prompt.format(**context)
            return self.llm.generate(prompt, max_tokens=300, temperature=0.7)
        except Exception as e:
            logger.warning("email_body_failed", error=str(e))
            return self._fallback_email(context)

    def _generate_linkedin(self, context: dict) -> str:
        """Generate LinkedIn connection message."""
        try:
            prompt = self.linkedin_message_prompt.format(**context)
            message = self.llm.generate(prompt, max_tokens=150, temperature=0.7)
            # Ensure under 300 char limit
            if len(message) > 300:
                message = message[:297] + "..."
            return message
        except Exception as e:
            logger.warning("linkedin_failed", error=str(e))
            return self._fallback_linkedin(context)

    def _generate_whatsapp(self, context: dict) -> str:
        """Generate WhatsApp message."""
        try:
            prompt = self.whatsapp_message_prompt.format(**context)
            return self.llm.generate(prompt, max_tokens=200, temperature=0.7)
        except Exception as e:
            logger.warning("whatsapp_failed", error=str(e))
            return self._fallback_whatsapp(context)

    def _generate_cold_call(self, context: dict) -> str:
        """Generate cold call script."""
        try:
            prompt = self.cold_call_script_prompt.format(**context)
            return self.llm.generate(prompt, max_tokens=400, temperature=0.7)
        except Exception as e:
            logger.warning("cold_call_failed", error=str(e))
            return self._fallback_cold_call(context)

    def _fallback_email(self, context: dict) -> str:
        """Fallback email template."""
        return f"""Hi,

I came across {context['business_name']} and was impressed by your presence in the {context['category']} space.

I'd love to discuss how we might be able to help you reach more customers and grow your business.

Would you be open to a brief conversation this week?

Best regards"""

    def _fallback_linkedin(self, context: dict) -> str:
        """Fallback LinkedIn message."""
        return f"Hi! I noticed {context['business_name']} and would love to connect. I help {context['category']} businesses grow their customer base."

    def _fallback_whatsapp(self, context: dict) -> str:
        """Fallback WhatsApp message."""
        return f"Hi! I saw {context['business_name']} has great reviews. Quick question - are you looking to reach more customers in your area?"

    def _fallback_cold_call(self, context: dict) -> str:
        """Fallback cold call script."""
        return f"""Hi, this is [Your Name] from [Company].

[PAUSE]

I'm reaching out to {context['business_name']}. Am I speaking with the owner or manager?

[PAUSE]

Great! I noticed you have excellent reviews on Google. I help {context['category']} businesses like yours attract more customers through digital marketing.

[PAUSE]

Would you have 5 minutes this week to discuss how we might help you grow?"""

    def generate_batch(
        self,
        scored_leads: list[ScoredLead],
    ) -> list[FinalLead]:
        """Generate outreach for multiple leads.

        Args:
            scored_leads: List of ScoredLead objects.

        Returns:
            List of FinalLead objects.
        """
        results = []
        for lead in scored_leads:
            try:
                final_lead = self.generate(lead)
                results.append(final_lead)
            except Exception as e:
                logger.error(
                    "outreach_generation_failed",
                    name=lead.lead.raw.name,
                    error=str(e),
                )
                # Create lead without outreach on failure
                results.append(FinalLead(scored_lead=lead))

        return results
