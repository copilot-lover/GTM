from fastapi import APIRouter, Depends
from pydantic import BaseModel
from psycopg.rows import dict_row

import app.db as db
from app.core.deps import require_workspace
from app.services import email_service

router = APIRouter(prefix="/outreach", tags=["outreach"])


@router.get("/approvals")
def approval_queue(user: dict = Depends(require_workspace)):
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        rows = conn.execute(
            """SELECT m.id, m.subject, m.body_text, m.created_at,
                      l.id AS lead_id, c.business_name, c.city, c.state,
                      l.primary_pain, l.recommended_offer
               FROM messages m
               JOIN leads l ON l.id = m.lead_id
               JOIN companies c ON c.id = l.company_id
               WHERE m.workspace_id=%s AND m.status='pending_approval'
               ORDER BY m.created_at""",
            (user["workspace_id"],),
        ).fetchall()
    return {"items": rows}


class ApproveIn(BaseModel):
    message_ids: list[str]
    action: str  # approve | reject
    reason: str | None = None


@router.post("/approvals")
def bulk_approve(req: ApproveIn, user: dict = Depends(require_workspace)):
    results = []
    for mid in req.message_ids[:100]:
        try:
            if req.action == "approve":
                email_service.approve(user["workspace_id"], mid, str(user["id"]))
            else:
                email_service.reject(user["workspace_id"], mid, req.reason)
            results.append({"message_id": mid, "ok": True})
        except email_service.SendBlocked as e:
            results.append({"message_id": mid, "ok": False, "error": str(e)})
    return {"results": results}


@router.post("/send/{message_id}")
def send_now(message_id: str, user: dict = Depends(require_workspace)):
    outcome = email_service.send_approved(user["workspace_id"], message_id)
    return outcome


@router.post("/process-cadence")
def process_cadence(user: dict = Depends(require_workspace)):
    """n8n schedule trigger hits this with a service token."""
    return email_service.process_cadence(user["workspace_id"])


class ReviewReplyIn(BaseModel):
    lead_id: str
    text: str


@router.post("/classify-reply")
def classify_reply_route(req: ReviewReplyIn, user: dict = Depends(require_workspace)):
    return email_service.classify_reply(
        user["workspace_id"],
        req.lead_id,
        req.text,
    )
