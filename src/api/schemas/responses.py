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


class JobSummary(BaseModel):
    """Summary of completed job results."""

    total_leads: int = 0
    hot: int = 0
    warm: int = 0
    cold: int = 0
    duration_seconds: float | None = None


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


class JobListResponse(BaseModel):
    """Response for listing jobs."""

    jobs: list[JobStatusResponse]
    total: int


class WebSocketMessage(BaseModel):
    """Base WebSocket message."""

    type: Literal["status", "lead", "error", "complete"]
    data: dict[str, Any] | None = None
    message: str | None = None
