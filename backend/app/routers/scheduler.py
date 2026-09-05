"""Scheduler router — capacity, queue, pause/unpause, health endpoints."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.deps import require_workspace
from app.services import scheduler as sched, flags

router = APIRouter(prefix="/scheduler", tags=["scheduler"])


class PauseBody(BaseModel):
    paused: bool = True


# ---------------------------------------------------------------- tick
@router.post("/tick")
def run_tick(user: dict = Depends(require_workspace)):
    result = sched.tick()
    return result


# ---------------------------------------------------------------- queue
@router.get("/queue")
def get_queue(user: dict = Depends(require_workspace)):
    import psycopg.rows
    import app.db as db
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        rows = conn.execute(
            """SELECT om.*, m.email AS mailbox_email
               FROM outbound_messages om
               LEFT JOIN mailboxes m ON m.id = om.assigned_mailbox_id
               WHERE om.status IN ('queued','scheduled')
               ORDER BY om.priority ASC, om.eligible_at ASC"""
        ).fetchall()
    # Convert datetimes to strings for JSON
    for r in rows:
        for k in ("eligible_at", "deadline", "scheduled_slot_at", "sent_at", "created_at", "updated_at"):
            if r.get(k):
                r[k] = str(r[k])
        if r.get("id"):
            r["id"] = str(r["id"])
        if r.get("lead_id"):
            r["lead_id"] = str(r["lead_id"])
        if r.get("assigned_mailbox_id"):
            r["assigned_mailbox_id"] = str(r["assigned_mailbox_id"])
    return {"messages": rows, "count": len(rows)}


# ---------------------------------------------------------------- pause mailbox
@router.post("/mailbox/{mailbox_id}/pause")
def pause_mailbox(mailbox_id: str, body: PauseBody = PauseBody(),
                  user: dict = Depends(require_workspace)):
    ks = _get_ks()
    if body.paused:
        ks.setdefault("pause_mailbox", {})[mailbox_id] = True
    else:
        ks.get("pause_mailbox", {}).pop(mailbox_id, None)
    flags.set_flag("kill_switches", ks, updated_by="api")
    return {"ok": True, "mailbox_id": mailbox_id, "paused": body.paused}


# ---------------------------------------------------------------- pause domain
@router.post("/domain/{domain_id}/pause")
def pause_domain(domain_id: str, body: PauseBody = PauseBody(),
                 user: dict = Depends(require_workspace)):
    ks = _get_ks()
    if body.paused:
        ks.setdefault("pause_domain", {})[domain_id] = True
    else:
        ks.get("pause_domain", {}).pop(domain_id, None)
    flags.set_flag("kill_switches", ks, updated_by="api")
    return {"ok": True, "domain_id": domain_id, "paused": body.paused}


# ---------------------------------------------------------------- pause campaign
@router.post("/campaign/{campaign_id}/pause")
def pause_campaign(campaign_id: str, body: PauseBody = PauseBody(),
                   user: dict = Depends(require_workspace)):
    ks = _get_ks()
    if body.paused:
        ks.setdefault("pause_campaign", {})[campaign_id] = True
    else:
        ks.get("pause_campaign", {}).pop(campaign_id, None)
    flags.set_flag("kill_switches", ks, updated_by="api")
    return {"ok": True, "campaign_id": campaign_id, "paused": body.paused}


# ---------------------------------------------------------------- health
@router.get("/health")
def get_health(user: dict = Depends(require_workspace)):
    import psycopg.rows
    import app.db as db
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        mailboxes = conn.execute(
            """SELECT m.id, m.email, m.health_score, m.health_state,
                      m.daily_send_limit, m.sent_today, m.status,
                      sd.domain
               FROM mailboxes m
               LEFT JOIN sending_domains sd ON sd.id = m.domain_id
               ORDER BY m.health_score ASC"""
        ).fetchall()

    for m in mailboxes:
        m["id"] = str(m["id"])

    capacity = sched.get_daily_capacity()
    return {"mailboxes": mailboxes, "capacity": capacity}


# ---------------------------------------------------------------- helpers
def _get_ks() -> dict:
    raw = flags.get_flag("kill_switches")
    if raw and isinstance(raw, dict):
        return dict(raw)
    return {
        "pause_all_sending": False,
        "pause_followups": False,
        "pause_ai_replies": False,
        "pause_hiring_campaigns": False,
        "pause_domain": {},
        "pause_mailbox": {},
        "pause_campaign": {},
    }
