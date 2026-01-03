"""Jobs management endpoints."""

import csv
import io
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response

from src.api.middleware.supabase_auth import AuthUser, verify_supabase_token
from src.api.schemas.responses import (
    JobListResponse,
    JobProgress,
    JobStatusResponse,
    JobSummary,
    LeadResponse,
)
from src.api.services.job_manager import job_manager
from src.utils.logger import get_logger

router = APIRouter()
logger = get_logger("jobs_route")


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

    if job:
        # Check ownership
        if job.user_id != auth_user.user_id and auth_user.user_id != "dev-user":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this job",
            )

        leads = []
        for lead in job.leads:
            leads.append(
                LeadResponse(
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

                # Get leads from database
                db_leads = db.get_leads_for_job(job_id)
                leads = []
                for db_lead in db_leads:
                    # Get raw_data if available (contains full lead info)
                    raw = db_lead.get("raw_data", {})
                    leads.append(
                        LeadResponse(
                            name=db_lead.get("name", ""),
                            phone=db_lead.get("phone"),
                            email=db_lead.get("email"),
                            whatsapp=db_lead.get("whatsapp"),
                            website=db_lead.get("website"),
                            address=db_lead.get("address"),
                            category=db_lead.get("category"),
                            rating=db_lead.get("rating"),
                            review_count=db_lead.get("review_count", 0),
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
                            photos_count=db_lead.get("photos_count", 0) or raw.get("photos_count", 0),
                            is_claimed=db_lead.get("is_claimed") or raw.get("is_claimed"),
                            years_in_business=db_lead.get("years_in_business") or raw.get("years_in_business"),
                            outreach=db_lead.get("outreach") or raw.get("outreach"),
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
