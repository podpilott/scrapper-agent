"""Jobs management endpoints."""

import csv
import io
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from slowapi import Limiter
import jwt

from src.api.middleware.supabase_auth import AuthUser, verify_supabase_token
from src.api.schemas.responses import (
    JobListResponse,
    JobProgress,
    JobStatusResponse,
    JobSummary,
    LeadResearch,
    LeadResearchResponse,
    LeadResponse,
)
from src.api.services.job_manager import job_manager
from src.utils.logger import get_logger

router = APIRouter()
logger = get_logger("jobs_route")


def get_user_id_for_limit(request: Request) -> str:
    """Extract user_id from JWT token for rate limiting."""
    try:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            payload = jwt.decode(token, options={"verify_signature": False})
            user_id = payload.get("sub")
            if user_id:
                request.state.user_id = user_id
                return f"user:{user_id}"
    except Exception:
        pass
    return "unknown"


limiter = Limiter(key_func=get_user_id_for_limit)


def _get_db_service():
    """Get database service if configured."""
    try:
        from src.api.services.database import db_service
        if db_service.is_configured():
            return db_service
    except Exception:
        pass
    return None


@router.get("/jobs", response_model=JobListResponse)
async def list_jobs(
    auth_user: AuthUser = Depends(verify_supabase_token),
) -> JobListResponse:
    """List all jobs for the authenticated user."""
    # First try in-memory jobs (for active/running jobs)
    in_memory_jobs = job_manager.get_jobs_for_user(auth_user.user_id)
    in_memory_job_ids = {j.job_id for j in in_memory_jobs}

    job_responses = []

    # Add in-memory jobs first (most up-to-date for running jobs)
    for job in in_memory_jobs:
        job_responses.append(
            JobStatusResponse(
                job_id=job.job_id,
                status=job.status,
                query=job.query,
                created_at=job.created_at,
                started_at=job.started_at,
                completed_at=job.completed_at,
                progress=job.progress,
                summary=job.summary,
                error=job.error,
                # Job config for retry
                max_results=job.max_results,
                min_score=job.min_score,
                skip_enrichment=job.skip_enrichment,
                skip_outreach=job.skip_outreach,
                product_context=job.product_context,
            )
        )

    # Then add historical jobs from database (if configured)
    db = _get_db_service()
    if db:
        try:
            db_jobs = db.get_jobs_for_user(auth_user.user_id)
            for db_job in db_jobs:
                # Skip if already in memory (in-memory is more current)
                if db_job["job_id"] in in_memory_job_ids:
                    continue

                # Parse summary if present
                summary = None
                if db_job.get("summary"):
                    summary = JobSummary(**db_job["summary"])

                # Parse progress if present
                progress = None
                if db_job.get("progress"):
                    progress = JobProgress(**db_job["progress"])

                job_responses.append(
                    JobStatusResponse(
                        job_id=db_job["job_id"],
                        status=db_job["status"],
                        query=db_job["query"],
                        created_at=db_job["created_at"],
                        started_at=db_job.get("started_at"),
                        completed_at=db_job.get("completed_at"),
                        progress=progress,
                        summary=summary,
                        error=db_job.get("error"),
                        # Job config for retry
                        max_results=db_job.get("max_results"),
                        min_score=db_job.get("min_score"),
                        skip_enrichment=db_job.get("skip_enrichment"),
                        skip_outreach=db_job.get("skip_outreach"),
                        product_context=db_job.get("product_context"),
                    )
                )
        except Exception:
            pass  # Fallback to in-memory only if DB fails

    # Sort by created_at descending (handle both timezone-aware and naive datetimes)
    def get_sort_key(j):
        dt = j.created_at
        if dt is None:
            return datetime.min.replace(tzinfo=timezone.utc)
        # If it's a string, parse it
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        # Make timezone-naive datetimes aware (assume UTC)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    job_responses.sort(key=get_sort_key, reverse=True)

    return JobListResponse(jobs=job_responses, total=len(job_responses))


