import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from psycopg.rows import dict_row

import app.db as db
from app.core.deps import audit, require_workspace
from app.routers.companies import CompanyIn
from app.services import phones, scoring, state_machine
from app.services.suppression import add as add_suppression

router = APIRouter(prefix="/leads", tags=["leads"])

VALID_TRANSITIONS = state_machine.TRANSITIONS


class LeadIn(BaseModel):
    company: CompanyIn


class TransitionIn(BaseModel):
    to_status: str
    reason: str | None = None


def get_lead_or_404(conn, lead_id: str, workspace_id: str) -> dict:
    lead = conn.execute(
        "SELECT * FROM leads WHERE id=%s AND workspace_id=%s",
        (lead_id, workspace_id),
    ).fetchone()
    if lead is None:
        raise HTTPException(404, "lead not found")
    return lead


@router.post("", status_code=201)
def create_lead(req: LeadIn, user: dict = Depends(require_workspace)):
    """Manual lead creation with dedupe (CSV import lands here per row too)."""
    from app.routers.companies import create_company

    company_result = create_company(req.company, user)
    company_id = company_result["company"]["id"]
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        existing_lead = conn.execute(
            """SELECT id FROM leads WHERE workspace_id=%s AND company_id=%s LIMIT 1""",
            (user["workspace_id"], company_id),
        ).fetchone()
        if existing_lead:
            return {"id": existing_lead["id"], "deduped": True}
        lead = conn.execute(
            """INSERT INTO leads (workspace_id, company_id, source, source_url)
               VALUES (%s,%s,%s,%s) RETURNING *""",
            (user["workspace_id"], company_id, req.company.source, req.company.source_url),
        ).fetchone()
        conn.execute(
            """INSERT INTO activities (workspace_id, lead_id, type, summary, actor)
               VALUES (%s,%s,'system',%s,'system')""",
            (user["workspace_id"], lead["id"], f"Lead created via {req.company.source or 'manual'}"),
        )
        audit(
            conn,
            actor_type="user",
            actor_id=str(user["id"]),
            action="create",
            entity="lead",
            entity_id=str(lead["id"]),
            workspace_id=user["workspace_id"],
        )
    return {"id": lead["id"], **{k: v for k, v in lead.items() if k != "id"}, "deduped": False}


@router.get("")
def list_leads(
    status: str | None = None,
    fit_status: str | None = None,
    q: str | None = None,
    min_score: int | None = None,
    limit: int = 50,
    offset: int = 0,
    user: dict = Depends(require_workspace),
):
    limit = min(limit, 200)
    where = ["l.workspace_id = %s"]
    params: list = [user["workspace_id"]]
    if status:
        where.append("l.status = %s")
        params.append(status)
    if fit_status:
        where.append("l.fit_status = %s")
        params.append(fit_status)
    if min_score is not None:
        where.append("coalesce(l.lead_score,0) >= %s")
        params.append(min_score)
    if q:
        where.append("c.business_name ILIKE %s")
        params.append(f"%{q}%")
    total_where = " AND ".join(where)

    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        count = conn.execute(
            f"""SELECT count(*) AS n FROM leads l JOIN companies c ON c.id=l.company_id
                WHERE {total_where}""",
            tuple(params),
        ).fetchone()["n"]
        rows = conn.execute(
            f"""SELECT l.*, c.business_name, c.website, c.phone, c.city, c.state, c.vertical
                FROM leads l JOIN companies c ON c.id = l.company_id
                WHERE {total_where}
                ORDER BY coalesce(l.priority_score,0) DESC, l.created_at DESC
                LIMIT %s OFFSET %s""",
            tuple(params + [limit, offset]),
        ).fetchall()

    items = []
    for r in rows:
        tier = scoring.priority_tier(r["priority_score"]) if r["priority_score"] is not None else None
        items.append({**r, "priority_tier": tier})
    return {"items": items, "total": count, "limit": limit, "offset": offset}


@router.get("/{lead_id}")
def lead_detail(lead_id: str, user: dict = Depends(require_workspace)):
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        lead = conn.execute(
            """SELECT l.*, c.business_name, c.website, c.phone, c.city, c.state,
                      c.vertical, c.owner_name, c.owner_operator_confidence,
                      c.google_rating, c.review_count, c.number_of_locations,
                      c.tech_signals, c.address, c.zip
               FROM leads l JOIN companies c ON c.id = l.company_id
               WHERE l.id=%s AND l.workspace_id=%s""",
            (lead_id, user["workspace_id"]),
        ).fetchone()
        if lead is None:
            raise HTTPException(404, "lead not found")
        contact = None
        if lead["contact_id"]:
            contact = conn.execute(
                "SELECT * FROM contacts WHERE id=%s", (str(lead["contact_id"]),)
            ).fetchone()
        activities = conn.execute(
            """SELECT * FROM activities WHERE lead_id=%s ORDER BY created_at DESC LIMIT 100""",
            (lead_id,),
        ).fetchall()
        messages = conn.execute(
            """SELECT * FROM messages WHERE lead_id=%s ORDER BY created_at DESC LIMIT 50""",
            (lead_id,),
        ).fetchall()
        calls = conn.execute(
            """SELECT * FROM calls WHERE lead_id=%s ORDER BY created_at DESC LIMIT 50""",
            (lead_id,),
        ).fetchall()
        allowed = sorted(VALID_TRANSITIONS.get(lead["status"], set()))
    return {
        "lead": lead,
        "contact": contact,
        "activities": activities,
        "messages": messages,
        "calls": calls,
        "allowed_transitions": allowed,
    }


