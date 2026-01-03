"""Database service for Supabase PostgreSQL operations."""

from datetime import datetime, timedelta, timezone
from typing import Any

from supabase import Client, create_client


def format_ban_remaining(expires_at_str: str | None) -> str:
    """Format remaining ban time in a human-readable way.

    Args:
        expires_at_str: ISO format expiry timestamp.

    Returns:
        Human-readable string like "45 minutes", "3 hours", "2 days".
    """
    if not expires_at_str:
        return "indefinitely"

    try:
        expiry = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
        remaining = expiry - datetime.now(timezone.utc)

        if remaining.total_seconds() <= 0:
            return "soon"

        total_minutes = int(remaining.total_seconds() / 60)
        total_hours = int(remaining.total_seconds() / 3600)
        total_days = int(remaining.total_seconds() / 86400)

        if total_days >= 1:
            return f"{total_days} day{'s' if total_days != 1 else ''}"
        elif total_hours >= 1:
            return f"{total_hours} hour{'s' if total_hours != 1 else ''}"
        elif total_minutes >= 1:
            return f"{total_minutes} minute{'s' if total_minutes != 1 else ''}"
        else:
            return "less than a minute"
    except Exception:
        return "some time"

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

    def update_lead(
        self,
        job_id: str,
        place_id: str,
        lead_data: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Update an existing lead with enriched data.

        Args:
            job_id: The job ID the lead belongs to.
            place_id: The place ID to identify the lead.
            lead_data: Updated lead data.

        Returns:
            Updated lead data or None if not found.
        """
        # Helper to convert empty strings to None for nullable fields
        def clean_value(value, default=None):
            if value == "" or value is None:
                return default
            return value

        # Helper for integer fields
        def clean_int(value, default=0):
            if value == "" or value is None:
                return default
            try:
                return int(value)
            except (ValueError, TypeError):
                return default

        data = {
            "email": clean_value(lead_data.get("email")),
            "whatsapp": clean_value(lead_data.get("whatsapp")),
            "score": clean_value(lead_data.get("score"), 0),
            "tier": clean_value(lead_data.get("tier")),
            "owner_name": clean_value(lead_data.get("owner_name")),
            "linkedin": clean_value(lead_data.get("linkedin")),
            "facebook": clean_value(lead_data.get("facebook")),
            "instagram": clean_value(lead_data.get("instagram")),
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

        # Remove None values to avoid overwriting with nulls
        data = {k: v for k, v in data.items() if v is not None}

        try:
            result = (
                self.client.table("leads")
                .update(data)
                .eq("job_id", job_id)
                .eq("place_id", place_id)
                .execute()
            )
            if result.data:
                logger.debug("lead_updated_in_db", job_id=job_id, place_id=place_id)
                return result.data[0]
            return None
        except Exception as e:
            logger.warning("update_lead_failed", job_id=job_id, error=str(e))
            return None

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

    # ============== Query Duplicate Check Operations ==============

    def find_similar_jobs(
        self,
        user_id: str,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Find similar completed jobs for a user.

        Matching strategy:
        1. Exact match (case-insensitive)
        2. Contains match (query contains or is contained by existing)
        3. Word overlap (shared significant words)

        Args:
            user_id: User ID to search for.
            query: Query string to find similar jobs for.
            limit: Maximum number of results to return.

        Returns:
            List of job dicts with: job_id, query, total_leads, created_at, match_type
        """
        try:
            # Get user's completed jobs from last 30 days
            cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat()

            result = (
                self.client.table("jobs")
                .select("job_id, query, created_at, summary")
                .eq("user_id", user_id)
                .eq("status", "completed")
                .gte("created_at", cutoff)
                .order("created_at", desc=True)
                .limit(50)
                .execute()
            )

            jobs = result.data or []
            query_lower = query.lower().strip()
            query_words = set(query_lower.split())

            matches = []
            for job in jobs:
                job_query = job["query"].lower().strip()
                job_words = set(job_query.split())

                # Calculate similarity
                score = 0
                match_type = None

                if query_lower == job_query:
                    score = 100
                    match_type = "exact"
                elif query_lower in job_query or job_query in query_lower:
                    score = 80
                    match_type = "contains"
                else:
                    # Word overlap
                    overlap = len(query_words & job_words)
                    total = len(query_words | job_words)
                    if total > 0 and overlap / total > 0.5:
                        score = int(overlap / total * 60)
                        match_type = "similar"

                if score > 40:
                    summary = job.get("summary") or {}
                    matches.append({
                        "job_id": job["job_id"],
                        "query": job["query"],
                        "total_leads": summary.get("total_leads", 0),
                        "created_at": job["created_at"],
                        "match_type": match_type,
                        "score": score,
                    })

            # Sort by: leads (desc), then score (desc), then date (desc)
            # Prioritize jobs with actual leads over empty ones
            matches.sort(key=lambda x: (-x["total_leads"], -x["score"], x["created_at"]))
            return matches[:limit]

        except Exception as e:
            logger.warning("find_similar_jobs_failed", user_id=user_id, error=str(e))
            return []

    # ============== Demo Operations ==============

    def get_demo_leads(self) -> list[dict[str, Any]]:
        """Get public demo leads."""
        result = self.client.table("demo_leads").select("*").limit(10).execute()
        return result.data or []

    # ============== Ban Operations ==============

    def is_user_banned(self, user_id: str) -> bool:
        """Check if user is banned.

        Args:
            user_id: The user ID to check.

        Returns:
            True if user is banned and ban is active, False otherwise.
        """
        ban_info = self.get_user_ban_info(user_id)
        return ban_info is not None

    def get_user_ban_info(self, user_id: str) -> dict[str, Any] | None:
        """Get ban information for a user.

        Args:
            user_id: The user ID to check.

        Returns:
            Ban info dict with 'reason', 'expires_at' if banned, None otherwise.
        """
        try:
            result = (
                self.client.table("banned_users")
                .select("id, reason, expires_at")
                .eq("user_id", user_id)
                .eq("is_active", True)
                .limit(1)
                .execute()
            )
            if not result.data:
                return None

            # Check if ban has expired
            ban = result.data[0]
            expires_at = ban.get("expires_at")
            if expires_at:
                expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) > expiry:
                    # Ban expired, deactivate it
                    self.client.table("banned_users").update(
                        {"is_active": False}
                    ).eq("id", ban["id"]).execute()
                    return None

            return {
                "reason": ban.get("reason"),
                "expires_at": expires_at,
            }
        except Exception as e:
            logger.warning("ban_check_failed", user_id=user_id, error=str(e))
            return None  # Fail open - don't block on error

    def ban_user(
        self,
        user_id: str,
        reason: str,
        banned_by: str | None = None,
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Ban a user.

        Args:
            user_id: The user ID to ban.
            reason: Reason for the ban.
            banned_by: Admin user ID who issued the ban.
            expires_at: Optional expiration time for the ban.

        Returns:
            The created ban record.
        """
        data = {
            "user_id": user_id,
            "reason": reason,
            "banned_by": banned_by,
            "is_active": True,
        }
        if expires_at:
            data["expires_at"] = expires_at.isoformat()

        result = self.client.table("banned_users").insert(data).execute()
        logger.info("user_banned", user_id=user_id, reason=reason)
        return result.data[0] if result.data else {}

    def unban_user(self, user_id: str) -> bool:
        """Unban a user.

        Args:
            user_id: The user ID to unban.

        Returns:
            True if user was unbanned, False if no active ban found.
        """
        result = (
            self.client.table("banned_users")
            .update({"is_active": False})
            .eq("user_id", user_id)
            .eq("is_active", True)
            .execute()
        )
        if result.data:
            logger.info("user_unbanned", user_id=user_id)
            return True
        return False

    # ============== Rate Limit Violation Operations ==============

    def record_rate_limit_violation(self, user_id: str, endpoint: str) -> None:
        """Record a rate limit violation for a user.

        Args:
            user_id: The user who hit the rate limit.
            endpoint: The API endpoint that was rate limited.
        """
        try:
            self.client.table("rate_limit_violations").insert({
                "user_id": user_id,
                "endpoint": endpoint,
            }).execute()
            logger.debug("violation_recorded", user_id=user_id, endpoint=endpoint)
        except Exception as e:
            logger.warning("record_violation_failed", user_id=user_id, error=str(e))

    def get_violation_count(self, user_id: str, hours: int = 24) -> int:
        """Count rate limit violations in the last N hours.

        Args:
            user_id: The user ID to check.
            hours: Time window in hours (default 24).

        Returns:
            Number of violations in the time window.
        """
        try:
            since = datetime.now(timezone.utc) - timedelta(hours=hours)
            result = (
                self.client.table("rate_limit_violations")
                .select("id", count="exact")
                .eq("user_id", user_id)
                .gte("created_at", since.isoformat())
                .execute()
            )
            return result.count or 0
        except Exception as e:
            logger.warning("get_violation_count_failed", user_id=user_id, error=str(e))
            return 0

    def check_and_auto_ban(self, user_id: str) -> bool:
        """Check violation count and auto-ban if threshold exceeded.

        Progressive thresholds:
        - 30+ violations in 24h: 1 hour ban
        - 60+ violations in 24h: 6 hour ban
        - 120+ violations in 24h: 24 hour ban
        - 200+ violations in 24h: 7 day ban

        Args:
            user_id: The user ID to check.

        Returns:
            True if user was banned, False otherwise.
        """
        try:
            # Skip if already banned
            if self.is_user_banned(user_id):
                return False

            count_24h = self.get_violation_count(user_id, hours=24)

            # Progressive thresholds
            if count_24h >= 200:
                ban_hours = 24 * 7  # 7 days
                reason = "Severe rate limit abuse (200+ violations in 24h)"
            elif count_24h >= 120:
                ban_hours = 24  # 24 hours
                reason = "Heavy rate limit abuse (120+ violations in 24h)"
            elif count_24h >= 60:
                ban_hours = 6  # 6 hours
                reason = "Moderate rate limit abuse (60+ violations in 24h)"
            elif count_24h >= 30:
                ban_hours = 1  # 1 hour
                reason = "Rate limit abuse (30+ violations in 24h)"
            else:
                return False  # Below threshold

            expires_at = datetime.now(timezone.utc) + timedelta(hours=ban_hours)
            self.ban_user(user_id, reason, expires_at=expires_at)
            logger.warning(
                "auto_ban_triggered",
                user_id=user_id,
                violations=count_24h,
                ban_hours=ban_hours,
            )
            return True
        except Exception as e:
            logger.error("auto_ban_check_failed", user_id=user_id, error=str(e))
            return False

    def cleanup_old_violations(self, days: int = 7) -> int:
        """Delete violations older than N days.

        Args:
            days: Delete violations older than this many days.

        Returns:
            Number of violations deleted.
        """
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            result = (
                self.client.table("rate_limit_violations")
                .delete()
                .lt("created_at", cutoff.isoformat())
                .execute()
            )
            count = len(result.data) if result.data else 0
            if count > 0:
                logger.info("violations_cleaned_up", count=count, days=days)
            return count
        except Exception as e:
            logger.warning("cleanup_violations_failed", error=str(e))
            return 0


# Global database service instance
db_service = DatabaseService()