@router.get("/jobs/export/bulk")
async def bulk_export_leads(
    format: Literal["csv", "json"] = Query(default="csv"),
    auth_user: AuthUser = Depends(verify_supabase_token),
) -> Response:
    """Export all leads from all completed jobs."""
    # Get all jobs for user
    jobs_response = await list_jobs(auth_user)

    all_leads = []
    for job_response in jobs_response.jobs:
        if job_response.status == "completed":
            try:
                job_leads = await get_job_leads(job_response.job_id, auth_user)
                # Add job context to each lead
                for lead in job_leads:
                    lead_dict = {
                        "job_id": job_response.job_id,
                        "job_query": job_response.query,
                        "name": lead.name,
                        "phone": lead.phone,
                        "email": lead.email,
                        "whatsapp": lead.whatsapp,
                        "website": lead.website,
                        "address": lead.address,
                        "category": lead.category,
                        "rating": lead.rating,
                        "review_count": lead.review_count,
                        "score": lead.score,
                        "tier": lead.tier,
                        "owner_name": lead.owner_name,
                        "linkedin": lead.linkedin,
                        "facebook": lead.facebook,
                        "instagram": lead.instagram,
                        "maps_url": lead.maps_url,
                        "place_id": lead.place_id,
                        "price_level": lead.price_level,
                        "photos_count": lead.photos_count,
                        "is_claimed": lead.is_claimed,
                        "years_in_business": lead.years_in_business,
                        "outreach": lead.outreach,
                    }
                    all_leads.append(lead_dict)
            except Exception:
                continue

    if not all_leads:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No leads found in completed jobs",
        )

    if format == "csv":
        # Generate CSV
        output = io.StringIO()
        fieldnames = [
            "job_id", "job_query", "name", "phone", "email", "whatsapp", "website", "address",
            "category", "rating", "review_count", "score", "tier",
            "owner_name", "linkedin", "facebook", "instagram", "maps_url",
            "place_id", "price_level", "photos_count", "is_claimed", "years_in_business",
            "email_subject", "email_body", "whatsapp_message", "linkedin_message", "cold_call_script",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()

        for lead in all_leads:
            outreach = lead.get("outreach") or {}
            writer.writerow({
                "job_id": lead.get("job_id", ""),
                "job_query": lead.get("job_query", ""),
                "name": lead.get("name", ""),
                "phone": lead.get("phone") or "",
                "email": lead.get("email") or "",
                "whatsapp": lead.get("whatsapp") or "",
                "website": lead.get("website") or "",
                "address": lead.get("address") or "",
                "category": lead.get("category") or "",
                "rating": lead.get("rating") or "",
                "review_count": lead.get("review_count") or 0,
                "score": lead.get("score") or 0,
                "tier": lead.get("tier") or "",
                "owner_name": lead.get("owner_name") or "",
                "linkedin": lead.get("linkedin") or "",
                "facebook": lead.get("facebook") or "",
                "instagram": lead.get("instagram") or "",
                "maps_url": lead.get("maps_url") or "",
                "place_id": lead.get("place_id") or "",
                "price_level": lead.get("price_level") or "",
                "photos_count": lead.get("photos_count") or 0,
                "is_claimed": lead.get("is_claimed") if lead.get("is_claimed") is not None else "",
                "years_in_business": lead.get("years_in_business") or "",
                "email_subject": outreach.get("email_subject", "") if outreach else "",
                "email_body": outreach.get("email_body", "") if outreach else "",
                "whatsapp_message": outreach.get("whatsapp_message", "") if outreach else "",
                "linkedin_message": outreach.get("linkedin_message", "") if outreach else "",
                "cold_call_script": outreach.get("cold_call_script", "") if outreach else "",
            })

        content = output.getvalue()
        filename = f"all_leads_export.csv"
        return Response(
            content=content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )
    else:
        # Generate JSON
        content = json.dumps(all_leads, indent=2, ensure_ascii=False)
        filename = f"all_leads_export.json"
        return Response(
            content=content,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    auth_user: AuthUser = Depends(verify_supabase_token),
) -> JobStatusResponse:
    """Get status of a specific job."""
    # First try in-memory
    job = job_manager.get_job(job_id)

    if job:
        # Check ownership
        if job.user_id != auth_user.user_id and auth_user.user_id != "dev-user":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this job",
            )

        return JobStatusResponse(
            job_id=job.job_id,
            status=job.status,
            query=job.query,
            created_at=job.created_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            progress=job.progress,
            summary=job.summary,
            error=job.error,
            # Job config for retry
            max_results=job.max_results,
            min_score=job.min_score,
            skip_enrichment=job.skip_enrichment,
            skip_outreach=job.skip_outreach,
            product_context=job.product_context,
        )

    # Fallback to database for historical jobs
    db = _get_db_service()
    if db:
        try:
            db_job = db.get_job(job_id)
            if db_job:
                # Check ownership
                if db_job["user_id"] != auth_user.user_id and auth_user.user_id != "dev-user":
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Not authorized to access this job",
                    )

                summary = None
                if db_job.get("summary"):
                    summary = JobSummary(**db_job["summary"])

                # Parse progress if present
                progress = None
                if db_job.get("progress"):
                    progress = JobProgress(**db_job["progress"])

                return JobStatusResponse(
                    job_id=db_job["job_id"],
                    status=db_job["status"],
                    query=db_job["query"],
                    created_at=db_job["created_at"],
                    started_at=db_job.get("started_at"),
                    completed_at=db_job.get("completed_at"),
                    progress=progress,
                    summary=summary,
                    error=db_job.get("error"),
                    # Job config for retry
                    max_results=db_job.get("max_results"),
                    min_score=db_job.get("min_score"),
                    skip_enrichment=db_job.get("skip_enrichment"),
                    skip_outreach=db_job.get("skip_outreach"),
                    product_context=db_job.get("product_context"),
                )
        except HTTPException:
            raise
        except Exception:
            pass

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Job {job_id} not found",
    )


