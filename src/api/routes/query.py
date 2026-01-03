"""Query enhancement endpoint with security measures."""

import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from slowapi import Limiter

from src.api.middleware.supabase_auth import AuthUser, verify_supabase_token
from src.api.services.database import db_service
from src.generators.llm import LLMClient
from src.utils.logger import get_logger

router = APIRouter()
logger = get_logger("query_route")


def get_user_id_for_limit(request: Request) -> str:
    """Extract user_id from request state for rate limiting."""
    # This is set by verify_supabase_token dependency
    if hasattr(request.state, "user_id"):
        return f"user:{request.state.user_id}"
    return "unknown"


# Rate limiter keyed by user_id
limiter = Limiter(key_func=get_user_id_for_limit)

# Security constants
MAX_QUERY_LENGTH = 200


class QueryEnhanceRequest(BaseModel):
    query: str = Field(..., max_length=MAX_QUERY_LENGTH + 50)  # Allow slight buffer for validation


class QueryEnhanceResponse(BaseModel):
    query_type: str  # "company", "category_no_location", or "good"
    is_problematic: bool
    message: str | None = None
    suggestions: list[str] = []


def sanitize_query(query: str) -> str:
    """Sanitize query input to prevent abuse.

    - Removes control characters
    - Strips whitespace
    - Limits length
    """
    # Remove control characters (including null bytes, etc.)
    query = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', query)
    # Remove excessive whitespace
    query = ' '.join(query.split())
    # Limit length
    return query[:MAX_QUERY_LENGTH].strip()


QUERY_ENHANCE_PROMPT = """Analyze this Google Maps search query: "{query}"

Determine:
1. Is this a specific company/brand name (e.g., "Starbucks", "Phincon", "McDonald's")
2. Is this a business category + location (e.g., "coffee shops in Jakarta")
3. Is this missing a location (e.g., just "restaurants")

Return a JSON object with:
- "query_type": "company" | "category_no_location" | "good"
- "suggestions": Array of 2-3 improved queries if the query is problematic

Example responses:
- Input: "phincon" -> {{"query_type": "company", "suggestions": ["IT companies in Jakarta", "software companies in Indonesia"]}}
- Input: "restaurants" -> {{"query_type": "category_no_location", "suggestions": ["restaurants in Jakarta", "restaurants near me"]}}
- Input: "coffee shops in Kemang" -> {{"query_type": "good", "suggestions": []}}

Return ONLY valid JSON, no other text.
"""


@router.post("/query/enhance", response_model=QueryEnhanceResponse)
@limiter.limit("10/minute")
async def enhance_query(
    request: Request,
    body: QueryEnhanceRequest,
    auth_user: AuthUser = Depends(verify_supabase_token),
) -> QueryEnhanceResponse:
    """Analyze a query and suggest improvements.

    Requires authentication. Rate limited to 10 requests per minute per user.
    """
    # Store user_id in request state for rate limiter
    request.state.user_id = auth_user.user_id

    # Check if user is banned
    if db_service.is_configured():
        if db_service.is_user_banned(auth_user.user_id):
            logger.warning("banned_user_attempt", user_id=auth_user.user_id)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied. Your account has been restricted.",
            )

    # Sanitize input
    query = sanitize_query(body.query)

    # Skip if empty or too short
    if not query or len(query) < 2:
        return QueryEnhanceResponse(
            query_type="good",
            is_problematic=False,
        )

    # Skip if too long (after sanitization this shouldn't happen, but safety check)
    if len(query) > MAX_QUERY_LENGTH:
        logger.warning("query_too_long", length=len(query))
        return QueryEnhanceResponse(
            query_type="good",
            is_problematic=False,
        )

    try:
        llm = LLMClient()
        prompt = QUERY_ENHANCE_PROMPT.format(query=query)
        response = llm.generate(prompt, max_tokens=200, temperature=0.3)

        # Parse JSON response - handle potential markdown code blocks
        response_text = response.strip()
        if response_text.startswith("```"):
            # Remove markdown code block
            lines = response_text.split("\n")
            response_text = "\n".join(
                line for line in lines[1:-1] if not line.startswith("```")
            )

        data = json.loads(response_text)

        query_type = data.get("query_type", "good")
        suggestions = data.get("suggestions", [])

        # Validate query_type
        if query_type not in ["company", "category_no_location", "good"]:
            query_type = "good"

        # Sanitize suggestions (limit each suggestion length)
        sanitized_suggestions = [
            s[:100] for s in suggestions if isinstance(s, str)
        ][:3]

        is_problematic = query_type in ["company", "category_no_location"]

        message = None
        if query_type == "company":
            message = "This looks like a specific company name. Google Maps works better with business categories."
        elif query_type == "category_no_location":
            message = "Try adding a location for better results."

        return QueryEnhanceResponse(
            query_type=query_type,
            is_problematic=is_problematic,
            message=message,
            suggestions=sanitized_suggestions,
        )

    except Exception as e:
        logger.error("query_enhance_error", error=str(e))
        # Fallback: don't block the user
        return QueryEnhanceResponse(
            query_type="good",
            is_problematic=False,
        )
