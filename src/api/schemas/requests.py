"""Request schemas for the API."""

from pydantic import BaseModel, Field


class ScrapeRequest(BaseModel):
    """Request body for starting a scrape job."""

    query: str = Field(..., description="Search query (e.g., 'coffee shops in Tokyo')")
    max_results: int = Field(
        default=20,
        ge=1,
        le=50,
        description="Maximum number of leads to scrape",
    )
    min_score: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Minimum score for qualified leads",
    )
    skip_enrichment: bool = Field(
        default=False,
        description="Skip website enrichment (faster, less data)",
    )
    skip_outreach: bool = Field(
        default=False,
        description="Skip outreach message generation (no LLM calls)",
    )
    product_context: str | None = Field(
        default=None,
        description="Description of your product/service for personalized outreach",
    )
    language: str = Field(
        default="en",
        description="Language for AI-generated outreach messages (en=English, id=Indonesian)",
        pattern="^(en|id)$",
    )
