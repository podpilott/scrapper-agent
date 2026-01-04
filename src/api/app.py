"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from config.settings import settings
from src.api.routes import demo, health, jobs, query, scrape, stream
from src.api.services.database import db_service
from src.api.services.job_manager import job_manager
from src.utils.logger import get_logger

logger = get_logger("app")

# Rate limiter instance
limiter = Limiter(key_func=get_remote_address)


async def custom_rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Custom rate limit handler with auto-ban support.

    Records violations and triggers progressive bans for repeat offenders.
    """
    user_id = getattr(request.state, "user_id", None)

    if user_id and db_service.is_configured():
        try:
            # Record violation
            db_service.record_rate_limit_violation(user_id, request.url.path)

            # Check if should auto-ban
            was_banned = db_service.check_and_auto_ban(user_id)
            if was_banned:
                logger.warning(
                    "user_auto_banned_on_rate_limit",
                    user_id=user_id,
                    endpoint=request.url.path,
                )
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "Account temporarily restricted due to excessive requests. "
                        "Please try again later."
                    },
                )
        except Exception as e:
            # Don't fail the request on DB errors
            logger.error("rate_limit_handler_error", error=str(e))

    # Standard 429 response
    retry_after = getattr(exc, "retry_after", 60)
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Please slow down."},
        headers={"Retry-After": str(retry_after)},
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("app_starting")

    # Recover any orphaned jobs from previous run
    recovered = await job_manager.recover_stale_jobs()
    if recovered:
        logger.info("orphaned_jobs_recovered", count=recovered)

    job_manager.start_cleanup_task()
    logger.info("app_started")
    yield
    # Shutdown
    logger.info("app_shutting_down")
    job_manager.stop_cleanup_task()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Lead Scraper API",
        description="Google Maps lead generation with real-time streaming",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Rate limiter with custom handler for auto-ban
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, custom_rate_limit_handler)

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(demo.router, prefix="/api", tags=["demo"])
    app.include_router(query.router, prefix="/api", tags=["query"])
    app.include_router(scrape.router, prefix="/api", tags=["scrape"])
    app.include_router(jobs.router, prefix="/api", tags=["jobs"])
    app.include_router(stream.router, prefix="/api", tags=["stream"])

    return app


# Create app instance for uvicorn
app = create_app()
