from fastapi import APIRouter, Depends, HTTPException
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


@router.get("/due-sends")
def due_sends(user: dict = Depends(require_workspace)):
    """n8n polls this; each message must pass POST /claim before transport."""
    return {"items": email_service.due_sends(user["workspace_id"])}


class ClaimIn(BaseModel):
    idempotency_key: str | None = None


@router.post("/claim/{message_id}")
def claim(message_id: str, req: ClaimIn, user: dict = Depends(require_workspace)):
    """Gates + atomic claim; returns the payload for n8n's Send Email node."""
    try:
        return email_service.claim_for_send(
            user["workspace_id"], message_id, req.idempotency_key
        )
    except email_service.SendBlocked as e:
        raise HTTPException(409, str(e))


class SendResultIn(BaseModel):
    ok: bool
    provider_message_id: str | None = None
    error: str | None = None


@router.post("/apply/send-result")
def apply_send_result(message_id: str, req: SendResultIn,
                      user: dict = Depends(require_workspace)):
    """n8n reports transport outcome; backend owns resulting state."""
    try:
        return email_service.apply_send_result(
            user["workspace_id"], message_id,
            ok=req.ok, provider_message_id=req.provider_message_id,
            error=req.error,
        )
    except email_service.SendBlocked as e:
        raise HTTPException(409, str(e))


@router.get("/messages/{message_id}/send-decision")
def send_decision(message_id: str, user: dict = Depends(require_workspace)):
    """Full structural gate evaluation for this message (auditable)."""
    from app.services import outbound_gate

    return outbound_gate.can_send(user["workspace_id"], message_id)


@router.get("/messages/{message_id}/why")
def why(message_id: str, user: dict = Depends(require_workspace)):
    """Stage history + latest QA runs + send decision for the Why panel."""
    from app.services import gtm_lifecycle, outbound_gate

    ws = user["workspace_id"]
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        latest_qa = conn.execute(
            """SELECT DISTINCT ON (object_type)
                      object_type, status, score, findings, failed_rules,
                      attempt, created_at
               FROM qa_runs
               WHERE workspace_id=%s AND object_id=%s
                     AND object_type IN ('copy','compliance')
               ORDER BY object_type, created_at DESC""",
            (ws, message_id),
        ).fetchall()
    return {
        "stage_history": gtm_lifecycle.stage_history(ws, message_id),
        "latest_qa": latest_qa,
        "send_decision": outbound_gate.can_send(ws, message_id),
    }


class ReviewReplyIn(BaseModel):
    lead_id: str
    text: str


@router.post("/classify-reply")
def classify_reply_route(req: ReviewReplyIn, user: dict = Depends(require_workspace)):
    """Durable intake: persists reply, fires kill switch, emits reply.received
    for n8n classification. Never calls an LLM inline."""
    return email_service.classify_reply(user["workspace_id"], req.lead_id, req.text)


class ClassificationIn(BaseModel):
    lead_id: str
    intent_class: str
    confidence: float = 0.0
    suggested_response: str | None = None


@router.post("/apply/classification")
def apply_classification(req: ClassificationIn,
                         user: dict = Depends(require_workspace)):
    """n8n posts the LLM classification result; backend owns routing."""
    return email_service.apply_classification(
        user["workspace_id"], req.lead_id,
        intent_class=req.intent_class,
        confidence=req.confidence,
        suggested_response=req.suggested_response,
    )