@router.get("/jobs/{job_id}/leads", response_model=list[LeadResponse])
async def get_job_leads(
    job_id: str,
    auth_user: AuthUser = Depends(verify_supabase_token),
) -> list[LeadResponse]:
    """Get all leads for a job."""
    # First try in-memory job
    job = job_manager.get_job(job_id)

    # Use in-memory leads only if job exists AND has leads
    # (Resumed jobs may have empty in-memory leads but leads in DB)
    if job and job.leads:
        # Check ownership
        if job.user_id != auth_user.user_id and auth_user.user_id != "dev-user":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this job",
            )

        # Fetch database IDs for leads (needed for Business Research button)
        db = _get_db_service()
        place_id_to_db_id: dict[str, str] = {}
        if db:
            try:
                db_leads = db.get_leads_for_job(job_id)
                for db_lead in db_leads:
                    place_id = db_lead.get("place_id")
                    db_id = db_lead.get("id")
                    if place_id and db_id:
                        place_id_to_db_id[place_id] = db_id
            except Exception:
                pass  # Continue without IDs if DB lookup fails

        leads = []
        for lead in job.leads:
            place_id = lead.scored_lead.lead.raw.place_id
            leads.append(
                LeadResponse(
                    id=place_id_to_db_id.get(place_id),  # Add database ID
                    name=lead.name,
                    phone=lead.phone,
                    email=lead.email,
                    whatsapp=lead.whatsapp,
                    website=lead.website,
                    address=lead.address,
                    category=lead.category,
                    rating=lead.rating,
                    review_count=lead.review_count,
                    score=lead.score,
                    tier=lead.tier,
                    owner_name=lead.owner_name,
                    linkedin=lead.linkedin,
                    facebook=lead.scored_lead.lead.social_links.facebook,
                    instagram=lead.scored_lead.lead.social_links.instagram,
                    maps_url=lead.scored_lead.lead.raw.maps_url,
                    # Enhanced fields
                    place_id=lead.scored_lead.lead.raw.place_id,
                    price_level=lead.scored_lead.lead.raw.price_level,
                    photos_count=lead.scored_lead.lead.raw.photos_count,
                    is_claimed=lead.scored_lead.lead.raw.is_claimed,
                    years_in_business=lead.scored_lead.lead.raw.years_in_business,
                    outreach={
                        "email_subject": lead.outreach.email_subject,
                        "email_body": lead.outreach.email_body,
                        "linkedin_message": lead.outreach.linkedin_message,
                        "whatsapp_message": lead.outreach.whatsapp_message,
                        "cold_call_script": lead.outreach.cold_call_script,
                    },
                )
            )
        return leads

    # Fallback to database for historical jobs
    db = _get_db_service()
    if db:
        try:
            # First verify the job exists and check ownership
            db_job = db.get_job(job_id)
            if db_job:
                if db_job["user_id"] != auth_user.user_id and auth_user.user_id != "dev-user":
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Not authorized to access this job",
                    )

                # Helper to safely parse int fields (handles empty strings)
                def safe_int(value, default=None):
                    if value is None or value == "":
                        return default
                    try:
                        return int(value)
                    except (ValueError, TypeError):
                        return default

                # Get leads from database
                db_leads = db.get_leads_for_job(job_id)
                leads = []
                for db_lead in db_leads:
                    # Get raw_data if available (contains full lead info)
                    raw = db_lead.get("raw_data", {})
                    leads.append(
                        LeadResponse(
                            id=db_lead.get("id"),
                            name=db_lead.get("name", ""),
                            phone=db_lead.get("phone"),
                            email=db_lead.get("email"),
                            whatsapp=db_lead.get("whatsapp"),
                            website=db_lead.get("website"),
                            address=db_lead.get("address"),
                            category=db_lead.get("category"),
                            rating=db_lead.get("rating"),
                            review_count=safe_int(db_lead.get("review_count"), 0),
                            score=db_lead.get("score", 0),
                            tier=db_lead.get("tier"),
                            owner_name=db_lead.get("owner_name"),
                            linkedin=db_lead.get("linkedin"),
                            facebook=db_lead.get("facebook") or raw.get("facebook"),
                            instagram=db_lead.get("instagram") or raw.get("instagram"),
                            maps_url=db_lead.get("maps_url") or raw.get("maps_url"),
                            # Enhanced fields
                            place_id=db_lead.get("place_id") or raw.get("place_id"),
                            price_level=db_lead.get("price_level") or raw.get("price_level"),
                            photos_count=safe_int(db_lead.get("photos_count"), 0) or safe_int(raw.get("photos_count"), 0),
                            is_claimed=db_lead.get("is_claimed") or raw.get("is_claimed"),
                            years_in_business=safe_int(db_lead.get("years_in_business")) or safe_int(raw.get("years_in_business")),
                            outreach=db_lead.get("outreach") or raw.get("outreach"),
                            research=db_lead.get("research"),
                        )
                    )
                return leads
        except HTTPException:
            raise
        except Exception as e:
            logger.error("get_job_leads_db_error", job_id=job_id, error=str(e))

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Job {job_id} not found",
    )


