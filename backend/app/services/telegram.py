"""Telegram notification service.

Encrypted bot token storage via Fernet, message formatting helpers,
and event-driven notification dispatch.
"""

import logging
from datetime import datetime, timezone

import httpx
import psycopg.rows

import app.db as db
from app.config import get_settings

logger = logging.getLogger(__name__)

_LEVEL_WEIGHTS = {"all": 0, "important": 1, "critical": 2}
_SEVERITY_WEIGHTS = {"info": 0, "attention": 1, "warning": 2, "critical": 3}


def _get_settings() -> dict:
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        row = conn.execute("SELECT * FROM telegram_settings WHERE id=true").fetchone()
    return row or {}


def _decrypt_token(encrypted: str | None) -> str | None:
    if not encrypted:
        return None
    settings = get_settings()
    if not settings.app_secret:
        logger.warning("app_secret not set, cannot decrypt telegram token")
        return None
    try:
        from cryptography.fernet import Fernet

        return Fernet(settings.app_secret.encode()).decrypt(encrypted.encode()).decode()
    except Exception as e:
        logger.error("Failed to decrypt telegram token: %s", e)
        return None


def _encrypt_token(plaintext: str) -> str:
    settings = get_settings()
    if not settings.app_secret:
        logger.warning("app_secret not set, storing telegram token unencrypted")
        return plaintext
    from cryptography.fernet import Fernet

    return Fernet(settings.app_secret.encode()).encrypt(plaintext.encode()).decode()


def send_message(text: str, parse_mode: str = "Markdown") -> dict:
    ts = _get_settings()
    if not ts.get("enabled"):
        return {"ok": False, "error": "telegram disabled"}
    token = _decrypt_token(ts.get("bot_token_encrypted"))
    if not token:
        return {"ok": False, "error": "no valid token"}
    chat_id = ts.get("chat_id")
    if not chat_id:
        return {"ok": False, "error": "no chat_id"}
    try:
        resp = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
            timeout=10,
        )
        data = resp.json()
        return {"ok": data.get("ok", False), "error": data.get("description")}
    except Exception as e:
        logger.error("Telegram send failed: %s", e)
        return {"ok": False, "error": str(e)}


def format_meeting_booked(lead: dict, signal: dict, meeting: dict) -> str:
    company = lead.get("business_name", "Unknown")
    contact = lead.get("contact_name", "")
    scheduled = meeting.get("scheduled_at", "")
    return (
        f"📅 *Meeting Booked*\n"
        f"Company: {company}\n"
        f"Contact: {contact}\n"
        f"Scheduled: {scheduled}"
    )


def format_hot_lead(lead: dict, score: int, signal: dict) -> str:
    company = lead.get("business_name", "Unknown")
    role = signal.get("role_category", "")
    return (
        f"🔥 *Hot Lead*\n"
        f"Company: {company}\n"
        f"Score: {score}\n"
        f"Signal: {role}"
    )


def format_alert(alert: dict) -> str:
    severity = alert.get("severity", "info")
    message = alert.get("message", "")
    icon = {"critical": "🚨", "warning": "⚠️", "attention": "👀", "info": "ℹ️"}.get(severity, "")
    return f"{icon} *Alert [{severity}]*\n{message}"


def format_daily_digest(audit_report: dict) -> str:
    score = audit_report.get("overall_score", "N/A")
    problems = audit_report.get("problems", [])
    lines = [f"📊 *Daily Digest*\nOverall Score: {score}"]
    if problems:
        lines.append("Problems:")
        for p in problems[:5]:
            domain = p.get("domain", "")
            issues = ", ".join(p.get("dns_issues", []))
            lines.append(f"  • {domain}: {issues}")
    return "\n".join(lines)


def event_hook(event_type: str, data: dict) -> None:
    ts = _get_settings()
    if not ts.get("enabled"):
        return
    notify_types = ts.get("notify_types") or {}
    if not notify_types.get(event_type, False):
        return
    level = ts.get("level", "important")
    level_w = _LEVEL_WEIGHTS.get(level, 1)
    severity = data.get("severity", "info")
    severity_w = _SEVERITY_WEIGHTS.get(severity, 0)
    if severity_w < level_w:
        return
    formatters = {
        "meeting_booked": lambda d: format_meeting_booked(
            d.get("lead", {}), d.get("signal", {}), d.get("meeting", {})
        ),
        "positive_reply": lambda d: f"✉️ *Positive Reply*\n{d.get('summary', '')}",
        "hot_lead": lambda d: format_hot_lead(
            d.get("lead", {}), d.get("score", 0), d.get("signal", {})
        ),
        "alert_critical": lambda d: format_alert(d.get("alert", {})),
        "alert_warning": lambda d: format_alert(d.get("alert", {})),
        "daily_digest": lambda d: format_daily_digest(d.get("report", {})),
    }
    formatter = formatters.get(event_type)
    if formatter:
        send_message(formatter(data))
