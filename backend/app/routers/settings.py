"""Settings management endpoints — read/write .env config from the UI."""

import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.core.deps import require_workspace

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["settings"])

# Resolve .env path relative to the backend directory (where uvicorn runs)
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def _read_env() -> dict[str, str]:
    """Parse .env into an ordered dict of KEY=VALUE (no comments, no blanks)."""
    env: dict[str, str] = {}
    if not _ENV_FILE.exists():
        return env
    for line in _ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


def _write_env(data: dict[str, str]) -> None:
    """Write the full dict back to .env as KEY=VALUE lines."""
    lines = [f"{k}={v}" for k, v in data.items()]
    _ENV_FILE.write_text("\n".join(lines) + "\n")


def _mask(value: str | None) -> str:
    """Return a safe display string for secret values."""
    return "***set***" if value else "not set"


def _require_owner(user: dict) -> dict:
    if user.get("role") != "owner":
        raise HTTPException(403, "only owners can modify settings")
    return user


# ── GET /api/settings ────────────────────────────────────────────────


@router.get("")
def get_all_settings(user: dict = Depends(require_workspace)):
    _require_owner(user)
    s = get_settings()
    return {
        "providers": {
            "llm_api_key": _mask(s.llm_api_key),
            "llm_model_chain": s.llm_model_chain,
            "ai_daily_budget_usd": s.ai_daily_budget_usd,
        },
        "smtp": {
            "smtp_host": s.smtp_host,
            "smtp_port": s.smtp_port,
            "smtp_user": s.smtp_user,
            "smtp_from_email": s.smtp_from_email,
            "smtp_from_name": s.smtp_from_name,
            "orbit_physical_address": s.orbit_physical_address,
            "smtp_password": _mask(s.smtp_password),
        },
        "scraper": {
            "scraper_headless": s.scraper_headless,
            "scraper_stealth_mode": s.scraper_stealth_mode,
        },
    }


# ── PUT /api/settings/providers ──────────────────────────────────────


class ProviderSettingsIn(BaseModel):
    llm_api_key: str | None = None
    llm_model_chain: str | None = None
    ai_daily_budget_usd: float | None = None


@router.put("/providers")
def update_provider_settings(
    req: ProviderSettingsIn, user: dict = Depends(require_workspace)
):
    _require_owner(user)
    env = _read_env()
    keys_updated: list[str] = []

    if req.llm_api_key is not None:
        env["LLM_API_KEY"] = req.llm_api_key
        keys_updated.append("LLM_API_KEY")
    if req.llm_model_chain is not None:
        env["LLM_MODEL_CHAIN"] = req.llm_model_chain
        keys_updated.append("LLM_MODEL_CHAIN")
    if req.ai_daily_budget_usd is not None:
        env["AI_DAILY_BUDGET_USD"] = str(req.ai_daily_budget_usd)
        keys_updated.append("AI_DAILY_BUDGET_USD")

    if not keys_updated:
        return {"ok": True, "updated": []}

    _write_env(env)
    get_settings.cache_info()
    get_settings.cache_clear()
    logger.info("settings updated: %s", keys_updated)
    return {"ok": True, "updated": keys_updated}


# ── PUT /api/settings/smtp ───────────────────────────────────────────


class SmtpSettingsIn(BaseModel):
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_from_name: str | None = None
    orbit_physical_address: str | None = None


@router.put("/smtp")
def update_smtp_settings(
    req: SmtpSettingsIn, user: dict = Depends(require_workspace)
):
    _require_owner(user)
    env = _read_env()
    keys_updated: list[str] = []

    mapping = {
        "smtp_host": "SMTP_HOST",
        "smtp_port": "SMTP_PORT",
        "smtp_user": "SMTP_USER",
        "smtp_password": "SMTP_PASSWORD",
        "smtp_from_email": "SMTP_FROM_EMAIL",
        "smtp_from_name": "SMTP_FROM_NAME",
        "orbit_physical_address": "ORBIT_PHYSICAL_ADDRESS",
    }
    for field, env_key in mapping.items():
        value = getattr(req, field)
        if value is not None:
            env[env_key] = str(value)
            keys_updated.append(env_key)

    if not keys_updated:
        return {"ok": True, "updated": []}

    _write_env(env)
    get_settings.cache_clear()
    logger.info("smtp settings updated: %s", keys_updated)
    return {"ok": True, "updated": keys_updated}


# ── PUT /api/settings/scraper ────────────────────────────────────────


class ScraperSettingsIn(BaseModel):
    scraper_headless: bool | None = None
    scraper_stealth_mode: bool | None = None


@router.put("/scraper")
def update_scraper_settings(
    req: ScraperSettingsIn, user: dict = Depends(require_workspace)
):
    _require_owner(user)
    env = _read_env()
    keys_updated: list[str] = []

    if req.scraper_headless is not None:
        env["SCRAPER_HEADLESS"] = str(req.scraper_headless).lower()
        keys_updated.append("SCRAPER_HEADLESS")
    if req.scraper_stealth_mode is not None:
        env["SCRAPER_STEALTH_MODE"] = str(req.scraper_stealth_mode).lower()
        keys_updated.append("SCRAPER_STEALTH_MODE")

    if not keys_updated:
        return {"ok": True, "updated": []}

    _write_env(env)
    get_settings.cache_clear()
    logger.info("scraper settings updated: %s", keys_updated)
    return {"ok": True, "updated": keys_updated}
