"""GTM agent control-plane router: scheduler tick, agent dashboard,
run history, message stage history, intent why-panel and re-evaluation."""

import logging

import psycopg.rows
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import app.db as db
from app.agents import ledger, registry
from app.core.deps import require_workspace

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/gtm", tags=["gtm"])


def _row_factory(conn):
    conn.row_factory = psycopg.rows.dict_row


def _query(sql: str, params: tuple = ()) -> list[dict]:
    with db.get_pool().connection() as conn:
        _row_factory(conn)
        return conn.execute(sql, params).fetchall()


def _query_one(sql: str, params: tuple = ()) -> dict | None:
    with db.get_pool().connection() as conn:
        _row_factory(conn)
        return conn.execute(sql, params).fetchone()


# ── POST /scheduler/tick ─────────────────────────────────────────────────────

@router.post("/scheduler/tick")
def scheduler_tick(user: dict = Depends(require_workspace)):
    from app.agents import scheduler as agent_scheduler

    agent_scheduler.ensure_default_schedules()
    return agent_scheduler.tick()


# ── GET /agents ──────────────────────────────────────────────────────────────

@router.get("/agents")
def list_agents(user: dict = Depends(require_workspace)):
    registry.ensure_registered()

    schedules = {
        s["agent"]: s
        for s in _query("SELECT * FROM agent_schedules ORDER BY agent")
    }
    health = {h["agent"]: h for h in ledger.agent_health()}

    agents = []
    for name, spec in registry.AGENTS.items():
        s = schedules.get(name, {})
        h = health.get(name, {})
        agents.append({
            "agent": name,
            "capabilities": sorted(spec["capabilities"]),
            "cannot_send": spec.get("cannot_send", True),
            "task_type": s.get("task_type"),
            "pool": s.get("pool"),
            "schedule_seconds": s.get("schedule_seconds"),
            "enabled": s.get("enabled"),
            "last_run": s.get("last_run") or h.get("last_run_at"),
            "next_run": s.get("next_run"),
            "last_status": s.get("last_status") or h.get("last_status"),
            "last_error": s.get("last_error") or h.get("last_error"),
            "avg_latency_ms": h.get("avg_latency_ms"),
            "tokens_24h": h.get("tokens_24h"),
            "successes_24h": h.get("successes_24h"),
            "failures_24h": h.get("failures_24h"),
        })
    return {"agents": agents}


# ── GET /agents/{agent}/runs ─────────────────────────────────────────────────

@router.get("/agents/{agent}/runs")
def agent_runs(agent: str, limit: int = 20,
               user: dict = Depends(require_workspace)):
    if agent not in registry.AGENTS:
        raise HTTPException(404, f"unknown agent: {agent}")
    rows = _query(
        """SELECT id, workspace_id, trigger, input_ref, output_ref, status,
                  confidence, tokens_in, tokens_out, cost_usd, latency_ms,
                  error, started_at, finished_at
           FROM agent_runs WHERE agent_name=%s
           ORDER BY started_at DESC LIMIT %s""",
        (agent, max(1, min(limit, 200))),
    )
    return {"agent": agent, "runs": rows}


# ── GET /messages/{message_id}/stage-history ─────────────────────────────────

@router.get("/messages/{message_id}/stage-history")
def stage_history(message_id: str, user: dict = Depends(require_workspace)):
    from app.services import gtm_lifecycle

    return {"message_id": message_id,
            "history": gtm_lifecycle.stage_history(
                str(user["workspace_id"]), message_id)}


# ── POST /messages/{message_id}/qa/* ────────────────────────────────────────

class ResubmitBody(BaseModel):
    subject: str | None = None
    first_sentence: str | None = None
    body: str | None = None
    cta: str | None = None
    claims: list | None = None
    evidence_refs: list | None = None


@router.post("/messages/{message_id}/qa/copy")
def qa_copy(message_id: str, user: dict = Depends(require_workspace)):
    from app.services import qa_service

    try:
        registry.assert_capability("GTM_QA", "write_qa_decisions")
        return qa_service.run_copy_qa(str(user["workspace_id"]), message_id)
    except registry.PermissionDenied as exc:
        raise HTTPException(403, str(exc))


