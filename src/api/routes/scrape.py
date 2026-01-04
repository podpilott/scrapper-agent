"""Scrape endpoint for starting new scrape jobs."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from config.settings import settings
from src.api.middleware.supabase_auth import AuthUser, verify_supabase_token
from src.api.schemas.requests import ScrapeRequest
from src.api.schemas.responses import JobCreatedResponse, JobSummary
from src.api.services.database import db_service, format_ban_remaining
from src.api.services.job_manager import Job, job_manager
from src.models.lead import (
    EnrichedLead,
    FinalLead,
    LeadScore,
    RawLead,
    ScoredLead,
    SocialLinks,
)
from src.pipeline.orchestrator import Pipeline, PipelineResult
from src.utils.logger import get_logger

logger = get_logger("scrape_route")

router = APIRouter()

# Thread pool for running blocking pipeline operations
_executor = ThreadPoolExecutor(max_workers=3)


def _db_lead_to_raw_lead(db_lead: dict, query: str) -> RawLead:
    """Convert a database lead record back to a RawLead object for reprocessing.

    Args:
        db_lead: Lead data from database.
        query: The original search query.

    Returns:
        RawLead object that can be processed by the pipeline.
    """
    raw_data = db_lead.get("raw_data") or {}

    return RawLead(
        place_id=db_lead.get("place_id") or "unknown",
        name=db_lead.get("name", ""),
        phone=db_lead.get("phone"),
        website=db_lead.get("website"),
        address=db_lead.get("address") or "",
        latitude=raw_data.get("latitude"),
        longitude=raw_data.get("longitude"),
        category=db_lead.get("category") or "",
        categories=raw_data.get("categories", []),
        rating=db_lead.get("rating"),
        review_count=db_lead.get("review_count") or 0,
        price_level=db_lead.get("price_level"),
        business_hours=raw_data.get("business_hours"),
        is_open_now=raw_data.get("is_open_now"),
        photos_count=db_lead.get("photos_count") or 0,
        is_claimed=db_lead.get("is_claimed"),
        years_in_business=db_lead.get("years_in_business"),
        search_query=query,
        maps_url=db_lead.get("maps_url") or "",
    )


def _db_lead_to_scored_lead(db_lead: dict, query: str) -> ScoredLead:
    """Convert a database lead record to a ScoredLead object for outreach-only resume.

    This is used when resuming from the outreach step - leads have already been
    enriched and scored, so we reconstruct ScoredLead objects from DB data.

    Args:
        db_lead: Lead data from database (with score, tier, etc.).
        query: The original search query.

    Returns:
        ScoredLead object that can be passed directly to outreach generation.
    """
    raw_lead = _db_lead_to_raw_lead(db_lead, query)

    # Reconstruct EnrichedLead with data from DB
    enriched = EnrichedLead(
        raw=raw_lead,
        emails=[db_lead.get("email")] if db_lead.get("email") else [],
        primary_email=db_lead.get("email"),
        social_links=SocialLinks(
            linkedin=db_lead.get("linkedin"),
            facebook=db_lead.get("facebook"),
            instagram=db_lead.get("instagram"),
        ),
        owner_name=db_lead.get("owner_name"),
        whatsapp=db_lead.get("whatsapp"),
        website_reachable=True,  # Assume reachable if we got this far
    )

    # Reconstruct LeadScore - use stored score to derive component scores
    # We don't have the breakdown, so distribute evenly based on total
    total_score = db_lead.get("score") or 0
    component_score = total_score * 1.25 / 5  # Reverse the normalization, divide by 5 components
    lead_score = LeadScore(
        rating_score=component_score,
        review_score=component_score,
        completeness_score=component_score,
        social_presence_score=component_score,
        business_signals_score=component_score,
    )

    return ScoredLead(lead=enriched, score=lead_score)


def _run_pipeline_sync(job: Job) -> PipelineResult:
    """Run pipeline synchronously (for thread pool execution).

    Args:
        job: Job configuration.

    Returns:
        PipelineResult with leads and summary.
    """
    job_id = job.job_id

    # Track which place_ids were actually saved (not duplicates)
    saved_place_ids: set[str] = set()
    # Track deduplication info for summary
    duplicate_job_ids: set[str] = set()
    duplicates_count: int = 0
    total_scraped: int = 0

    # For resume: track place_ids to skip (already processed in previous run)
    resume_skip_place_ids: set[str] = job.skip_place_ids or set()
    is_resume = len(resume_skip_place_ids) > 0
    resume_step = job.resume_step  # Step to resume from (e.g., "Generating outreach")

    # For resume: load leads that need further processing
    resume_leads: list[RawLead] = []
    resume_scored_leads: list[ScoredLead] = []

    # Determine if we're resuming from outreach step (skip enrichment/scoring)
    is_outreach_resume = is_resume and resume_step and "outreach" in resume_step.lower()

    if is_resume and db_service.is_configured():
        db_leads = db_service.get_unenriched_leads_for_job(job_id)

        if is_outreach_resume:
            # OUTREACH-ONLY RESUME: Load as ScoredLead to skip enrichment/scoring
            resume_scored_leads = [
                _db_lead_to_scored_lead(db_lead, job.query)
                for db_lead in db_leads
            ]
            logger.info(
                "resuming_job_outreach_only",
                job_id=job_id,
                scored_lead_count=len(resume_scored_leads),
                resume_step=resume_step,
            )
            # Add place_ids to saved_place_ids so updates work
            for scored_lead in resume_scored_leads:
                saved_place_ids.add(scored_lead.lead.raw.place_id)
        else:
            # ENRICHMENT RESUME: Load as RawLead to re-enrich
            resume_leads = [
                _db_lead_to_raw_lead(db_lead, job.query)
                for db_lead in db_leads
            ]
            logger.info(
                "resuming_job",
                job_id=job_id,
                skip_count=len(resume_skip_place_ids),
                lead_count=len(resume_leads),
                resume_step=resume_step,
            )
            # Add resumed lead place_ids to saved_place_ids so updates work
            for lead in resume_leads:
                saved_place_ids.add(lead.place_id)
    elif is_resume:
        logger.info(
            "resuming_job",
            job_id=job_id,
            skip_count=len(resume_skip_place_ids),
            resume_step=resume_step,
        )

    def progress_callback(step: str, current: int, total: int) -> None:
        if job_manager.is_cancelled(job_id):
            raise Exception("Job cancelled")
        message = _get_step_message(step, current, total)
        job_manager.update_progress(job_id, step, current, total, message)

        # Update checkpoint for resume support
        job_manager.update_checkpoint(
            job_id,
            step=step,
            processed_place_ids=list(saved_place_ids),
            last_index=current,
        )

    def lead_callback(lead: FinalLead) -> bool:
        """Add lead and return True if saved, False if duplicate."""
        nonlocal duplicates_count
        place_id = lead.scored_lead.lead.raw.place_id

        # Skip leads that were already processed in previous run (resume)
        if place_id in resume_skip_place_ids:
            logger.debug("skipping_resumed_lead", place_id=place_id)
            return False

        was_added, existing_job_id = job_manager.add_lead(job_id, lead)
        if was_added:
            saved_place_ids.add(place_id)
        else:
            duplicates_count += 1
            if existing_job_id:
                duplicate_job_ids.add(existing_job_id)
        return was_added

    def lead_update_callback(lead: FinalLead) -> None:
        place_id = lead.scored_lead.lead.raw.place_id
        # Only update leads that were actually saved (not duplicates or resumed)
        if place_id in saved_place_ids:
            job_manager.update_lead(job_id, place_id, lead)

    def on_scrape_complete(count: int) -> None:
        """Called when scraping is complete to track total scraped."""
        nonlocal total_scraped
        total_scraped = count

    pipeline = Pipeline(
        max_results=job.max_results,
        min_score=job.min_score,
        skip_enrichment=job.skip_enrichment,
        skip_outreach=job.skip_outreach,
        product_context=job.product_context,
        progress_callback=progress_callback,
        lead_callback=lead_callback,
        lead_update_callback=lead_update_callback,
        saved_place_ids=saved_place_ids,  # Pass to pipeline to skip duplicates
        resume_leads=resume_leads if resume_leads else None,  # Pass leads for enrichment resume
        resume_step=resume_step,  # Step to resume from
        resume_scored_leads=resume_scored_leads if resume_scored_leads else None,  # Pass scored leads for outreach resume
    )

    # Run async pipeline in new event loop (since we're in a thread)
    result = asyncio.run(pipeline.run(job.query))

    # Attach deduplication info to result for summary building
    result.total_scraped = result.total_scraped or total_scraped
    result.duplicates_skipped = duplicates_count
    result.duplicate_jobs = list(duplicate_job_ids)

    return result


async def run_scrape_job(job: Job) -> None:
    """Run a scrape job in a background thread.

    Args:
        job: Job object with configuration.
    """
    job_id = job.job_id

    try:
        # Update status to running
        job_manager.update_status(job_id, "running")

        # Run pipeline in thread pool to avoid blocking event loop
        loop = asyncio.get_event_loop()
        result: PipelineResult = await loop.run_in_executor(
            _executor, _run_pipeline_sync, job
        )

        # Build summary from SAVED leads (not processed leads, due to deduplication)
        # Get the actual saved leads from job manager
        saved_job = job_manager.get_job(job_id)
        saved_leads = saved_job.leads if saved_job else []

        # Fallback: if in-memory leads are empty but DB has leads, get from DB
        # This can happen due to race conditions or memory issues
        if not saved_leads and db_service.is_configured():
            db_leads = db_service.get_leads_for_job(job_id)
            if db_leads:
                logger.warning(
                    "using_db_leads_for_summary",
                    job_id=job_id,
                    in_memory_count=0,
                    db_count=len(db_leads),
                )
                # Build tiers from DB leads
                tiers = {"hot": 0, "warm": 0, "cold": 0}
                for db_lead in db_leads:
                    tier = db_lead.get("tier", "cold")
                    if tier in tiers:
                        tiers[tier] += 1

                summary = JobSummary(
                    total_leads=len(db_leads),
                    hot=tiers["hot"],
                    warm=tiers["warm"],
                    cold=tiers["cold"],
                    duration_seconds=result.duration_seconds,
                    total_scraped=result.total_scraped,
                    duplicates_skipped=result.duplicates_skipped,
                    duplicate_jobs=result.duplicate_jobs,
                )
                job_manager.complete_job(job_id, summary)
                return

        logger.info(
            "building_summary",
            job_id=job_id,
            saved_leads_count=len(saved_leads),
            result_leads_count=len(result.leads),
        )

        tiers = {"hot": 0, "warm": 0, "cold": 0}
        for lead in saved_leads:
            tiers[lead.tier] = tiers.get(lead.tier, 0) + 1

        summary = JobSummary(
            total_leads=len(saved_leads),
            hot=tiers["hot"],
            warm=tiers["warm"],
            cold=tiers["cold"],
            duration_seconds=result.duration_seconds,
            # Deduplication info
            total_scraped=result.total_scraped,
            duplicates_skipped=result.duplicates_skipped,
            duplicate_jobs=result.duplicate_jobs,
        )

        job_manager.complete_job(job_id, summary)

    except Exception as e:
        error_msg = str(e)
        if "cancelled" in error_msg.lower():
            logger.info("job_cancelled_during_run", job_id=job_id)
            job_manager.update_status(job_id, "cancelled")
        else:
            logger.error("job_error", job_id=job_id, error=error_msg)
            job_manager.fail_job(job_id, error_msg)


def _get_step_message(step: str, current: int, total: int) -> str:
    """Get human-readable message for a step."""
    messages = {
        "Scraping Google Maps": f"Scraping Google Maps ({current}/{total})...",
        "Enriching leads": f"Enriching leads ({current}/{total})...",
        "Scoring leads": f"Scoring leads ({current}/{total})...",
        "Generating outreach": f"Generating outreach messages ({current}/{total})...",
        "Resuming job": f"Resuming job ({current}/{total} leads)...",
        "Resuming outreach": f"Resuming outreach generation ({current}/{total})...",
    }
    return messages.get(step, f"{step} ({current}/{total})...")


@router.post("/scrape", response_model=JobCreatedResponse)
async def start_scrape(
    request: ScrapeRequest,
    background_tasks: BackgroundTasks,
    auth_user: AuthUser = Depends(verify_supabase_token),
) -> JobCreatedResponse:
    """Start a new scrape job.

    Returns immediately with job_id. Connect to SSE endpoint for real-time updates.
    """
    # Check if user is banned
    if db_service.is_configured():
        ban_info = db_service.get_user_ban_info(auth_user.user_id)
        if ban_info:
            remaining = format_ban_remaining(ban_info.get("expires_at"))
            logger.warning("banned_user_scrape_attempt", user_id=auth_user.user_id)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Your account has been temporarily restricted due to excessive requests. Try again in {remaining}.",
            )

    # Check concurrency limit (per-user and global)
    can_start, error_message = job_manager.can_start_job(user_id=auth_user.user_id)
    if not can_start:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=error_message,
        )

    # Apply limits to prevent abuse
    max_results = request.max_results
    if max_results is None:
        max_results = settings.default_max_results
    max_results = min(max_results, settings.max_results_limit)

    # Truncate product_context if too long
    product_context = request.product_context
    if product_context:
        if len(product_context) > settings.product_context_max_chars:
            product_context = product_context[: settings.product_context_max_chars]
            logger.warning(
                "product_context_truncated",
                original_chars=len(request.product_context),
                max_chars=settings.product_context_max_chars,
            )

    # Create job with user_id
    job = job_manager.create_job(
        query=request.query,
        user_id=auth_user.user_id,
        max_results=max_results,
        min_score=request.min_score,
        skip_enrichment=request.skip_enrichment,
        skip_outreach=request.skip_outreach,
        product_context=product_context,
    )

    # Start background task
    background_tasks.add_task(run_scrape_job, job)

    return JobCreatedResponse(
        job_id=job.job_id,
        status="pending",
        stream_url=f"/api/jobs/{job.job_id}/stream",
    )
