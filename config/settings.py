"""Application settings using Pydantic Settings."""

from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM API Keys
    openai_api_key: SecretStr | None = Field(default=None)
    anthropic_api_key: SecretStr | None = Field(default=None)
    deepseek_api_key: SecretStr | None = Field(default=None)

    # LLM Settings
    llm_provider: Literal["openai", "anthropic", "deepseek"] = Field(default="openai")
    llm_model: str = Field(default="gpt-4o-mini")

    # SerpAPI Settings (Google Maps scraping)
    serpapi_key: SecretStr | None = Field(default=None)
    serpapi_fetch_details: bool = Field(default=False)

    # Search API Settings (for company enrichment and contact discovery)
    tavily_api_key: SecretStr | None = Field(default=None)
    brave_api_key: SecretStr | None = Field(default=None)
    search_provider: Literal["tavily", "brave", "auto"] = Field(default="auto")

    # Lead Analysis Settings
    enable_lead_analysis: bool = Field(default=True)
    enable_company_enrichment: bool = Field(default=True)
    enable_contact_discovery: bool = Field(default=True)
    ideal_customer_profile: str = Field(default="")

    # Scraping Settings
    max_results_per_query: int = Field(default=50)
    requests_per_minute: int = Field(default=10)

    # Scoring Thresholds
    min_score_for_outreach: int = Field(default=50)
    hot_lead_threshold: int = Field(default=75)
    warm_lead_threshold: int = Field(default=50)

    # API Settings
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)
    cors_origins: list[str] = Field(default=["http://localhost:3000"])

    # Job Settings
    max_concurrent_jobs: int = Field(default=10)
    max_jobs_per_user: int = Field(default=1)
    job_ttl_hours: int = Field(default=24)
    job_timeout_minutes: int = Field(default=30)  # Auto-fail jobs running longer than this

    # User Request Limits (abuse prevention)
    default_max_results: int = Field(default=10)
    max_results_limit: int = Field(default=20)
    product_context_max_chars: int = Field(default=1000)

    # Supabase Settings
    supabase_url: str = Field(default="")
    supabase_anon_key: str = Field(default="")
    supabase_service_role_key: SecretStr | None = Field(default=None)
    supabase_jwt_secret: SecretStr | None = Field(default=None)


settings = Settings()