@router.get("/jobs/{job_id}/export")
async def export_job_leads(
    job_id: str,
    format: Literal["csv", "json"] = Query(default="csv"),
    auth_user: AuthUser = Depends(verify_supabase_token),
) -> Response:
    """Export leads as CSV or JSON file."""
    # Get leads using existing logic
    leads = await get_job_leads(job_id, auth_user)

    if not leads:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No leads found for this job",
        )

    # Get job query for filename
    job = job_manager.get_job(job_id)
    query_slug = "leads"
    if job:
        query_slug = job.query.replace(" ", "_")[:30]

    if format == "csv":
        # Generate CSV
        output = io.StringIO()
        fieldnames = [
            "name", "phone", "email", "whatsapp", "website", "address",
            "category", "rating", "review_count", "score", "tier",
            "owner_name", "linkedin", "facebook", "instagram", "maps_url",
            "place_id", "price_level", "photos_count", "is_claimed", "years_in_business",
            "email_subject", "email_body", "whatsapp_message", "linkedin_message", "cold_call_script",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()

        for lead in leads:
            outreach = lead.outreach or {}
            writer.writerow({
                "name": lead.name or "",
                "phone": lead.phone or "",
                "email": lead.email or "",
                "whatsapp": lead.whatsapp or "",
                "website": lead.website or "",
                "address": lead.address or "",
                "category": lead.category or "",
                "rating": lead.rating or "",
                "review_count": lead.review_count or 0,
                "score": lead.score or 0,
                "tier": lead.tier or "",
                "owner_name": lead.owner_name or "",
                "linkedin": lead.linkedin or "",
                "facebook": lead.facebook or "",
                "instagram": lead.instagram or "",
                "maps_url": lead.maps_url or "",
                "place_id": lead.place_id or "",
                "price_level": lead.price_level or "",
                "photos_count": lead.photos_count or 0,
                "is_claimed": lead.is_claimed if lead.is_claimed is not None else "",
                "years_in_business": lead.years_in_business or "",
                "email_subject": outreach.get("email_subject", "") if outreach else "",
                "email_body": outreach.get("email_body", "") if outreach else "",
                "whatsapp_message": outreach.get("whatsapp_message", "") if outreach else "",
                "linkedin_message": outreach.get("linkedin_message", "") if outreach else "",
                "cold_call_script": outreach.get("cold_call_script", "") if outreach else "",
            })

        content = output.getvalue()
        filename = f"{query_slug}_{job_id}.csv"
        return Response(
            content=content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )
    else:
        # Generate JSON
        leads_data = [
            {
                "name": lead.name,
                "phone": lead.phone,
                "email": lead.email,
                "whatsapp": lead.whatsapp,
                "website": lead.website,
                "address": lead.address,
                "category": lead.category,
                "rating": lead.rating,
                "review_count": lead.review_count,
                "score": lead.score,
                "tier": lead.tier,
                "owner_name": lead.owner_name,
                "linkedin": lead.linkedin,
                "facebook": lead.facebook,
                "instagram": lead.instagram,
                "maps_url": lead.maps_url,
                "place_id": lead.place_id,
                "price_level": lead.price_level,
                "photos_count": lead.photos_count,
                "is_claimed": lead.is_claimed,
                "years_in_business": lead.years_in_business,
                "outreach": lead.outreach,
            }
            for lead in leads
        ]

        content = json.dumps(leads_data, indent=2, ensure_ascii=False)
        filename = f"{query_slug}_{job_id}.json"
        return Response(
            content=content,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )


@router.delete("/jobs/{job_id}")
async def cancel_job(
    job_id: str,
    auth_user: AuthUser = Depends(verify_supabase_token),
) -> dict:
    """Cancel a running job."""
    job = job_manager.get_job(job_id)

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    # Check ownership
    if job.user_id != auth_user.user_id and auth_user.user_id != "dev-user":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to cancel this job",
        )

    if job.status not in ("pending", "running"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel job with status: {job.status}",
        )

    success = job_manager.cancel_job(job_id)

    if success:
        return {"message": f"Job {job_id} cancelled", "status": "cancelled"}
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to cancel job",
        )