@router.post("/{lead_id}/transition")
def transition_lead(lead_id: str, req: TransitionIn, user: dict = Depends(require_workspace)):
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        lead = get_lead_or_404(conn, lead_id, user["workspace_id"])
        applied = state_machine.transition(
            conn, lead_id, user["workspace_id"], lead["status"], req.to_status
        )
        if not applied:
            raise HTTPException(409, "concurrent status change; reload and retry")
        if req.to_status == "do_not_call":
            company = conn.execute(
                "SELECT phone FROM companies WHERE id=%s", (str(lead["company_id"]),)
            ).fetchone()
            contact = (
                conn.execute(
                    "SELECT email FROM contacts WHERE id=%s", (str(lead["contact_id"]),)
                ).fetchone()
                if lead["contact_id"]
                else None
            )
            add_suppression(conn, workspace_id=user["workspace_id"], scope="company",
                            value=str(lead["company_id"]), reason="do_not_call disposition")
            if company and company["phone"]:
                add_suppression(conn, workspace_id=user["workspace_id"], scope="phone",
                                value=phones.normalize_phone(company["phone"]) or company["phone"],
                                reason="do_not_call disposition")
            if contact and contact["email"]:
                add_suppression(conn, workspace_id=user["workspace_id"], scope="email",
                                value=contact["email"], reason="do_not_call disposition")
        summary = f"status {lead['status']} -> {req.to_status}"
        if req.reason:
            summary += f" ({req.reason})"
        conn.execute(
            """INSERT INTO activities (workspace_id, lead_id, type, summary, actor)
               VALUES (%s,%s,'system',%s,'human')""",
            (user["workspace_id"], lead_id, summary),
        )
        audit(
            conn,
            actor_type="user",
            actor_id=str(user["id"]),
            action="transition",
            entity="lead",
            entity_id=lead_id,
            before_state={"status": lead["status"]},
            after_state={"status": req.to_status},
            workspace_id=user["workspace_id"],
        )
    return {"status": req.to_status}


class ScoreIn(BaseModel):
    signals: dict = {}
    unclear: bool = False


@router.post("/{lead_id}/score")
def score_lead(lead_id: str, req: ScoreIn, user: dict = Depends(require_workspace)):
    """Deterministic ICP scoring from detected signals; evidence recorded."""
    score, detail = scoring.icp_fit_score(req.signals)
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        lead = get_lead_or_404(conn, lead_id, user["workspace_id"])
        fit_status = scoring.fit_status_for(score, req.signals, req.unclear)
        priority = scoring.priority_score(
            intent=req.signals.get("intent", 0.0),
            fit=score / 10,
            contact_quality=req.signals.get("contact_quality", 0.5),
            history=req.signals.get("history", 0.0),
        )
        evidence = {**(lead["evidence"] or {}), "icp_signals": detail, "raw_score_total": score * 1.8}
        new_status = lead["status"]
        if lead["status"] == "new":
            target = "qualified" if fit_status == "qualified" else (
                "rejected" if fit_status.startswith("rejected") else lead["status"]
            )
            if state_machine.can_transition(new_status, target):
                state_machine.transition(conn, lead_id, user["workspace_id"], new_status, target)
                new_status = target
        conn.execute(
            """UPDATE leads SET lead_score=%s, fit_status=%s, priority_score=%s,
               evidence=%s, rejection_reason=COALESCE(%s, rejection_reason), updated_at=now()
               WHERE id=%s AND workspace_id=%s""",
            (
                score, fit_status, priority,
                json.dumps(evidence),
                fit_status if fit_status.startswith("rejected") else None,
                lead_id, user["workspace_id"],
            ),
        )
        review_reasons = []
        if fit_status == "borderline":
            review_reasons.append("borderline ICP score — human review required")
        conn.execute(
            "UPDATE leads SET review_reasons=%s::jsonb WHERE id=%s",
            (json.dumps(review_reasons) if review_reasons else "[]", lead_id),
        )
    return {"lead_score": score, "fit_status": fit_status, "priority_score": priority,
            "priority_tier": scoring.priority_tier(priority)}
