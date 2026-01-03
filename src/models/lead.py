"""Lead data models using Pydantic."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class SocialLinks(BaseModel):
    """Social media links for a business."""

    linkedin: str | None = None
    facebook: str | None = None
    instagram: str | None = None
    twitter: str | None = None
    youtube: str | None = None
    tiktok: str | None = None


class CompanyIntelligence(BaseModel):
    """Company intelligence data from web search."""

    employee_count: int | None = None
    founded_year: int | None = None
    recent_news: list[str] = Field(default_factory=list)
    company_description: str | None = None
    industry: str | None = None
    source_urls: list[str] = Field(default_factory=list)
    enriched_at: datetime | None = None


class DiscoveredContact(BaseModel):
    """Contact information discovered via search."""

    name: str
    role: str | None = None
    email: str | None = None
    linkedin_url: str | None = None
    source: str | None = None  # Where we found this contact


class LeadAnalysis(BaseModel):
    """LLM-powered lead analysis and insights."""

    fit_score: int = Field(default=0, ge=0, le=100)  # How well lead matches ICP
    fit_reasoning: str | None = None
    pain_points: list[str] = Field(default_factory=list)
    personalization_hooks: list[str] = Field(default_factory=list)  # Key talking points
    potential_challenges: list[str] = Field(default_factory=list)
    recommended_approach: str | None = None
    analyzed_at: datetime | None = None


class RawLead(BaseModel):
    """Raw business data scraped from Google Maps."""

    # Identifiers
    place_id: str = Field(..., description="Google Maps place ID")

    # Core fields
    name: str
    phone: str | None = None
    website: str | None = None

    # Location
    address: str
    latitude: float | None = None
    longitude: float | None = None

    # Classification
    category: str
    categories: list[str] = Field(default_factory=list)

    # Ratings & Reviews
    rating: float | None = Field(None, ge=0, le=5)
    review_count: int = 0
    price_level: str | None = None  # $, $$, $$$, $$$$

    # Business Signals (Enhanced)
    business_hours: dict[str, str] | None = None  # {"Monday": "9AM-5PM", ...}
    is_open_now: bool | None = None
    photos_count: int = 0
    is_claimed: bool | None = None
    years_in_business: int | None = None

    # Metadata
    scraped_at: datetime = Field(default_factory=datetime.utcnow)
    search_query: str
    maps_url: str


class EnrichedLead(BaseModel):
    """Lead enriched with website data and company intelligence."""

    # Original data
    raw: RawLead

    # Extracted emails
    emails: list[str] = Field(default_factory=list)
    primary_email: str | None = None

    # Social media
    social_links: SocialLinks = Field(default_factory=SocialLinks)

    # Contact information
    owner_name: str | None = None
    contact_names: list[str] = Field(default_factory=list)

    # WhatsApp (derived from phone)
    whatsapp: str | None = None

    # Website signals
    has_contact_form: bool = False
    website_reachable: bool = True

    # Team/Owner information (Enhanced)
    team_members: list[dict] = Field(default_factory=list)
    # [{"name": "John", "role": "CEO", "email": "...", "linkedin": "..."}]
    structured_data: dict | None = None  # JSON-LD data from website

    # NEW: Company intelligence from web search
    company_intel: CompanyIntelligence = Field(default_factory=CompanyIntelligence)

    # NEW: Discovered contacts from web search
    discovered_contacts: list[DiscoveredContact] = Field(default_factory=list)

    # NEW: LLM analysis
    analysis: LeadAnalysis = Field(default_factory=LeadAnalysis)

    # Metadata
    enriched_at: datetime = Field(default_factory=datetime.utcnow)


class LeadScore(BaseModel):
    """Detailed scoring breakdown for a lead."""

    rating_score: float = Field(0, ge=0, le=25)
    review_score: float = Field(0, ge=0, le=25)
    completeness_score: float = Field(0, ge=0, le=25)
    social_presence_score: float = Field(0, ge=0, le=25)
    business_signals_score: float = Field(0, ge=0, le=25)  # NEW: photos, hours, claimed, etc.

    @property
    def total(self) -> float:
        """Total score out of 100 (normalized from 125 max)."""
        raw_total = (
            self.rating_score
            + self.review_score
            + self.completeness_score
            + self.social_presence_score
            + self.business_signals_score
        )
        # Normalize from 125 max to 100
        return min(raw_total * 100 / 125, 100.0)

    @property
    def tier(self) -> Literal["hot", "warm", "cold"]:
        """Lead quality tier based on total score."""
        if self.total >= 75:
            return "hot"
        elif self.total >= 50:
            return "warm"
        else:
            return "cold"


class ScoredLead(BaseModel):
    """Lead with quality scoring."""

    # Enriched data
    lead: EnrichedLead

    # Scoring
    score: LeadScore

    # Convenience properties are computed
    @property
    def total_score(self) -> float:
        return self.score.total

    @property
    def tier(self) -> str:
        return self.score.tier


class OutreachMessages(BaseModel):
    """Generated outreach messages for all channels."""

    email_subject: str | None = None
    email_body: str | None = None
    linkedin_message: str | None = None
    whatsapp_message: str | None = None
    cold_call_script: str | None = None


class FinalLead(BaseModel):
    """Final lead with all data and outreach messages."""

    # All lead data
    scored_lead: ScoredLead

    # Generated outreach
    outreach: OutreachMessages = Field(default_factory=OutreachMessages)

    # Metadata
    processed_at: datetime = Field(default_factory=datetime.utcnow)

    # Convenience accessors
    @property
    def name(self) -> str:
        return self.scored_lead.lead.raw.name

    @property
    def phone(self) -> str | None:
        return self.scored_lead.lead.raw.phone

    @property
    def email(self) -> str | None:
        return self.scored_lead.lead.primary_email

    @property
    def website(self) -> str | None:
        return self.scored_lead.lead.raw.website

    @property
    def address(self) -> str:
        return self.scored_lead.lead.raw.address

    @property
    def category(self) -> str:
        return self.scored_lead.lead.raw.category

    @property
    def rating(self) -> float | None:
        return self.scored_lead.lead.raw.rating

    @property
    def review_count(self) -> int:
        return self.scored_lead.lead.raw.review_count

    @property
    def whatsapp(self) -> str | None:
        return self.scored_lead.lead.whatsapp

    @property
    def score(self) -> float:
        return self.scored_lead.total_score

    @property
    def tier(self) -> str:
        return self.scored_lead.tier

    @property
    def linkedin(self) -> str | None:
        return self.scored_lead.lead.social_links.linkedin

    @property
    def owner_name(self) -> str | None:
        return self.scored_lead.lead.owner_name

    def to_flat_dict(self) -> dict:
        """Convert to flat dictionary for CSV export."""
        raw = self.scored_lead.lead.raw
        enriched = self.scored_lead.lead
        intel = enriched.company_intel
        analysis = enriched.analysis

        return {
            "name": self.name,
            "phone": self.phone or "",
            "email": self.email or "",
            "whatsapp": self.whatsapp or "",
            "website": self.website or "",
            "address": self.address,
            "category": self.category,
            "rating": self.rating or "",
            "review_count": self.review_count,
            "score": round(self.score, 1),
            "tier": self.tier,
            "owner_name": self.owner_name or "",
            "linkedin": self.linkedin or "",
            "facebook": self.scored_lead.lead.social_links.facebook or "",
            "instagram": self.scored_lead.lead.social_links.instagram or "",
            "maps_url": self.scored_lead.lead.raw.maps_url,
            # Enhanced data
            "place_id": raw.place_id,
            "price_level": raw.price_level or "",
            "photos_count": raw.photos_count,
            "is_claimed": raw.is_claimed,
            "years_in_business": raw.years_in_business or "",
            # Company intelligence
            "employee_count": intel.employee_count or "",
            "founded_year": intel.founded_year or "",
            "company_description": intel.company_description or "",
            "recent_news": "; ".join(intel.recent_news[:3]) if intel.recent_news else "",
            # Lead analysis
            "fit_score": analysis.fit_score,
            "pain_points": "; ".join(analysis.pain_points[:3]) if analysis.pain_points else "",
            "personalization_hooks": "; ".join(analysis.personalization_hooks[:3]) if analysis.personalization_hooks else "",
            # Outreach
            "email_subject": self.outreach.email_subject or "",
            "email_body": self.outreach.email_body or "",
            "linkedin_message": self.outreach.linkedin_message or "",
            "whatsapp_message": self.outreach.whatsapp_message or "",
            "cold_call_script": self.outreach.cold_call_script or "",
        }
