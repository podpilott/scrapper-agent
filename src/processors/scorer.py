"""Lead scoring engine."""

from config.settings import settings
from src.models.lead import EnrichedLead, LeadScore, ScoredLead
from src.utils.logger import get_logger

logger = get_logger("scorer")


class LeadScorer:
    """Score leads based on multiple quality factors."""

    def __init__(
        self,
        hot_threshold: int | None = None,
        warm_threshold: int | None = None,
    ):
        """Initialize the scorer.

        Args:
            hot_threshold: Minimum score for "hot" tier. Defaults to settings.
            warm_threshold: Minimum score for "warm" tier. Defaults to settings.
        """
        self.hot_threshold = hot_threshold or settings.hot_lead_threshold
        self.warm_threshold = warm_threshold or settings.warm_lead_threshold

    def score(self, lead: EnrichedLead) -> ScoredLead:
        """Score an enriched lead.

        Args:
            lead: EnrichedLead to score.

        Returns:
            ScoredLead with quality scoring.
        """
        rating_score = self._score_rating(lead)
        review_score = self._score_reviews(lead)
        completeness_score = self._score_completeness(lead)
        social_score = self._score_social_presence(lead)
        business_signals_score = self._score_business_signals(lead)

        score = LeadScore(
            rating_score=rating_score,
            review_score=review_score,
            completeness_score=completeness_score,
            social_presence_score=social_score,
            business_signals_score=business_signals_score,
        )

        scored_lead = ScoredLead(lead=lead, score=score)

        logger.debug(
            "lead_scored",
            name=lead.raw.name,
            total=score.total,
            tier=score.tier,
        )

        return scored_lead

    def _score_rating(self, lead: EnrichedLead) -> float:
        """Score based on Google rating (0-25 points).

        Scoring:
        - 4.5+ : 25 points
        - 4.0-4.5: 20 points
        - 3.5-4.0: 15 points
        - 3.0-3.5: 10 points
        - Below 3.0: 5 points
        - No rating: 0 points
        """
        rating = lead.raw.rating
        if rating is None:
            return 0.0

        if rating >= 4.5:
            return 25.0
        elif rating >= 4.0:
            return 20.0
        elif rating >= 3.5:
            return 15.0
        elif rating >= 3.0:
            return 10.0
        else:
            return 5.0

    def _score_reviews(self, lead: EnrichedLead) -> float:
        """Score based on review count (0-25 points).

        Scoring:
        - 100+ reviews: 25 points
        - 50-99 reviews: 20 points
        - 20-49 reviews: 15 points
        - 5-19 reviews: 10 points
        - 1-4 reviews: 5 points
        - 0 reviews: 0 points
        """
        review_count = lead.raw.review_count

        if review_count >= 100:
            return 25.0
        elif review_count >= 50:
            return 20.0
        elif review_count >= 20:
            return 15.0
        elif review_count >= 5:
            return 10.0
        elif review_count >= 1:
            return 5.0
        else:
            return 0.0

    def _score_completeness(self, lead: EnrichedLead) -> float:
        """Score based on data completeness (0-25 points).

        Points for:
        - Phone: 5 points
        - Website: 5 points
        - Email: 8 points
        - Owner name: 7 points
        """
        score = 0.0

        if lead.raw.phone:
            score += 5.0

        if lead.raw.website:
            score += 5.0

        if lead.emails or lead.primary_email:
            score += 8.0

        if lead.owner_name:
            score += 7.0

        return min(score, 25.0)

    def _score_social_presence(self, lead: EnrichedLead) -> float:
        """Score based on social media presence (0-25 points).

        Points for each platform:
        - LinkedIn: 8 points (most valuable for B2B)
        - Instagram: 6 points
        - Facebook: 5 points
        - Twitter/X: 3 points
        - YouTube: 2 points
        - TikTok: 1 point
        """
        score = 0.0
        social = lead.social_links

        if social.linkedin:
            score += 8.0
        if social.instagram:
            score += 6.0
        if social.facebook:
            score += 5.0
        if social.twitter:
            score += 3.0
        if social.youtube:
            score += 2.0
        if social.tiktok:
            score += 1.0

        return min(score, 25.0)

    def _score_business_signals(self, lead: EnrichedLead) -> float:
        """Score based on business quality signals (0-25 points).

        Points for:
        - Photos: 5 points (20+ = 5, 10+ = 3, 1+ = 1)
        - Business hours: 3 points
        - Price level: 2 points
        - Claimed status: 5 points (not available with SerpAPI)
        - Website quality: 5 points (reachable + SSL + contact form)
        - Team info: 5 points
        """
        score = 0.0
        raw = lead.raw

        # Photos (max 5 points) - may be 0 with SerpAPI
        if raw.photos_count >= 20:
            score += 5.0
        elif raw.photos_count >= 10:
            score += 3.0
        elif raw.photos_count >= 1:
            score += 1.0

        # Business hours (3 points)
        if raw.business_hours:
            score += 3.0

        # Price level (2 points)
        if raw.price_level:
            score += 2.0

        # Claimed status (5 points) - not available with SerpAPI, gracefully skip
        if raw.is_claimed is True:
            score += 5.0

        # Website quality (5 points)
        if lead.website_reachable:
            score += 2.0
        if lead.has_contact_form:
            score += 1.0
        if raw.website and raw.website.startswith("https"):
            score += 2.0

        # Team info (5 points)
        if lead.team_members:
            score += 5.0

        return min(score, 25.0)

    def score_batch(self, leads: list[EnrichedLead]) -> list[ScoredLead]:
        """Score multiple leads.

        Args:
            leads: List of EnrichedLead objects.

        Returns:
            List of ScoredLead objects.
        """
        return [self.score(lead) for lead in leads]

    def filter_by_tier(
        self,
        leads: list[ScoredLead],
        tiers: list[str] | None = None,
    ) -> list[ScoredLead]:
        """Filter leads by quality tier.

        Args:
            leads: List of ScoredLead objects.
            tiers: List of tiers to include. Defaults to ["hot", "warm"].

        Returns:
            Filtered list of leads.
        """
        if tiers is None:
            tiers = ["hot", "warm"]

        return [lead for lead in leads if lead.tier in tiers]

    def filter_by_min_score(
        self,
        leads: list[ScoredLead],
        min_score: int | None = None,
    ) -> list[ScoredLead]:
        """Filter leads by minimum score.

        Args:
            leads: List of ScoredLead objects.
            min_score: Minimum score threshold. Defaults to settings value.

        Returns:
            Filtered list of leads.
        """
        if min_score is None:
            min_score = settings.min_score_for_outreach

        return [lead for lead in leads if lead.total_score >= min_score]
