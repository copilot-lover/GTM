"""Scheduled agent runner on top of the existing durable jobs queue.

No new queue: agent_schedules rows are materialized into job_queue jobs by
``tick``; real handlers are registered via the standard ``@worker``
decorator so the existing WorkerSupervisor pools run them.
"""

import logging

import psycopg.rows

import app.db as db
from app.config import get_settings
from app.services import job_queue

logger = logging.getLogger(__name__)

DEFAULT_TASKS = {
    "GTM_LEADS": ("gtm_leads_refresh", "discovery"),
    "GTM_INTENT": ("gtm_intent_process", "ai"),
    "GTM_QA": ("gtm_qa_audit", "ai"),
    "GTM_OUTBOUND": ("gtm_outbound_refresh", "outbound"),
    "GTM_REPLIES": ("gtm_reply_check", "ai"),
}

PRIORITY_BY_AGENT = {"GTM_OUTBOUND": 1, "GTM_REPLIES": 2}


def ensure_default_schedules() -> None:
    """Upsert agent_schedules rows from settings.gtm_agent_schedules.

    UNIQUE(agent, task_type) makes this idempotent.
    """
    intervals = get_settings().gtm_agent_schedules
    with db.get_pool().connection() as conn:
        for agent, (task_type, pool) in DEFAULT_TASKS.items():
            seconds = int(intervals.get(agent, 3600))
            conn.execute(
                """INSERT INTO agent_schedules
                       (agent, task_type, pool, schedule_seconds, priority)
                   VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT (agent, task_type) DO UPDATE SET
                       pool = EXCLUDED.pool,
                       schedule_seconds = EXCLUDED.schedule_seconds""",
                (
                    agent, task_type, pool, seconds,
                    PRIORITY_BY_AGENT.get(agent, 3),
                ),
            )


def tick(limit: int = 25) -> dict:
    """Enqueue one job per due enabled schedule and advance next_run."""
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        due = conn.execute(
            """SELECT * FROM agent_schedules
               WHERE enabled AND next_run <= now()
               ORDER BY priority ASC, next_run ASC LIMIT %s""",
            (limit,),
        ).fetchall()

        scheduled = 0
        for s in due:
            epoch_bucket = int(s["next_run"].timestamp())
            try:
                job_queue.enqueue(
                    type=s["task_type"],
                    pool=s["pool"],
                    priority=s["priority"],
                    payload={"schedule_id": str(s["id"])},
                    idempotency_key=f"agent-schedule-{s['id']}-{epoch_bucket}",
                    workspace_id=str(s["workspace_id"]) if s["workspace_id"] else None,
                )
                conn.execute(
                    """UPDATE agent_schedules SET last_run=now(),
                           next_run=now() + make_interval(secs => schedule_seconds),
                           last_status='scheduled', last_error=NULL
                       WHERE id=%s""",
                    (s["id"],),
                )
                scheduled += 1
            except Exception as exc:
                logger.warning("schedule %s tick failed: %s", s["id"], exc)
                conn.execute(
                    """UPDATE agent_schedules SET last_status='failed',
                           last_error=%s WHERE id=%s""",
                    (f"{type(exc).__name__}: {exc}", s["id"]),
                )
    return {"scheduled": scheduled}


def due_preview() -> list[dict]:
    """Schedules currently due (next_run <= now()), without mutating."""
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        return conn.execute(
            """SELECT id, agent, task_type, pool, schedule_seconds, priority,
                      enabled, last_run, next_run, last_status, last_error
               FROM agent_schedules
               WHERE enabled AND next_run <= now()
               ORDER BY priority ASC, next_run ASC"""
        ).fetchall()


# -----------------------------------------------------------------------
# Real handlers — registered into the existing job queue worker pools
# -----------------------------------------------------------------------


