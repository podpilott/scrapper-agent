"""Database service for Supabase PostgreSQL operations."""

from datetime import datetime
from typing import Any

from supabase import Client, create_client

from config.settings import settings
from src.api.schemas.responses import JobSummary
from src.utils.logger import get_logger

logger = get_logger("database")


class DatabaseService:
    """Service for database operations using Supabase."""

    def __init__(self):
        self._client: Client | None = None

    @property
    def client(self) -> Client:
        """Get or create Supabase client."""
        if self._client is None:
            if not settings.supabase_url or not settings.supabase_service_role_key:
                raise ValueError(
                    "Supabase URL and service role key are required for database operations"
                )
            self._client = create_client(
                settings.supabase_url,
                settings.supabase_service_role_key.get_secret_value(),
            )
        return self._client

    def is_configured(self) -> bool:
        """Check if database is configured."""
        return bool(settings.supabase_url and settings.supabase_service_role_key)

    # ============== Job Operations ==============

    def create_job(
        self,
        job_id: str,
        user_id: str,
        query: str,
        max_results: int = 20,
        min_score: int = 0,
        skip_enrichment: bool = False,
        skip_outreach: bool = False,
        product_context: str | None = None,
    ) -> dict[str, Any]:
        """Create a new job in the database."""
        data = {
            "job_id": job_id,
            "user_id": user_id,
            "query": query,
            "status": "pending",
            "max_results": max_results,
            "min_score": min_score,
            "skip_enrichment": skip_enrichment,
            "skip_outreach": skip_outreach,
            "product_context": product_context,
        }
        result = self.client.table("jobs").insert(data).execute()
        logger.info("job_created_in_db", job_id=job_id, user_id=user_id)
        return result.data[0] if result.data else {}

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        """Get a job by ID."""
        try:
            result = (
                self.client.table("jobs")
                .select("*")
                .eq("job_id", job_id)
                .limit(1)
                .execute()
            )
            if result.data:
                return result.data[0]
            return None
        except Exception as e:
            logger.error("get_job_failed", job_id=job_id, error=str(e))
            return None

    def get_jobs_for_user(self, user_id: str) -> list[dict[str, Any]]:
        """Get all jobs for a user."""
        result = (
            self.client.table("jobs")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return result.data or []

    def update_job_status(
        self,
        job_id: str,
        status: str,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        """Update job status."""
        data: dict[str, Any] = {"status": status}
        if started_at:
            data["started_at"] = started_at.isoformat()
        if completed_at:
            data["completed_at"] = completed_at.isoformat()

        self.client.table("jobs").update(data).eq("job_id", job_id).execute()
        logger.info("job_status_updated_in_db", job_id=job_id, status=status)

    def update_job_progress(
        self,
        job_id: str,
        step: str,
        current: int,
        total: int,
        message: str | None = None,
    ) -> None:
        """Update job progress."""
        progress_data = {
            "step": step,
            "current": current,
            "total": total,
            "message": message,
        }
        data = {"progress": progress_data}
        self.client.table("jobs").update(data).eq("job_id", job_id).execute()

    def complete_job(self, job_id: str, summary: JobSummary) -> None:
        """Mark job as completed with summary."""
        data = {
            "status": "completed",
            "completed_at": datetime.utcnow().isoformat(),
            "summary": summary.model_dump(),
        }
        self.client.table("jobs").update(data).eq("job_id", job_id).execute()
        logger.info("job_completed_in_db", job_id=job_id)

    def fail_job(self, job_id: str, error: str) -> None:
        """Mark job as failed with error message."""
        data = {
            "status": "failed",
            "completed_at": datetime.utcnow().isoformat(),
            "error": error,
        }
        self.client.table("jobs").update(data).eq("job_id", job_id).execute()
        logger.error("job_failed_in_db", job_id=job_id, error=error)

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a job."""
        # First check if job exists and is cancellable
        job = self.get_job(job_id)
        if not job or job["status"] not in ("pending", "running"):
            return False

        data = {
            "status": "cancelled",
            "completed_at": datetime.utcnow().isoformat(),
        }
        self.client.table("jobs").update(data).eq("job_id", job_id).execute()
        logger.info("job_cancelled_in_db", job_id=job_id)
        return True

    # ============== Lead Operations ==============

    def check_lead_exists(
        self,
        user_id: str,
        place_id: str | None = None,
        phone: str | None = None,
    ) -> dict[str, Any] | None:
        """Check if lead already exists for user (cross-job deduplication).

        Args:
            user_id: User ID to check against.
            place_id: Google Maps place ID (most reliable).
            phone: Phone number (fallback).

        Returns:
            Existing lead data if found, None otherwise.
        """
        try:
            # First try by place_id (most reliable)
            if place_id and place_id != "unknown":
                result = (
                    self.client.table("leads")
                    .select("job_id, name, created_at")
                    .eq("user_id", user_id)
                    .eq("place_id", place_id)
                    .limit(1)
                    .execute()
                )
                if result.data:
                    logger.debug(
                        "duplicate_found_by_place_id",
                        place_id=place_id,
                        existing_job=result.data[0].get("job_id"),
                    )
                    return result.data[0]

            # Fallback to phone (normalize first)
            if phone:
                # Normalize phone for comparison (strip non-digits)
                import re
                normalized_phone = re.sub(r"[^\d]", "", phone)
                if len(normalized_phone) >= 8:
                    result = (
                        self.client.table("leads")
                        .select("job_id, name, created_at")
                        .eq("user_id", user_id)
                        .eq("phone", phone)
                        .limit(1)
                        .execute()
                    )
                    if result.data:
                        logger.debug(
                            "duplicate_found_by_phone",
                            phone=phone[:4] + "****",
                            existing_job=result.data[0].get("job_id"),
                        )
                        return result.data[0]

        except Exception as e:
            logger.warning("check_lead_exists_failed", error=str(e))

        return None

    def add_lead(
        self,
        job_id: str,
        user_id: str,
        lead_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Add a lead to the database."""
        # Helper to convert empty strings to None for nullable fields
        def clean_value(value, default=None):
            if value == "" or value is None:
                return default
            return value

        # Helper for integer fields - convert empty strings to default int
        def clean_int(value, default=0):
            if value == "" or value is None:
                return default
            try:
                return int(value)
            except (ValueError, TypeError):
                return default

        data = {
            "job_id": job_id,
            "user_id": user_id,
            "name": lead_data.get("name", ""),
            "phone": clean_value(lead_data.get("phone")),
            "email": clean_value(lead_data.get("email")),
            "whatsapp": clean_value(lead_data.get("whatsapp")),
            "website": clean_value(lead_data.get("website")),
            "address": clean_value(lead_data.get("address")),
            "category": clean_value(lead_data.get("category")),
            "rating": clean_value(lead_data.get("rating")),
            "review_count": clean_int(lead_data.get("review_count"), 0),
            "score": clean_value(lead_data.get("score"), 0),
            "tier": clean_value(lead_data.get("tier")),
            "owner_name": clean_value(lead_data.get("owner_name")),
            "linkedin": clean_value(lead_data.get("linkedin")),
            "facebook": clean_value(lead_data.get("facebook")),
            "instagram": clean_value(lead_data.get("instagram")),
            "maps_url": clean_value(lead_data.get("maps_url")),
            # Enhanced fields for deduplication and enrichment
            "place_id": clean_value(lead_data.get("place_id")),
            "price_level": clean_value(lead_data.get("price_level")),
            "photos_count": clean_int(lead_data.get("photos_count"), 0),
            "is_claimed": clean_value(lead_data.get("is_claimed")),
            "years_in_business": clean_int(lead_data.get("years_in_business"), None),
            "outreach": {
                "email_subject": clean_value(lead_data.get("email_subject")),
                "email_body": clean_value(lead_data.get("email_body")),
                "linkedin_message": clean_value(lead_data.get("linkedin_message")),
                "whatsapp_message": clean_value(lead_data.get("whatsapp_message")),
                "cold_call_script": clean_value(lead_data.get("cold_call_script")),
            } if any([
                lead_data.get("email_subject"),
                lead_data.get("whatsapp_message"),
                lead_data.get("linkedin_message"),
            ]) else None,
            "raw_data": lead_data,
        }
        result = self.client.table("leads").insert(data).execute()
        return result.data[0] if result.data else {}

    def get_leads_for_job(self, job_id: str) -> list[dict[str, Any]]:
        """Get all leads for a job."""
        result = (
            self.client.table("leads")
            .select("*")
            .eq("job_id", job_id)
            .order("created_at", desc=False)
            .execute()
        )
        return result.data or []

    def get_leads_for_user(self, user_id: str) -> list[dict[str, Any]]:
        """Get all leads for a user."""
        result = (
            self.client.table("leads")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return result.data or []

    # ============== Demo Operations ==============

    def get_demo_leads(self) -> list[dict[str, Any]]:
        """Get public demo leads."""
        result = self.client.table("demo_leads").select("*").limit(10).execute()
        return result.data or []


# Global database service instance
db_service = DatabaseService()