@router.post("/messages/{message_id}/qa/compliance")
def qa_compliance(message_id: str, user: dict = Depends(require_workspace)):
    from app.services import qa_service

    try:
        registry.assert_capability("GTM_QA", "write_qa_decisions")
        return qa_service.run_compliance_qa(str(user["workspace_id"]), message_id)
    except registry.PermissionDenied as exc:
        raise HTTPException(403, str(exc))
    except qa_service.QAError as exc:
        raise HTTPException(409, f"compliance QA cannot run: {exc}")


@router.post("/messages/{message_id}/qa/resubmit")
def qa_resubmit(message_id: str, parsed: ResubmitBody,
                user: dict = Depends(require_workspace)):
    from app.services import qa_service

    try:
        registry.assert_capability("GTM_COPY", "write_drafts")
        return qa_service.resubmit_copy(
            str(user["workspace_id"]), message_id, parsed.model_dump(exclude_none=True))
    except registry.PermissionDenied as exc:
        raise HTTPException(403, str(exc))
    except qa_service.QAError as exc:
        raise HTTPException(409, f"resubmit not possible: {exc}")


# ── GET /leads/{lead_id}/why ─────────────────────────────────────────────────

@router.get("/leads/{lead_id}/why")
def lead_why(lead_id: str, user: dict = Depends(require_workspace)):
    ws = user["workspace_id"]
    lead = _query_one(
        """SELECT l.id, l.priority_score, l.company_id
           FROM leads l WHERE l.id=%s AND l.workspace_id=%s""",
        (lead_id, ws),
    )
    if not lead:
        raise HTTPException(404, "lead not found")

    # Newest GTM_INTENT opportunity score; fall back to newest opportunity score.
    row = _query_one(
        """SELECT score, tier, components, recommended_action
           FROM scores
           WHERE lead_id=%s AND score_type='opportunity'
             AND components->>'source'='GTM_INTENT'
           ORDER BY computed_at DESC LIMIT 1""",
        (lead_id,),
    ) or _query_one(
        """SELECT score, tier, components, recommended_action
           FROM scores
           WHERE lead_id=%s AND score_type='opportunity'
           ORDER BY computed_at DESC LIMIT 1""",
        (lead_id,),
    )

    contributions: list[dict] = []
    components = (row or {}).get("components") or {}
    raw = components.get("contributions")
    if isinstance(raw, list):
        contributions.extend(raw)
    else:
        contributions.extend(
            {"component": k, "value": v} for k, v in components.items()
            if k != "source"
        )

    signals = _query(
        """SELECT role_category, signal_score, status, discovered_at
           FROM hiring_signals
           WHERE company_id=%s AND workspace_id=%s AND status='active'
           ORDER BY signal_score DESC NULLS LAST""",
        (lead["company_id"], ws),
    )
    contributions.extend(
        {"component": "hiring_signal", "value": s["role_category"],
         "signal_score": s["signal_score"]}
        for s in signals
    )

    return {
        "score": row.get("score") if row else None,
        "priority": lead.get("priority_score"),
        "contributions": contributions,
    }


# ── POST /leads/{lead_id}/reevaluate ─────────────────────────────────────────

@router.post("/leads/{lead_id}/reevaluate")
def lead_reevaluate(lead_id: str, user: dict = Depends(require_workspace)):
    try:
        from app.services import intent_engine
    except ImportError:
        raise HTTPException(503, "intent_engine not ready")
    reevaluate = getattr(intent_engine, "reevaluate_lead", None)
    if reevaluate is None:
        raise HTTPException(503, "intent_engine not ready")

    lead = _query_one(
        "SELECT id FROM leads WHERE id=%s AND workspace_id=%s",
        (lead_id, user["workspace_id"]),
    )
    if not lead:
        raise HTTPException(404, "lead not found")
    return {"lead_id": lead_id,
            "result": reevaluate(str(user["workspace_id"]), lead_id)}
