from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from psycopg.rows import dict_row

import app.db as db
from app.core.deps import require_workspace
from app.services import pipeline

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


class RunIn(BaseModel):
    lead_ids: list[str]


@router.post("/run")
def run(req: RunIn, user: dict = Depends(require_workspace)):
    """Run the six-stage pipeline over lead ids. n8n batch or manual trigger.
    Fail-closed: blocked stages route leads to review, never guess."""
    results = []
    for lead_id in req.lead_ids[:100]:
        r = pipeline.run_pipeline(user["workspace_id"], lead_id)
        results.append(r)
    return {"runs": results}


@router.get("/review-queue")
def review_queue(user: dict = Depends(require_workspace)):
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