@job_queue.worker("ai", "gtm_intent_process")
def handle_gtm_intent_process(job: dict) -> dict:
    """Process pending intent events via app.services.intent_engine.

    Defensively skips when the engine module/function is not ready yet.
    """
    from app.agents import ledger

    try:
        from app.services import intent_engine
    except ImportError:
        return {"skipped": "intent_engine not ready"}

    process_fn = getattr(intent_engine, "process_pending_events", None)
    if process_fn is None:
        return {"skipped": "intent_engine not ready"}

    workspace_id = job.get("workspace_id")
    try:
        with ledger.tracked_run("GTM_INTENT", "schedule",
                                workspace_id=workspace_id) as run_id:
            if workspace_id:
                result = process_fn(workspace_id)
            else:
                with db.get_pool().connection() as conn:
                    ws_ids = [
                        str(r["workspace_id"]) for r in conn.execute(
                            """SELECT DISTINCT workspace_id FROM intent_events
                               WHERE processed=false"""
                        ).fetchall()
                    ]
                processed = {}
                for ws in ws_ids:
                    processed[ws] = process_fn(ws)
                result = {"workspaces": processed}
            ledger.complete_run(run_id, output_ref={"result": _plain(result)})
            return _plain(result)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


@job_queue.worker("ai", "gtm_qa_audit")
def handle_gtm_qa_audit(job: dict) -> dict:
    """Audit counts + QA sweep: advance every QA_PENDING draft through the
    deterministic copy/compliance gates; copy failures stay for regeneration."""
    from app.agents import ledger

    try:
        with ledger.tracked_run("GTM_QA", "schedule") as run_id:
            with db.get_pool().connection() as conn:
                conn.row_factory = psycopg.rows.dict_row
                stale_qa_pending = conn.execute(
                    """SELECT count(*) AS n FROM messages
                       WHERE gtm_stage='QA_PENDING'
                         AND created_at < now() - interval '24 hours'"""
                ).fetchone()["n"]
                dead_letter_24h = conn.execute(
                    """SELECT count(*) AS n FROM jobs
                       WHERE status='DEAD_LETTER'
                         AND completed_at >= now() - interval '24 hours'"""
                ).fetchone()["n"]
                pending = conn.execute(
                    """SELECT workspace_id, id FROM messages
                       WHERE gtm_stage='QA_PENDING'"""
                ).fetchall()

            from app.services import qa_service

            audited = copy_passed = compliance_passed = failed = 0
            for row in pending:
                ws, mid = str(row["workspace_id"]), str(row["id"])
                try:
                    run = qa_service.run_copy_qa(ws, mid)
                    audited += 1
                    if run["status"] == "passed":
                        copy_passed += 1
                        comp = qa_service.run_compliance_qa(ws, mid)
                        if comp["status"] == "passed":
                            compliance_passed += 1
                    else:
                        # left at QA_FAILED for GTM_COPY/n8n regeneration
                        failed += 1
                except Exception as exc:
                    logger.warning("qa sweep skipped message %s: %s", mid, exc)

            result = {
                "stale_qa_pending": int(stale_qa_pending),
                "dead_letter_24h": int(dead_letter_24h),
                "audited": audited,
                "copy_passed": copy_passed,
                "compliance_passed": compliance_passed,
                "failed": failed,
            }
            ledger.complete_run(run_id, output_ref={"audit": result})
            return result
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


@job_queue.worker("outbound", "gtm_outbound_refresh")
def handle_gtm_outbound_refresh(job: dict) -> dict:
    """Run one tick of the existing adaptive outbound scheduler."""
    from app.services import scheduler

    return scheduler.tick()


@job_queue.worker("ai", "gtm_reply_check")
def handle_gtm_reply_check(job: dict) -> dict:
    """Inbound volume + open human-handoff tasks needing replies."""
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        inbound_24h = conn.execute(
            """SELECT count(*) AS n FROM messages
               WHERE direction='inbound'
                 AND created_at >= now() - interval '24 hours'"""
        ).fetchone()["n"]
        open_human_tasks = conn.execute(
            """SELECT count(*) AS n FROM tasks
               WHERE status='open' AND type LIKE 'handle %'"""
        ).fetchone()["n"]
    return {
        "inbound_24h": int(inbound_24h),
        "open_handle_tasks": int(open_human_tasks),
    }


@job_queue.worker("discovery", "gtm_leads_refresh")
def handle_gtm_leads_refresh(job: dict) -> dict:
    """Counts of leads discovered last 24h grouped by fit_status."""
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        rows = conn.execute(
            """SELECT fit_status, count(*) AS n FROM leads
               WHERE created_at >= now() - interval '24 hours'
               GROUP BY fit_status"""
        ).fetchall()
    return {"by_fit_status": {r["fit_status"]: int(r["n"]) for r in rows}}


def _plain(value):
    if value is None or isinstance(value, (str, int, float, bool, list, dict)):
        return value
    return repr(value)
