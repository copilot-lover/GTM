"""Telegram notification endpoints."""

import logging

import psycopg.rows
from fastapi import APIRouter, Depends
from pydantic import BaseModel

import app.db as db
from app.core.deps import require_workspace
from app.services import telegram

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.post("/test")
def test_telegram(user: dict = Depends(require_workspace)):
    result = telegram.send_message("🔌 *Orbit GTM* — Telegram test message")
    return result


@router.get("/settings")
def get_settings(user: dict = Depends(require_workspace)):
    ts = telegram._get_settings()
    token_encrypted = ts.get("bot_token_encrypted")
    masked = None
    if token_encrypted:
        plain = telegram._decrypt_token(token_encrypted)
        if plain:
            masked = plain[:4] + "****" + plain[-4:] if len(plain) > 8 else "****"
    return {
        "bot_token": masked,
        "chat_id": ts.get("chat_id"),
        "enabled": ts.get("enabled", False),
        "notify_types": ts.get("notify_types") or {},
        "level": ts.get("level", "important"),
    }


class TelegramSettingsIn(BaseModel):
    bot_token: str | None = None
    chat_id: str | None = None
    enabled: bool | None = None
    notify_types: dict | None = None
    level: str | None = None


@router.post("/settings")
def update_settings(req: TelegramSettingsIn, user: dict = Depends(require_workspace)):
    updates = []
    params = []
    if req.bot_token is not None:
        encrypted = telegram._encrypt_token(req.bot_token)
        updates.append("bot_token_encrypted = %s")
        params.append(encrypted)
    if req.chat_id is not None:
        updates.append("chat_id = %s")
        params.append(req.chat_id)
    if req.enabled is not None:
        updates.append("enabled = %s")
        params.append(req.enabled)
    if req.notify_types is not None:
        import json
        updates.append("notify_types = %s")
        params.append(json.dumps(req.notify_types))
    if req.level is not None:
        updates.append("level = %s")
        params.append(req.level)

    if updates:
        updates.append("updated_at = now()")
        with db.get_pool().connection() as conn:
            conn.execute(
                f"""INSERT INTO telegram_settings (id) VALUES (true)
                    ON CONFLICT (id) DO NOTHING"""
            )
            conn.execute(
                f"""UPDATE telegram_settings SET {', '.join(updates)} WHERE id=true""",
                tuple(params),
            )
    return {"ok": True}


@router.post("/digest")
def trigger_digest(user: dict = Depends(require_workspace)):
    from app.services.mailbox_health import DAILY_GTM_HEALTH_AUDIT

    report = DAILY_GTM_HEALTH_AUDIT()
    result = telegram.send_message(telegram.format_daily_digest(report))
    return {"ok": result.get("ok", False), "report": report}
