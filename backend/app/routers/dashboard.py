from fastapi import APIRouter, Depends
from psycopg.rows import dict_row

import app.db as db
from app.core.deps import require_workspace

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
def dashboard(user: dict = Depends(require_workspace)):
    ws = user["workspace_id"]
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        kpis = conn.execute(
            """SELECT
                 (SELECT count(*) FROM leads WHERE workspace_id=%s
                    AND created_at::date = now()::date) AS new_leads_today,
                 (SELECT count(*) FROM leads WHERE workspace_id=%s AND status='contacted')
                    AS contacted_total,
                 (SELECT count(*) FROM leads WHERE workspace_id=%s AND status='responded')
                    AS replies_total,
                 (SELECT count(*) FROM meetings WHERE workspace_id=%s
                    AND scheduled_at >= now()) AS upcoming_meetings,
                 (SELECT COALESCE(SUM(value_mrr),0) FROM opportunities
                    WHERE workspace_id=%s AND stage='open') AS open_pipeline_mrr
               """,
            (ws, ws, ws, ws, ws),
        ).fetchone()
        funnel = conn.execute(
            """SELECT status, count(*) AS n FROM leads WHERE workspace_id=%s
               GROUP BY status""",
            (ws,),
        ).fetchall()
        hot_leads = conn.execute(
            """SELECT l.id, c.business_name, l.priority_score, l.primary_pain,
                      l.recommended_offer, c.phone
               FROM leads l JOIN companies c ON c.id=l.company_id
               WHERE l.workspace_id=%s AND l.status NOT IN
                 ('rejected','do_not_call','archived','won','lost')
               ORDER BY coalesce(l.priority_score,0) DESC LIMIT 10""",
            (ws,),
        ).fetchall()
        approvals = conn.execute(
            """SELECT count(*) AS n FROM messages
               WHERE workspace_id=%s AND status='pending_approval'""",
            (ws,),
        ).fetchone()["n"]
        ai_spend_today = conn.execute(
            """SELECT COALESCE(SUM(cost_usd),0) AS spend FROM agent_runs
               WHERE started_at >= date_trunc('day', now())""",
        ).fetchone()["spend"]
    return {
        "kpis": kpis,
        "funnel": {r["status"]: r["n"] for r in funnel},
        "hot_leads": hot_leads,
        "pending_approvals": approvals,
        "ai_spend_today_usd": float(ai_spend_today),
    }


@router.get("/system-health")
def system_health(user: dict = Depends(require_workspace)):
    import os

    from app.services import twilio_service

    checks = {}
    # database is implicitly up (this request worked)
    checks["database"] = "ok"
    checks["twilio"] = "configured" if twilio_service.configured() else "not_configured"
    checks["llm_openai"] = "configured" if os.environ.get("OPENAI_API_KEY") else "missing"
    checks["llm_anthropic"] = ("configured" if os.environ.get("ANTHROPIC_API_KEY")
                               else "missing")
    checks["smtp"] = "configured" if os.environ.get("SMTP_HOST") else "missing"
    try:
        with db.get_pool().connection() as conn:
            row = conn.execute(
                "SELECT count(*) FROM agent_runs WHERE status='failed' AND finished_at > now() - interval '24 hours'"
            ).fetchone()
            checks["agent_failures_24h"] = row[0]
    except Exception:
        checks["agent_failures_24h"] = -1
    return {"status": "ok", "checks": checks}
