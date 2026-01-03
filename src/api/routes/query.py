"""Query enhancement endpoint."""

import json

from fastapi import APIRouter
from pydantic import BaseModel

from src.generators.llm import LLMClient
from src.utils.logger import get_logger

router = APIRouter()
logger = get_logger("query_route")


class QueryEnhanceRequest(BaseModel):
    query: str


class QueryEnhanceResponse(BaseModel):
    query_type: str  # "company", "category_no_location", or "good"
    is_problematic: bool
    message: str | None = None
    suggestions: list[str] = []


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
async def enhance_query(request: QueryEnhanceRequest) -> QueryEnhanceResponse:
    """Analyze a query and suggest improvements."""
    query = request.query.strip()

    if not query:
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
            suggestions=suggestions[:3],  # Limit to 3
        )

    except Exception as e:
        logger.error("query_enhance_error", error=str(e))
        # Fallback: don't block the user
        return QueryEnhanceResponse(
            query_type="good",
            is_problematic=False,
        )