@router.post("/jobs/{job_id}/resume")
async def resume_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    auth_user: AuthUser = Depends(verify_supabase_token),
) -> dict:
    """Resume a failed or cancelled job from where it left off.

    This endpoint:
    1. Validates the job is resumable (status=failed/cancelled, belongs to user)
    2. Loads existing leads to skip re-processing
    3. Resets job status and restarts the pipeline

    Returns immediately. Connect to SSE endpoint for updates.
    """
    db = _get_db_service()
    if not db:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Resume requires database. Database not configured.",
        )

    # Get job from database
    db_job = db.get_job(job_id)
    if not db_job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    # Check ownership
    if db_job["user_id"] != auth_user.user_id and auth_user.user_id != "dev-user":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to resume this job",
        )

    # Only failed or cancelled jobs can be resumed
    if db_job["status"] not in ("failed", "cancelled"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot resume job with status: {db_job['status']}. Only failed or cancelled jobs can be resumed.",
        )

    # Check concurrency limit
    can_start, error_message = job_manager.can_start_job(user_id=auth_user.user_id)
    if not can_start:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=error_message,
        )

    # Prepare job for resume (loads skip_place_ids, resets status)
    job = job_manager.prepare_for_resume(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to prepare job for resume",
        )

    # Import and run scrape job
    from src.api.routes.scrape import run_scrape_job

    background_tasks.add_task(run_scrape_job, job)

    skip_count = len(job.skip_place_ids)
    logger.info(
        "job_resume_started",
        job_id=job_id,
        skip_leads=skip_count,
        user_id=auth_user.user_id,
    )

    return {
        "message": f"Job {job_id} resumed",
        "status": "pending",
        "skip_leads": skip_count,
        "stream_url": f"/api/jobs/{job_id}/stream",
    }


