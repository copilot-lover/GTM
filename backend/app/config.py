from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    orbit_env: str = "dev"
    app_host: str = "127.0.0.1"
    app_port: int = 8100

    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_db: str = "orbit"
    postgres_user: str = "orbit"
    postgres_password: str = ""

    jwt_secret: str = ""
    jwt_expires_minutes: int = 10080

    # Outbound safety — overnight dry-run enforcement (Phase 11)
    # When true, email_service.claim_for_send still gates but apply_send_result never hits real SMTP
    outbound_dry_run: bool = True
    outbound_allow_real_send: bool = False

    scraper_headless: bool = True
    scraper_stealth_mode: bool = True

    # CORS origins (comma-separated for multiple)
    cors_origins: str = "http://localhost:8100,http://127.0.0.1:8100"

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_from_name: str = "Orbit"
    orbit_physical_address: str = ""

    ai_daily_budget_usd: float = 10.0

    # --- In-app provider layer ---
    # Ordered LLM fallback chain (first successful model wins).
    # Verified free 2026-08-31: liquid row is strictest for fallback testing.
    llm_model_chain: str = (
        "nvidia/nemotron-3-super-120b-a12b:free,"
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free,"
        "z-ai/glm-5.2:free"
    )
    llm_api_key: str = Field(default="", validation_alias=AliasChoices(
        "LLM_API_KEY", "OPENROUTER_API_KEY"))

    # --- Background workers (in-process job queue) ---
    workers_enabled: bool = False
    worker_pools_json: str = (
        '{"ai":2,"enrichment":2,"verification":2,"outbound":2,'
        '"discovery":1,"meeting":1}'
    )
    # Optional per-provider in-flight caps, e.g. {"openrouter":4}
    provider_concurrency_json: str = "{}"

    # Fernet key material for encrypting secrets at rest (telegram bot token).
    app_secret: str = ""

    # --- GTM agent layer ---
    # Copy-generation retry loop ceiling before a draft is HELD for human review.
    gtm_copy_max_attempts: int = 3
    # Default agent cadences (seconds), overridable via env JSON.
    gtm_agent_schedules_json: str = (
        '{"GTM_INTENT": 900, "GTM_QA": 3600, "GTM_LEADS": 86400, '
        '"GTM_OUTBOUND": 60, "GTM_REPLIES": 300}'
    )

    @property
    def gtm_agent_schedules(self) -> dict[str, int]:
        import json
        return json.loads(self.gtm_agent_schedules_json)

    @property
    def llm_model_chain_list(self) -> list[str]:
        return [m.strip() for m in self.llm_model_chain.split(",") if m.strip()]


@lru_cache
def get_settings() -> Settings:
    import os

    env_file = ".env.prod" if os.environ.get("ORBIT_ENV_FILE") == "prod" else ".env"
    return Settings(_env_file=env_file)  # type: ignore[call-arg]
