from functools import lru_cache

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

    jwt_secret: str = "dev-only-secret"
    jwt_expires_minutes: int = 10080

    scraper_headless: bool = True
    scraper_stealth_mode: bool = True

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_from_name: str = "Orbit"

    ai_daily_budget_usd: float = 10.0


@lru_cache
def get_settings() -> Settings:
    import os

    env_file = ".env.prod" if os.environ.get("ORBIT_ENV_FILE") == "prod" else ".env"
    return Settings(_env_file=env_file)  # type: ignore[call-arg]