@router.delete("/jobs/{job_id}/delete")
async def delete_job(
    job_id: str,
    auth_user: AuthUser = Depends(verify_supabase_token),
) -> dict:
    """Delete a completed/failed/cancelled job from history."""
    # Check in-memory first
    job = job_manager.get_job(job_id)

    if job:
        # Check ownership
        if job.user_id != auth_user.user_id and auth_user.user_id != "dev-user":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to delete this job",
            )

        # Can only delete completed/failed/cancelled jobs
        if job.status in ("pending", "running"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete a running job. Cancel it first.",
            )

        # Remove from in-memory storage
        if job_id in job_manager._jobs:
            del job_manager._jobs[job_id]

    # Delete from database
    db = _get_db_service()
    if db:
        try:
            db_job = db.get_job(job_id)
            if db_job:
                # Check ownership
                if db_job["user_id"] != auth_user.user_id and auth_user.user_id != "dev-user":
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Not authorized to delete this job",
                    )

                # Delete leads first (foreign key constraint)
                db.client.table("leads").delete().eq("job_id", job_id).execute()
                # Delete job
                db.client.table("jobs").delete().eq("job_id", job_id).execute()

                logger.info("job_deleted", job_id=job_id, user_id=auth_user.user_id)
                return {"message": f"Job {job_id} deleted", "status": "deleted"}
        except HTTPException:
            raise
        except Exception as e:
            logger.error("delete_job_error", job_id=job_id, error=str(e))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete job",
            )

    # If job wasn't in memory and DB not configured, return not found
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    return {"message": f"Job {job_id} deleted", "status": "deleted"}


# ============== Lead Research Endpoint ==============

