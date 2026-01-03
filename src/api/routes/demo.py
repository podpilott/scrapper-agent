"""Demo endpoints for unauthenticated users."""

from fastapi import APIRouter

from src.api.schemas.responses import LeadResponse
from src.utils.logger import get_logger

router = APIRouter()
logger = get_logger("demo_route")


def _get_db_service():
    """Get database service if configured."""
    try:
        from src.api.services.database import db_service

        if db_service.is_configured():
            return db_service
    except Exception:
        pass
    return None


@router.get("/demo/leads", response_model=list[LeadResponse])
async def get_demo_leads() -> list[LeadResponse]:
    """Get public demo leads (no auth required)."""
    db = _get_db_service()
    if db:
        try:
            demo_leads = db.get_demo_leads()
            return [
                LeadResponse(
                    name=lead.get("name", ""),
                    phone=lead.get("phone"),
                    email=lead.get("email"),
                    whatsapp=lead.get("whatsapp"),
                    website=lead.get("website"),
                    address=lead.get("address"),
                    category=lead.get("category"),
                    rating=lead.get("rating"),
                    review_count=lead.get("review_count", 0),
                    score=lead.get("score", 0),
                    tier=lead.get("tier"),
                    maps_url=lead.get("maps_url"),
                )
                for lead in demo_leads
            ]
        except Exception as e:
            logger.error("get_demo_leads_error", error=str(e))
    return []
