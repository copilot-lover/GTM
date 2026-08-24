"""Orchestration endpoints for n8n (spec §10.3).

n8n owns all external work: it fetches stage context, runs Scrapling + LLM,
and posts deterministic results back here. The backend validates, applies
state transitions, and emits the next event. Retries/DLQ are n8n's job.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.deps import require_workspace
from app.services import events, llm, pipeline

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


class RunIn(BaseModel):
    lead_ids: list[str]


@router.post("/run")
def run(req: RunIn, user: dict = Depends(require_workspace)):
    """Queue leads into the intelligence chain by emitting the first event.
    n8n picks up lead.qualification_requested and drives all external work."""
    results = []
    for lead_id in req.lead_ids[:100]:
        try:
            results.append(pipeline.request_qualification(user["workspace_id"], lead_id))
        except pipeline.PipelineError as e:
            results.append({"lead_id": lead_id, "error": str(e)})
    return {"runs": results}


@router.get("/{lead_id}/context/{stage}")
def stage_context(lead_id: str, stage: str, user: dict = Depends(require_workspace)):
    """The exact LLM prompt + data for this stage. n8n adds scraped content
    where the payload marks it."""
    try:
        ctx = pipeline.stage_context(user["workspace_id"], lead_id, stage)
    except pipeline.PipelineError as e:
        raise HTTPException(409, str(e))
    return ctx


class ApplyIn(BaseModel):
    result: dict


@router.post("/{lead_id}/apply/{stage}")
def apply_stage(lead_id: str, stage: str, req: ApplyIn,
                user: dict = Depends(require_workspace)):
    """Apply an n8n-produced stage result. Deterministic validation happens
    here; failures route the lead to review — never a guess."""
    fn = {
        "qualification": pipeline.apply_qualification,
        "enrichment": pipeline.apply_enrichment,
        "audit": pipeline.apply_audit,
        "offer": pipeline.apply_offer,
        "draft": pipeline.apply_draft,
    }.get(stage)
    if fn is None:
        raise HTTPException(404, f"unknown stage {stage}")
    try:
        outcome = fn(user["workspace_id"], lead_id, req.result)
    except pipeline.PipelineError as e:
        raise HTTPException(422, str(e))
    return outcome


class RecordRunIn(BaseModel):
    agent_name: str
    trigger: str = "n8n_workflow"
    status: str = "success"
    tokens_in: int = 0
    tokens_out: int = 0
    model: str | None = None
    latency_ms: int | None = None
    error: str | None = None
    workspace_id: str | None = None


@router.post("/agents/record-run")
def record_run(req: RecordRunIn, user: dict = Depends(require_workspace)):
    """Cost ledger entry for an LLM call n8n made. Budget guardrail enforced."""
    cost = llm.estimate_cost(req.model or "gpt-4o-mini",
                             req.tokens_in, req.tokens_out) if req.model else 0.0
    try:
        llm.check_budget(req.workspace_id or user["workspace_id"])
    except llm.BudgetExceeded as e:
        raise HTTPException(429, str(e))
    llm.record_run(
        agent_name=req.agent_name,
        trigger=req.trigger,
        input_ref={},
        output_ref={},
        status=req.status,
        tokens_in=req.tokens_in,
        tokens_out=req.tokens_out,
        cost_usd=cost,
        latency_ms=req.latency_ms,
        error=req.error,
        workspace_id=req.workspace_id or user["workspace_id"],
    )
    return {"recorded": True, "cost_usd": round(cost, 6)}


@router.get("/events/{event_id}")
def get_event(event_id: str, user: dict = Depends(require_workspace)):
    """Fetch one outbox row (n8n LISTEN payload carries 'type|id')."""
    from psycopg.rows import dict_row

    import app.db as db

    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        row = conn.execute(
            """SELECT id, event_type, payload, workspace_id, created_at
               FROM event_outbox WHERE id=%s""",
            (event_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "event not found")
    return row


@router.post("/events/{event_id}/ack")
def ack_one(event_id: str, user: dict = Depends(require_workspace)):
    import app.db as db

    with db.get_pool().connection() as conn:
        events.mark_processed(conn, event_id)
    return {"acked": event_id}


@router.get("/events/pending")
def pending_events(user: dict = Depends(require_workspace)):
    """Polling fallback for the LISTEN channel (n8n Postgres Trigger)."""
    with db.get_pool().connection() as conn:
        conn.row_factory = __import__("psycopg.rows", fromlist=["dict_row"]).dict_row
        rows = conn.execute(
            """SELECT id, event_type, payload, created_at FROM event_outbox
               WHERE processed_at IS NULL
               ORDER BY created_at LIMIT 25"""
        ).fetchall()
    return {"items": rows}


class AckEventsIn(BaseModel):
    event_ids: list[str]


@router.post("/events/ack")
def ack_events(req: AckEventsIn, user: dict = Depends(require_workspace)):
    with db.get_pool().connection() as conn:
        for eid in req.event_ids[:100]:
            events.mark_processed(conn, eid)
    return {"acked": len(req.event_ids)}


@router.get("/review-queue")
def review_queue(user: dict = Depends(require_workspace)):
    from psycopg.rows import dict_row

    import app.db as db

    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        rows = conn.execute(
            """SELECT l.id, c.business_name, l.review_reasons, l.fit_status,
                      l.lead_score, l.status
               FROM leads l JOIN companies c ON c.id=l.company_id
               WHERE l.workspace_id=%s AND jsonb_array_length(l.review_reasons) > 0
               ORDER BY l.updated_at DESC LIMIT 200""",
            (user["workspace_id"],),
        ).fetchall()
    return {"items": rows}


@router.post("/review-queue/{lead_id}/clear")
def clear_review(lead_id: str, user: dict = Depends(require_workspace)):
    import app.db as db

    with db.get_pool().connection() as conn:
        row = conn.execute(
            """UPDATE leads SET review_reasons='[]'::jsonb
               WHERE id=%s AND workspace_id=%s RETURNING id""",
            (lead_id, user["workspace_id"]),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "lead not found")
    return {"cleared": True}


@router.get("/agents")
def agent_stats(user: dict = Depends(require_workspace)):
    from psycopg.rows import dict_row

    import app.db as db

    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        rows = conn.execute(
            """SELECT agent_name,
                      count(*) AS runs,
                      count(*) FILTER (WHERE status='success') AS successes,
                      count(*) FILTER (WHERE status='failed') AS failures,
                      round(avg(latency_ms)) AS avg_latency_ms,
                      round(SUM(cost_usd), 4) AS total_cost_usd
               FROM agent_runs GROUP BY agent_name ORDER BY agent_name"""
        ).fetchall()
        recent = conn.execute(
            """SELECT id, agent_name, trigger, status, tokens_in, tokens_out,
                      cost_usd, latency_ms, error, started_at
               FROM agent_runs ORDER BY started_at DESC LIMIT 50"""
        ).fetchall()
        today = conn.execute(
            """SELECT COALESCE(SUM(cost_usd),0) AS spend FROM agent_runs
               WHERE started_at >= date_trunc('day', now())"""
        ).fetchone()["spend"]
    return {"agents": rows, "recent_runs": recent, "spend_today_usd": float(today)}
