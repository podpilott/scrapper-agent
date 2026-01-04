"""Query enhancement endpoint with security measures."""

import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from slowapi import Limiter
import jwt

from src.api.middleware.supabase_auth import AuthUser, verify_supabase_token
from src.api.schemas.responses import DuplicateCheckResponse, SimilarJob
from src.api.services.database import db_service, format_ban_remaining
from src.generators.llm import LLMClient
from src.utils.logger import get_logger

router = APIRouter()
logger = get_logger("query_route")


def get_user_id_for_limit(request: Request) -> str:
    """Extract user_id from JWT token for rate limiting.

    This runs BEFORE the endpoint function, so we need to decode the JWT manually.
    """
    try:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            # Decode without verification - just to get the user_id for rate limiting
            # The actual verification happens in verify_supabase_token
            payload = jwt.decode(token, options={"verify_signature": False})
            user_id = payload.get("sub")
            if user_id:
                # Store in request state for the custom 429 handler
                request.state.user_id = user_id
                return f"user:{user_id}"
    except Exception:
        pass
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


QUERY_ENHANCE_PROMPT = """You are a Google Maps search optimization expert for B2B lead generation.

Analyze this search query: "{query}"

CLASSIFICATION:
1. **company** - Specific company/brand name (e.g., "Starbucks", "Phincon", "Gojek")
   - Problem: Returns only 1 business, wastes scraping quota
   - Solution: Suggest the CATEGORY this company belongs to

2. **category_no_location** - Business category without location (e.g., "restaurants", "lawyers")
   - Problem: Google Maps returns random/nearby results, inconsistent data
   - Solution: Add specific location for targeted, high-quality leads

3. **good** - Category + location (e.g., "coffee shops in Kemang", "lawyers Bandung")
   - This is optimal for lead generation!

WHEN SUGGESTING ALTERNATIVES, BE STRATEGIC:
- For company names: What industry/category are they in? Suggest that category + likely location
- For no-location: Suggest popular Indonesian business districts (Kemang, Sudirman, Senopati, etc.)
- Think about what would yield the BEST B2B leads for sales outreach

Return JSON:
{{
  "query_type": "company" | "category_no_location" | "good",
  "suggestions": ["strategic suggestion 1", "strategic suggestion 2", "strategic suggestion 3"]
}}

Examples:
- "tokopedia" → {{"query_type": "company", "suggestions": ["e-commerce companies Jakarta", "tech startups Jakarta", "marketplace companies Indonesia"]}}
- "dentists" → {{"query_type": "category_no_location", "suggestions": ["dentists in Jakarta Selatan", "dental clinics Kemang", "dentists BSD City"]}}
- "web developers in Surabaya" → {{"query_type": "good", "suggestions": []}}

Return ONLY valid JSON."""


@router.post("/query/enhance", response_model=QueryEnhanceResponse)
@limiter.limit("20/minute")
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
        ban_info = db_service.get_user_ban_info(auth_user.user_id)
        if ban_info:
            remaining = format_ban_remaining(ban_info.get("expires_at"))
            logger.warning("banned_user_attempt", user_id=auth_user.user_id)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Your account has been restricted. Try again in {remaining}.",
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


# ============== Duplicate Query Check Endpoint ==============

QUERY_SUGGESTION_PROMPT = """You are a B2B lead generation strategist. A user has already searched for businesses using this query:

Original query: "{query}"
Their search history: {existing_queries}

Generate 3 STRATEGIC alternative queries to find NEW, UNTAPPED leads. Think creatively:

STRATEGIES TO CONSIDER:
1. **Upstream/Downstream**: Who supplies to or buys from these businesses?
   - "restaurants in Jakarta" → "food suppliers Jakarta" or "restaurant equipment suppliers Jakarta"

2. **Complementary Services**: What businesses work alongside them?
   - "lawyers in Bandung" → "notary public Bandung" or "accounting firms Bandung"

3. **Niche Specialization**: Break into specific sub-categories
   - "gyms in Surabaya" → "CrossFit boxes Surabaya" or "yoga studios Surabaya"

4. **Adjacent Locations**: Nearby areas they might have missed
   - "cafes in Kemang" → "cafes in Senopati" or "cafes in Cipete"

5. **Different Business Types**: Same need, different industry
   - "marketing agencies Jakarta" → "freelance marketing consultants Jakarta"

6. **Emerging Trends**: Modern variations of the category
   - "travel agencies Bali" → "tour guides Bali" or "travel influencers Bali"

RULES:
- Each suggestion must find DIFFERENT businesses (no overlap with original query)
- Keep it practical - must be searchable on Google Maps
- Include location for each suggestion
- Prioritize high-value B2B leads

Return ONLY a JSON array of 3 strings. Be creative and strategic!
Example: ["upstream supplier query", "complementary service query", "niche specialization query"]"""


