"""Job state management service with optional database persistence."""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from config.settings import settings
from src.api.schemas.responses import JobProgress, JobSummary
from src.models.lead import FinalLead
from src.utils.logger import get_logger

logger = get_logger("job_manager")


@dataclass
class Job:
    """Represents a scrape job."""

    job_id: str
    query: str
    status: str = "pending"  # pending, running, completed, failed, cancelled
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    user_id: str = ""

    # Configuration
    max_results: int = 20
    min_score: int = 0
    skip_enrichment: bool = False
    skip_outreach: bool = False
    product_context: str | None = None

    # Progress tracking
    progress: JobProgress | None = None
    summary: JobSummary | None = None
    error: str | None = None

    # Results
    leads: list[FinalLead] = field(default_factory=list)

    # Event buffer for reconnection
    event_buffer: list[dict[str, Any]] = field(default_factory=list)
    max_buffer_size: int = 100

    # Cancellation
    cancel_requested: bool = False

    # Resume checkpoint
    checkpoint: dict[str, Any] | None = None
    skip_place_ids: set[str] = field(default_factory=set)
    resume_step: str | None = None  # Step to resume from (e.g., "Generating outreach messages")

    def add_event(self, event: dict[str, Any]) -> None:
        """Add event to buffer for reconnection support."""
        self.event_buffer.append(event)
        # Limit buffer size
        if len(self.event_buffer) > self.max_buffer_size:
            self.event_buffer = self.event_buffer[-self.max_buffer_size:]