@router.post("/leads/{lead_id}/research", response_model=LeadResearchResponse)
@limiter.limit("10/minute")
async def generate_lead_research(
    request: Request,
    lead_id: str,
    auth_user: AuthUser = Depends(verify_supabase_token),
) -> LeadResearchResponse:
    """Generate LLM research brief for a lead.

    Rate limited to 10 requests per minute per user.
    Results are cached - subsequent requests return cached data.
    """
    db = _get_db_service()
    if not db:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not configured",
        )

    # Get lead from database
    lead = db.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead {lead_id} not found",
        )

    # Verify ownership via job
    job = db.get_job(lead["job_id"])
    if not job or (job["user_id"] != auth_user.user_id and auth_user.user_id != "dev-user"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this lead",
        )

    # Check if research already exists (cached)
    if lead.get("research"):
        logger.info("lead_research_cache_hit", lead_id=lead_id)
        return LeadResearchResponse(
            lead_id=lead_id,
            research=LeadResearch(**lead["research"]),
            cached=True,
        )

    # Get language from job (defaults to 'en')
    language = job.get("language", "en")

    # Load language-specific prompts
    from config.prompts import get_prompts
    prompts = get_prompts(language)

    # Generate research using LLM with language-specific prompt
    from src.generators.llm import LLMClient

    # Get product context from job if available
    product_context = job.get("product_context") or "Not specified"

    # Build social presence summary
    social_links = []
    if lead.get("linkedin"):
        social_links.append("LinkedIn")
    if lead.get("facebook"):
        social_links.append("Facebook")
    if lead.get("instagram"):
        social_links.append("Instagram")
    social_presence = ", ".join(social_links) if social_links else ("No social profiles found" if language == "en" else "Tidak ada profil sosial ditemukan")

    prompt = prompts.LEAD_RESEARCH_PROMPT.format(
        name=lead.get("name", "Unknown"),
        category=lead.get("category", "Unknown"),
        address=lead.get("address", "Unknown"),
        rating=lead.get("rating", "N/A"),
        review_count=lead.get("review_count", 0),
        website=lead.get("website", "Not available" if language == "en" else "Tidak tersedia"),
        owner_name=lead.get("owner_name") or ("Not identified" if language == "en" else "Tidak teridentifikasi"),
        social_presence=social_presence,
        score=lead.get("score", 0),
        tier=lead.get("tier", "unscored"),
        product_context=product_context,
    )

    try:
        llm = LLMClient()
        response = llm.generate(prompt, max_tokens=500, temperature=0.7)

        # Parse JSON response - handle potential markdown code blocks
        response_text = response.strip()

        # Log the raw response for debugging
        logger.debug("lead_research_raw_response", lead_id=lead_id, response=response_text[:500])

        # Remove markdown code blocks if present
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            # Find the actual JSON content between code fences
            json_lines = []
            in_code_block = False
            for line in lines:
                if line.startswith("```"):
                    in_code_block = not in_code_block
                    continue
                if in_code_block or (not line.startswith("```") and json_lines):
                    json_lines.append(line)
            response_text = "\n".join(json_lines).strip()

        # Try to find JSON object in response if LLM added extra text
        if not response_text.startswith("{"):
            # Look for the first { and last }
            start_idx = response_text.find("{")
            end_idx = response_text.rfind("}")
            if start_idx != -1 and end_idx != -1:
                response_text = response_text[start_idx:end_idx + 1]

        # Attempt to parse JSON
        try:
            research_data = json.loads(response_text)
        except json.JSONDecodeError as e:
            # If JSON parsing fails, log the problematic response and try to fix common issues
            logger.error("lead_research_json_parse_attempt1_failed",
                        lead_id=lead_id,
                        error=str(e),
                        response_snippet=response_text[:200])

            # Try to fix common issues: unescaped quotes in strings
            # This is a fallback - ask LLM to regenerate with stricter instructions
            fixed_prompt = prompt + "\n\nIMPORTANT: Ensure all quotes within strings are properly escaped. Return only valid JSON."
            response = llm.generate(fixed_prompt, max_tokens=500, temperature=0.5)
            response_text = response.strip()

            # Remove markdown again
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                json_lines = []
                in_code_block = False
                for line in lines:
                    if line.startswith("```"):
                        in_code_block = not in_code_block
                        continue
                    if in_code_block or (not line.startswith("```") and json_lines):
                        json_lines.append(line)
                response_text = "\n".join(json_lines).strip()

            # Find JSON object
            if not response_text.startswith("{"):
                start_idx = response_text.find("{")
                end_idx = response_text.rfind("}")
                if start_idx != -1 and end_idx != -1:
                    response_text = response_text[start_idx:end_idx + 1]

            research_data = json.loads(response_text)

        research_data["generated_at"] = datetime.utcnow().isoformat()

        # Cache result in database
        db.update_lead_research(lead_id, research_data)

        logger.info("lead_research_generated", lead_id=lead_id, user_id=auth_user.user_id, language=language)

        return LeadResearchResponse(
            lead_id=lead_id,
            research=LeadResearch(**research_data),
            cached=False,
        )

    except json.JSONDecodeError as e:
        logger.error("lead_research_json_parse_failed",
                    lead_id=lead_id,
                    error=str(e),
                    response=response_text if 'response_text' in locals() else "No response")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to parse research response",
        )
    except Exception as e:
        logger.error("lead_research_failed", lead_id=lead_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate research",
        )