def _generate_fallback_suggestions(query: str) -> list[str]:
    """Generate basic suggestions without LLM."""
    parts = query.lower().split(" in ")
    if len(parts) == 2:
        category, location = parts
        return [
            f"{category} near {location}",
            f"best {category} in {location}",
            f"{category} services in {location}",
        ]
    return []


def _generate_query_suggestions(query: str, similar_jobs: list[dict]) -> list[str]:
    """Use LLM to generate alternative query suggestions (with caching).

    Checks cache first. On cache miss, calls LLM and caches the result.
    Cache TTL is 7 days to reduce LLM API costs.
    """
    # Check cache first
    if db_service.is_configured():
        cached = db_service.get_cached_suggestions(query)
        if cached:
            logger.info("query_suggestions_cache_hit", query=query)
            return cached

    # Cache miss - generate with LLM
    existing_queries = [j["query"] for j in similar_jobs]

    prompt = QUERY_SUGGESTION_PROMPT.format(
        query=query,
        existing_queries=existing_queries,
    )

    try:
        llm = LLMClient()
        response = llm.generate(prompt, max_tokens=200, temperature=0.7)

        # Parse JSON response - handle potential markdown code blocks
        response_text = response.strip()
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(
                line for line in lines[1:-1] if not line.startswith("```")
            )

        suggestions = json.loads(response_text)
        if isinstance(suggestions, list):
            result = [s for s in suggestions if isinstance(s, str)][:3]

            # Cache the result for future queries
            if db_service.is_configured() and result:
                db_service.cache_suggestions(query, result)
                logger.info("query_suggestions_cached", query=query)

            return result
    except Exception as e:
        logger.warning("query_suggestion_failed", error=str(e))

    # Fallback: generate basic suggestions
    return _generate_fallback_suggestions(query)


@router.post("/query/check-duplicate", response_model=DuplicateCheckResponse)
@limiter.limit("20/minute")
async def check_duplicate_query(
    request: Request,
    body: QueryEnhanceRequest,
    auth_user: AuthUser = Depends(verify_supabase_token),
) -> DuplicateCheckResponse:
    """Check if query has similar jobs and suggest alternatives.

    Requires authentication. Rate limited to 20 requests per minute per user.
    """
    # Store user_id in request state for rate limiter
    request.state.user_id = auth_user.user_id

    # Check if user is banned
    if db_service.is_configured():
        ban_info = db_service.get_user_ban_info(auth_user.user_id)
        if ban_info:
            remaining = format_ban_remaining(ban_info.get("expires_at"))
            logger.warning("banned_user_dup_check_attempt", user_id=auth_user.user_id)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Your account has been restricted. Try again in {remaining}.",
            )

    # Sanitize input
    query = sanitize_query(body.query)

    if not query or len(query) < 2:
        return DuplicateCheckResponse(
            has_duplicates=False,
            similar_jobs=[],
            suggestions=[],
        )

    # Find similar jobs in database
    similar_jobs_data = []
    if db_service.is_configured():
        try:
            similar_jobs_data = db_service.find_similar_jobs(
                user_id=auth_user.user_id,
                query=query,
                limit=5,
            )
        except Exception as e:
            logger.warning("find_similar_jobs_error", error=str(e))

    if not similar_jobs_data:
        return DuplicateCheckResponse(
            has_duplicates=False,
            similar_jobs=[],
            suggestions=[],
        )

    # Convert to response models
    similar_jobs = [SimilarJob(**j) for j in similar_jobs_data]

    # Generate LLM suggestions for alternative queries
    suggestions = _generate_query_suggestions(query, similar_jobs_data)

    # Build message
    exact_match = any(j.match_type == "exact" for j in similar_jobs)
    if exact_match:
        message = "You've already searched for this exact query."
    else:
        message = "You have similar searches in your history."

    logger.info(
        "duplicate_query_check",
        user_id=auth_user.user_id,
        query=query,
        similar_count=len(similar_jobs),
        has_exact=exact_match,
    )

    return DuplicateCheckResponse(
        has_duplicates=True,
        similar_jobs=similar_jobs,
        suggestions=suggestions,
        message=message,
    )