class JobManager:
    """Manages job state and lifecycle with optional database persistence."""

    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._callbacks: dict[str, list[Callable]] = {}
        self._cleanup_task: asyncio.Task | None = None
        self._running_jobs: int = 0
        self._db_service = None

    @property
    def db(self):
        """Lazy load database service."""
        if self._db_service is None:
            try:
                from src.api.services.database import db_service
                if db_service.is_configured():
                    self._db_service = db_service
            except Exception as e:
                logger.warning("database_not_configured", error=str(e))
        return self._db_service

    def create_job(
        self,
        query: str,
        user_id: str,
        max_results: int = 20,
        min_score: int = 0,
        skip_enrichment: bool = False,
        skip_outreach: bool = False,
        product_context: str | None = None,
    ) -> Job:
        """Create a new job.

        Args:
            query: Search query.
            user_id: Supabase user ID.
            max_results: Maximum leads to scrape.
            min_score: Minimum score filter.
            skip_enrichment: Skip website enrichment.
            skip_outreach: Skip outreach generation.
            product_context: Product description for outreach.

        Returns:
            Created Job object.
        """
        job_id = str(uuid.uuid4())[:8]
        job = Job(
            job_id=job_id,
            query=query,
            user_id=user_id,
            max_results=max_results,
            min_score=min_score,
            skip_enrichment=skip_enrichment,
            skip_outreach=skip_outreach,
            product_context=product_context,
        )
        self._jobs[job_id] = job
        logger.info("job_created", job_id=job_id, query=query)

        # Persist to database if configured
        if self.db:
            try:
                self.db.create_job(
                    job_id=job_id,
                    user_id=user_id,
                    query=query,
                    max_results=max_results,
                    min_score=min_score,
                    skip_enrichment=skip_enrichment,
                    skip_outreach=skip_outreach,
                    product_context=product_context,
                )
            except Exception as e:
                logger.error("db_create_job_error", job_id=job_id, error=str(e))

        return job

    def get_job(self, job_id: str) -> Job | None:
        """Get job by ID."""
        return self._jobs.get(job_id)

    def get_jobs_for_user(self, user_id: str) -> list[Job]:
        """Get all jobs for a user."""
        return [j for j in self._jobs.values() if j.user_id == user_id]

    def update_status(self, job_id: str, status: str) -> None:
        """Update job status."""
        job = self._jobs.get(job_id)
        if job:
            job.status = status
            started_at = None
            completed_at = None

            if status == "running" and job.started_at is None:
                job.started_at = datetime.utcnow()
                started_at = job.started_at
            elif status in ("completed", "failed", "cancelled"):
                job.completed_at = datetime.utcnow()
                completed_at = job.completed_at

            logger.info("job_status_updated", job_id=job_id, status=status)

            # Update database if configured
            if self.db:
                try:
                    self.db.update_job_status(
                        job_id=job_id,
                        status=status,
                        started_at=started_at,
                        completed_at=completed_at,
                    )
                except Exception as e:
                    logger.error("db_update_status_error", job_id=job_id, error=str(e))

    def update_progress(
        self,
        job_id: str,
        step: str,
        current: int,
        total: int,
        message: str | None = None,
    ) -> None:
        """Update job progress."""
        job = self._jobs.get(job_id)
        if job:
            job.progress = JobProgress(
                step=step,
                current=current,
                total=total,
                message=message,
            )
            # Add to event buffer
            event = {
                "type": "status",
                "step": step,
                "current": current,
                "total": total,
                "message": message,
            }
            job.add_event(event)
            # Notify callbacks
            self._notify_callbacks(job_id, event)

            # Persist to database if configured
            if self.db:
                try:
                    self.db.update_job_progress(
                        job_id=job_id,
                        step=step,
                        current=current,
                        total=total,
                        message=message,
                    )
                except Exception as e:
                    logger.error("db_update_progress_error", job_id=job_id, error=str(e))

    def add_lead(self, job_id: str, lead: FinalLead) -> tuple[bool, str | None]:
        """Add a lead to job results with cross-job deduplication.

        Returns:
            Tuple of (was_added, existing_job_id). If duplicate, returns (False, job_id).
        """
        job = self._jobs.get(job_id)
        if not job:
            return False, None

        lead_dict = lead.to_flat_dict()
        place_id = lead_dict.get("place_id")

        # Check for same-job duplicates (in-memory)
        if place_id:
            for existing_lead in job.leads:
                if existing_lead.scored_lead.lead.raw.place_id == place_id:
                    logger.debug("same_job_duplicate_skipped", place_id=place_id)
                    return False, job_id

        # Check for cross-job duplicates in database
        if self.db:
            try:
                existing = self.db.check_lead_exists(
                    user_id=job.user_id,
                    place_id=lead_dict.get("place_id"),
                    phone=lead_dict.get("phone"),
                )
                if existing:
                    existing_job_id = existing.get("job_id")
                    logger.info(
                        "duplicate_lead_skipped",
                        name=lead.name,
                        existing_job=existing_job_id,
                    )
                    return False, existing_job_id
            except Exception as e:
                logger.warning("dedup_check_failed", error=str(e))
                # Continue anyway if dedup check fails

        # Add to in-memory storage
        job.leads.append(lead)

        # Add to event buffer
        event = {"type": "lead", "data": lead_dict}
        job.add_event(event)

        # Notify callbacks
        self._notify_callbacks(job_id, event)

        # Persist to database if configured
        if self.db:
            try:
                self.db.add_lead(
                    job_id=job_id,
                    user_id=job.user_id,
                    lead_data=lead_dict,
                )
            except Exception as e:
                logger.error("db_add_lead_error", job_id=job_id, error=str(e))

        return True, None

    def update_lead(self, job_id: str, place_id: str, lead: FinalLead) -> bool:
        """Update an existing lead with enriched data.

        Args:
            job_id: The job ID.
            place_id: The place ID to identify the lead.
            lead: Updated FinalLead object.

        Returns:
            True if lead was updated, False if not found.
        """
        job = self._jobs.get(job_id)
        if not job:
            return False

        lead_dict = lead.to_flat_dict()

        # Update in-memory storage
        for i, existing_lead in enumerate(job.leads):
            if existing_lead.scored_lead.lead.raw.place_id == place_id:
                job.leads[i] = lead
                break

        # Add to event buffer (as an update)
        event = {"type": "lead_update", "data": lead_dict}
        job.add_event(event)

        # Notify callbacks
        self._notify_callbacks(job_id, event)

        # Update in database if configured
        if self.db:
            try:
                self.db.update_lead(
                    job_id=job_id,
                    place_id=place_id,
                    lead_data=lead_dict,
                )
            except Exception as e:
                logger.error("db_update_lead_error", job_id=job_id, error=str(e))

        return True

    def complete_job(self, job_id: str, summary: JobSummary) -> None:
        """Mark job as completed."""
        job = self._jobs.get(job_id)
        if job:
            job.status = "completed"
            job.completed_at = datetime.utcnow()
            job.summary = summary
            # Add to event buffer
            event = {
                "type": "complete",
                "summary": summary.model_dump(),
            }
            job.add_event(event)
            # Notify callbacks
            self._notify_callbacks(job_id, event)
            logger.info("job_completed", job_id=job_id, total_leads=summary.total_leads)

            # Update database if configured
            if self.db:
                try:
                    self.db.complete_job(job_id, summary)
                except Exception as e:
                    logger.error("db_complete_job_error", job_id=job_id, error=str(e))

    def fail_job(self, job_id: str, error: str) -> None:
        """Mark job as failed."""
        job = self._jobs.get(job_id)
        if job:
            job.status = "failed"
            job.completed_at = datetime.utcnow()
            job.error = error
            # Add to event buffer
            event = {"type": "error", "message": error, "recoverable": False}
            job.add_event(event)
            # Notify callbacks
            self._notify_callbacks(job_id, event)
            logger.error("job_failed", job_id=job_id, error=error)

            # Update database if configured
            if self.db:
                try:
                    self.db.fail_job(job_id, error)
                except Exception as e:
                    logger.error("db_fail_job_error", job_id=job_id, error=str(e))

    def cancel_job(self, job_id: str) -> bool:
        """Request job cancellation."""
        job = self._jobs.get(job_id)
        if job and job.status in ("pending", "running"):
            job.cancel_requested = True
            job.status = "cancelled"
            job.completed_at = datetime.utcnow()
            logger.info("job_cancelled", job_id=job_id)

            # Update database if configured
            if self.db:
                try:
                    self.db.cancel_job(job_id)
                except Exception as e:
                    logger.error("db_cancel_job_error", job_id=job_id, error=str(e))

            return True
        return False

    def is_cancelled(self, job_id: str) -> bool:
        """Check if job cancellation was requested."""
        job = self._jobs.get(job_id)
        return job.cancel_requested if job else False

    def update_checkpoint(
        self,
        job_id: str,
        step: str,
        processed_place_ids: list[str],
        last_index: int,
    ) -> None:
        """Update job checkpoint for resume support.

        Args:
            job_id: The job ID.
            step: Current pipeline step.
            processed_place_ids: List of place_ids already processed.
            last_index: Last processed index in the current step.
        """
        job = self._jobs.get(job_id)
        if job:
            checkpoint = {
                "step": step,
                "processed_place_ids": processed_place_ids,
                "last_index": last_index,
                "saved_at": datetime.utcnow().isoformat(),
            }
            job.checkpoint = checkpoint

            # Persist to database if configured
            if self.db:
                try:
                    self.db.update_job_checkpoint(job_id, checkpoint)
                except Exception as e:
                    logger.error("db_update_checkpoint_error", job_id=job_id, error=str(e))

    def prepare_for_resume(self, job_id: str) -> Job | None:
        """Prepare a failed or cancelled job for resumption.

        Loads the job from database, gets existing place_ids to skip,
        and resets the job status.

        Args:
            job_id: The job ID to resume.

        Returns:
            Job object ready for resumption, or None if not resumable.
        """
        if not self.db:
            logger.warning("resume_not_available", reason="database_not_configured")
            return None

        # Get job from database
        job_data = self.db.get_job(job_id)
        if not job_data:
            logger.warning("resume_job_not_found", job_id=job_id)
            return None

        if job_data["status"] not in ("failed", "cancelled"):
            logger.warning("resume_job_not_resumable", job_id=job_id, status=job_data["status"])
            return None

        # Get existing place_ids to skip
        skip_place_ids = self.db.get_job_place_ids(job_id)
        lead_count = len(skip_place_ids)

        if lead_count == 0:
            logger.info("resume_no_leads", job_id=job_id)
            # No leads to resume from - will essentially restart

        # Reset job in database
        if not self.db.reset_job_for_resume(job_id):
            logger.error("resume_reset_failed", job_id=job_id)
            return None

        # Extract resume step from checkpoint
        checkpoint = job_data.get("checkpoint")
        resume_step = None
        if checkpoint and isinstance(checkpoint, dict):
            resume_step = checkpoint.get("step")

        # Create in-memory job object
        job = Job(
            job_id=job_data["job_id"],
            query=job_data["query"],
            status="pending",
            user_id=job_data["user_id"],
            max_results=job_data.get("max_results", 20),
            min_score=job_data.get("min_score", 0),
            skip_enrichment=job_data.get("skip_enrichment", False),
            skip_outreach=job_data.get("skip_outreach", False),
            product_context=job_data.get("product_context"),
            checkpoint=checkpoint,
            skip_place_ids=skip_place_ids,
            resume_step=resume_step,
        )

        # Add to in-memory storage
        self._jobs[job_id] = job

        logger.info(
            "job_prepared_for_resume",
            job_id=job_id,
            skip_leads=lead_count,
            resume_step=resume_step,
        )

        return job

    def can_start_job(self, user_id: str | None = None) -> tuple[bool, str | None]:
        """Check if we can start a new job (both per-user and global limits).

        Args:
            user_id: User ID to check per-user limit. If None, only checks global.

        Returns:
            Tuple of (can_start, error_message). If can_start is True, error_message is None.
        """
        # Check global limit
        global_running = sum(1 for j in self._jobs.values() if j.status in ("pending", "running"))
        if global_running >= settings.max_concurrent_jobs:
            return False, f"Server is busy. Maximum {settings.max_concurrent_jobs} jobs can run at once. Try again later."

        # Check per-user limit if user_id provided
        if user_id:
            user_running = sum(
                1 for j in self._jobs.values()
                if j.user_id == user_id and j.status in ("pending", "running")
            )
            if user_running >= settings.max_jobs_per_user:
                return False, f"You already have {user_running} job(s) running. Wait for it to complete or cancel it."

        return True, None

    def register_callback(self, job_id: str, callback: Callable) -> None:
        """Register callback for job events."""
        if job_id not in self._callbacks:
            self._callbacks[job_id] = []
        self._callbacks[job_id].append(callback)

    def unregister_callback(self, job_id: str, callback: Callable) -> None:
        """Unregister callback for job events."""
        if job_id in self._callbacks:
            try:
                self._callbacks[job_id].remove(callback)
            except ValueError:
                pass

    def _notify_callbacks(self, job_id: str, event: dict[str, Any]) -> None:
        """Notify all registered callbacks for a job."""
        callbacks = self._callbacks.get(job_id, [])
        for callback in callbacks:
            try:
                callback(event)
            except Exception as e:
                logger.warning("callback_error", job_id=job_id, error=str(e))

    def start_cleanup_task(self) -> None:
        """Start background task to clean up old jobs."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    def stop_cleanup_task(self) -> None:
        """Stop the cleanup task."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            self._cleanup_task = None

    async def _cleanup_loop(self) -> None:
        """Background loop to clean up expired jobs and check for timeouts."""
        while True:
            try:
                await asyncio.sleep(60)  # Run every minute for timeout checks
                self._check_timed_out_jobs()  # Check for stuck jobs
                self._cleanup_old_jobs()  # Clean up old completed jobs
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("cleanup_error", error=str(e))

    def _cleanup_old_jobs(self) -> None:
        """Remove jobs older than TTL."""
        cutoff = datetime.utcnow() - timedelta(hours=settings.job_ttl_hours)
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if job.created_at < cutoff and job.status in ("completed", "failed", "cancelled")
        ]
        for job_id in expired:
            del self._jobs[job_id]
            if job_id in self._callbacks:
                del self._callbacks[job_id]
        if expired:
            logger.info("jobs_cleaned_up", count=len(expired))

    def _check_timed_out_jobs(self) -> None:
        """Check for and fail jobs that have been running too long."""
        timeout_cutoff = datetime.utcnow() - timedelta(minutes=settings.job_timeout_minutes)
        timed_out = [
            job for job in self._jobs.values()
            if job.status == "running" and job.started_at and job.started_at < timeout_cutoff
        ]
        for job in timed_out:
            error_msg = f"Job timed out after {settings.job_timeout_minutes} minutes. Please try again."
            logger.warning(
                "job_timed_out",
                job_id=job.job_id,
                started_at=job.started_at.isoformat() if job.started_at else None,
            )
            self.fail_job(job.job_id, error_msg)

    async def recover_stale_jobs(self) -> int:
        """Recover orphaned jobs after server restart.

        Marks any 'running' or 'pending' jobs in the database as 'failed'
        since they were interrupted by the restart.

        Returns:
            Number of jobs recovered/marked as failed.
        """
        if not self.db:
            logger.info("job_recovery_skipped", reason="database_not_configured")
            return 0

        try:
            # Query for orphaned jobs directly from database
            result = (
                self.db.client.table("jobs")
                .select("job_id, status, query, started_at")
                .in_("status", ["running", "pending"])
                .execute()
            )

            orphaned_jobs = result.data or []

            if not orphaned_jobs:
                logger.info("job_recovery_none_found")
                return 0

            # Mark each as failed
            for job_data in orphaned_jobs:
                job_id = job_data["job_id"]
                error_msg = "Job interrupted by server restart. Please start a new job."

                self.db.client.table("jobs").update({
                    "status": "failed",
                    "completed_at": datetime.utcnow().isoformat(),
                    "error": error_msg,
                }).eq("job_id", job_id).execute()

                logger.info(
                    "job_recovered",
                    job_id=job_id,
                    previous_status=job_data["status"],
                    query=job_data.get("query", "")[:30],
                )

            logger.info("job_recovery_complete", count=len(orphaned_jobs))
            return len(orphaned_jobs)

        except Exception as e:
            logger.error("job_recovery_failed", error=str(e))
            return 0


# Global job manager instance
job_manager = JobManager()
