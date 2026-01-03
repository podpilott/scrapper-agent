"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import settings
from src.api.routes import demo, health, jobs, scrape
from src.api.services.job_manager import job_manager
from src.api.websocket.handler import router as websocket_router
from src.utils.logger import get_logger

logger = get_logger("app")


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
    app.include_router(scrape.router, prefix="/api", tags=["scrape"])
    app.include_router(jobs.router, prefix="/api", tags=["jobs"])
    app.include_router(websocket_router, tags=["websocket"])

    return app


# Create app instance for uvicorn
app = create_app()
