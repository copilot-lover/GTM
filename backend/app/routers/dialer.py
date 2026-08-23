from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from psycopg.rows import dict_row

import app.db as db
from app.core.deps import require_workspace
from app.services import twilio_service

router = APIRouter(prefix="/dialer", tags=["dialer"])


@router.get("/token")
def token(user: dict = Depends(require_workspace)):
    """Short-lived Twilio Voice access token for the browser (WebRTC)."""
    try:
        tok = twilio_service.access_token(f"user_{user['id']}")
    except twilio_service.TwilioError as e:
        raise HTTPException(503, str(e))
    return {"token": tok, "identity": f"user_{user['id']}"}


class CallIn(BaseModel):
    lead_id: str
    to_number: str
    operator_endpoint: str
    session_id: str | None = None
    prospect_tz: str | None = None


@router.post("/calls")
def place_call(req: CallIn, user: dict = Depends(require_workspace)):
    try:
        return twilio_service.place_call(
            workspace_id=user["workspace_id"],
            lead_id=req.lead_id,
            to_number=req.to_number,
            operator_endpoint=req.operator_endpoint,
            session_id=req.session_id,
            prospect_tz=req.prospect_tz,
        )
    except twilio_service.TwilioError as e:
        raise HTTPException(409, str(e))


@router.post("/twilio-webhook")
async def twilio_webhook(request: Request):
    """Status callbacks. Idempotent by CallSid."""
    form = await request.form()
    payload = {k: v for k, v in form.items()}
    return twilio_service.process_status_webhook(payload)


# ------------------------------------------------------------------ sessions

class SessionIn(BaseModel):
    name: str
    filters: dict = {}
    lead_ids: list[str] | None = None


@router.post("/sessions", status_code=201)
def create_session(req: SessionIn, user: dict = Depends(require_workspace)):
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        session = conn.execute(
            """INSERT INTO calling_sessions (workspace_id, name, filters, created_by)
               VALUES (%s,%s,%s,%s) RETURNING *""",
            (user["workspace_id"], req.name, db_json(req.filters), user["id"]),
        ).fetchone()
        if req.lead_ids:
            # session-level dedupe via PK; queue ordered by priority desc
            for order, lid in enumerate(req.lead_ids[:500], start=1):
                conn.execute(
                    """INSERT INTO session_leads (session_id, lead_id, queue_order)
                       VALUES (%s,%s,%s) ON CONFLICT DO NOTHING""",
                    (str(session["id"]), lid, order),
                )
    return session


@router.get("/sessions")
def list_sessions(user: dict = Depends(require_workspace)):
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        rows = conn.execute(
            """SELECT s.*, count(sl.lead_id) AS queue_size
               FROM calling_sessions s
               LEFT JOIN session_leads sl ON sl.session_id = s.id
               WHERE s.workspace_id=%s
               GROUP BY s.id ORDER BY s.created_at DESC LIMIT 100""",
            (user["workspace_id"],),
        ).fetchall()
    return {"items": rows}


@router.get("/sessions/{session_id}/queue")
def session_queue(session_id: str, user: dict = Depends(require_workspace)):
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        rows = conn.execute(
            """SELECT l.id AS lead_id, c.business_name, c.phone, c.city, c.state,
                      l.priority_score, sl.queue_order,
                      (SELECT disposition FROM calls ca
                        WHERE ca.lead_id=l.id AND ca.session_id=sl.session_id
                        ORDER BY created_at DESC LIMIT 1) AS last_disposition
               FROM session_leads sl
               JOIN leads l ON l.id = sl.lead_id
               JOIN companies c ON c.id = l.company_id
               WHERE sl.session_id=%s AND l.workspace_id=%s
               ORDER BY sl.queue_order""",
            (session_id, user["workspace_id"]),
        ).fetchall()
    return {"items": rows}


def db_json(value) -> str:
    import json

    return json.dumps(value)


class DispositionIn(BaseModel):
    disposition: str
    notes: str | None = None


@router.post("/calls/{call_id}/disposition")
def set_disposition(call_id: str, req: DispositionIn,
                    user: dict = Depends(require_workspace)):
    try:
        return twilio_service.set_disposition(
            user["workspace_id"], call_id, req.disposition, req.notes
        )
    except twilio_service.TwilioError as e:
        raise HTTPException(422, str(e))


@router.patch("/calls/{call_id}")
def edit_call(call_id: str, req: DispositionIn, user: dict = Depends(require_workspace)):
    """Post-hoc outcome editing (spec FR-15)."""
    return set_disposition(call_id, req, user)


@router.get("/call-log")
def call_log(limit: int = 50, offset: int = 0, user: dict = Depends(require_workspace)):
    limit = min(limit, 200)
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        total = conn.execute(
            "SELECT count(*) AS n FROM calls WHERE workspace_id=%s",
            (user["workspace_id"],),
        ).fetchone()["n"]
        rows = conn.execute(
            """SELECT ca.*, co.business_name FROM calls ca
               LEFT JOIN leads l ON l.id = ca.lead_id
               LEFT JOIN companies co ON co.id = l.company_id
               WHERE ca.workspace_id=%s
               ORDER BY ca.created_at DESC LIMIT %s OFFSET %s""",
            (user["workspace_id"], limit, offset),
        ).fetchall()
    return {"items": rows, "total": total}


@router.get("/kpis")
def kpis(user: dict = Depends(require_workspace)):
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        row = conn.execute(
            """SELECT
                 count(*) FILTER (WHERE called_at::date = now()::date) AS calls_today,
                 count(*) FILTER (WHERE called_at >= now() - interval '7 days') AS calls_week,
                 count(*) FILTER (WHERE called_at >= now() - interval '30 days') AS calls_month,
                 count(DISTINCT lead_id) FILTER (WHERE called_at::date = now()::date) AS unique_today,
                 count(*) FILTER (WHERE disposition LIKE 'connected%%'
                     AND called_at::date = now()::date) AS connected_today,
                 count(*) FILTER (WHERE called_at::date = now()::date) AS dial_attempts_today
               FROM calls WHERE workspace_id=%s""",
            (user["workspace_id"],),
        ).fetchone()
    connection_rate = (
        round(row["connected_today"] / row["dial_attempts_today"], 3)
        if row["dial_attempts_today"] else 0
    )
    return {**row, "connection_rate_today": connection_rate}
