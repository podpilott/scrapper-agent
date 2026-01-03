"""Response schemas for the API."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class JobProgress(BaseModel):
    """Progress information for a running job."""

    step: str = Field(..., description="Current step name")
    current: int = Field(..., description="Current item number")
    total: int = Field(..., description="Total items to process")
    message: str | None = Field(None, description="Human-readable progress message")


class DuplicateInfo(BaseModel):
    """Information about a duplicate lead."""

    name: str
    job_id: str


class JobSummary(BaseModel):
    """Summary of completed job results."""

    total_leads: int = 0
    hot: int = 0
    warm: int = 0
    cold: int = 0
    duration_seconds: float | None = None
    # Deduplication info
    total_scraped: int = 0  # Total leads found from Google Maps
    duplicates_skipped: int = 0  # Number of leads skipped due to deduplication
    duplicate_jobs: list[str] = []  # Job IDs that contain the duplicates


class JobCreatedResponse(BaseModel):
    """Response when a job is created."""

    job_id: str
    status: str = "pending"
    websocket_url: str = Field(..., description="WebSocket URL for real-time updates")


class JobStatusResponse(BaseModel):
    """Response for job status query."""

    job_id: str
    status: Literal["pending", "running", "completed", "failed", "cancelled"]
    query: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    progress: JobProgress | None = None
    summary: JobSummary | None = None
    error: str | None = None
    # Job configuration for retry functionality
    max_results: int | None = None
    min_score: int | None = None
    skip_enrichment: bool | None = None
    skip_outreach: bool | None = None
    product_context: str | None = None


class LeadResponse(BaseModel):
    """Response for a single lead."""

    id: str | None = None  # Lead ID for research endpoint
    name: str
    phone: str | None = None
    email: str | None = None
    whatsapp: str | None = None
    website: str | None = None
    address: str | None = None
    category: str | None = None
    rating: float | None = None
    review_count: int = 0
    score: float = 0
    tier: str | None = None
    owner_name: str | None = None
    linkedin: str | None = None
    facebook: str | None = None
    instagram: str | None = None
    maps_url: str | None = None
    # Enhanced fields
    place_id: str | None = None
    price_level: str | None = None
    photos_count: int = 0
    is_claimed: bool | None = None
    years_in_business: int | None = None
    outreach: dict[str, Any] | None = None
    research: dict[str, Any] | None = None  # LLM-generated research brief


class JobListResponse(BaseModel):
    """Response for listing jobs."""

    jobs: list[JobStatusResponse]
    total: int


class WebSocketMessage(BaseModel):
    """Base WebSocket message."""

    type: Literal["status", "lead", "error", "complete"]
    data: dict[str, Any] | None = None
    message: str | None = None


class SimilarJob(BaseModel):
    """A similar job from user's history."""

    job_id: str
    query: str
    total_leads: int = 0
    created_at: str
    match_type: Literal["exact", "contains", "similar"]


class DuplicateCheckResponse(BaseModel):
    """Response for duplicate query check."""

    has_duplicates: bool = False
    similar_jobs: list[SimilarJob] = []
    suggestions: list[str] = []  # LLM-generated alternative queries
    message: str | None = None


class LeadResearch(BaseModel):
    """LLM-generated research brief for a lead."""

    overview: str  # 2-3 sentence business overview
    pain_points: list[str] = []  # 3-5 potential pain points
    opportunities: list[str] = []  # 2-3 reasons they might need user's product
    talking_points: list[str] = []  # 2-3 conversation starters
    generated_at: str  # ISO timestamp


class LeadResearchResponse(BaseModel):
    """Response for lead research generation."""

    lead_id: str
    research: LeadResearch
    cached: bool = False  # Was this from cache?
