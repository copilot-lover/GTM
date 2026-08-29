"""Run ledger helpers over the agent_runs table.

Every GTM agent run gets a durable row: ``record_run`` on entry (status
'running'), ``complete_run`` on exit, or the ``tracked_run`` context
manager which does both and records latency/error automatically.
"""

import contextlib
import json
import time

import psycopg.rows

import app.db as db
from app.agents import registry


def record_run(
    agent_name: str,
    trigger: str,
    workspace_id: str | None = None,
    input_ref: dict | None = None,
    parent_run_id: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    model_version: str | None = None,
) -> str:
    """Insert a status='running' agent_runs row; returns the run id."""
    registry.ensure_registered()
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        row = conn.execute(
            """INSERT INTO agent_runs
                   (workspace_id, agent_name, trigger, input_ref,
                    parent_run_id, provider, model, model_version)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (
                workspace_id, agent_name, trigger,
                json.dumps(input_ref or {}), parent_run_id,
                provider, model, model_version,
            ),
        ).fetchone()
        return str(row["id"])


def complete_run(
    run_id: str,
    status: str = "success",
    output_ref: dict | None = None,
    error: str | None = None,
    confidence: float | None = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    latency_ms: int | None = None,
    cost_usd: float = 0.0,
) -> None:
    """Finalize a run: terminal status, outputs, usage and timing."""
    with db.get_pool().connection() as conn:
        conn.execute(
            """UPDATE agent_runs SET
                   status=%s,
                   output_ref=COALESCE(%s, output_ref),
                   error=%s,
                   confidence=%s,
                   tokens_in=%s,
                   tokens_out=%s,
                   latency_ms=%s,
                   cost_usd=%s,
                   finished_at=now()
               WHERE id=%s""",
            (
                status,
                json.dumps(output_ref) if output_ref is not None else None,
                error, confidence, tokens_in, tokens_out,
                latency_ms, cost_usd, run_id,
            ),
        )


@contextlib.contextmanager
def tracked_run(agent_name: str, trigger: str, **kwargs):
    """record_run on enter, complete_run on exit.

    Yields the run id. On exception the run is marked 'failed' with the
    error string before re-raising.
    """
    run_id = record_run(agent_name, trigger, **kwargs)
    started = time.monotonic()
    try:
        yield run_id
    except Exception as exc:
        complete_run(
            run_id, status="failed", error=f"{type(exc).__name__}: {exc}",
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        raise
    complete_run(
        run_id, status="success",
        latency_ms=int((time.monotonic() - started) * 1000),
    )


def agent_health(workspace_id: str | None = None) -> list[dict]:
    """Per GTM_* agent: last run, 24h success/fail counts, avg latency,
    token totals and last error — merged over the static AGENTS registry."""
    clauses = ["started_at >= now() - interval '24 hours'"]
    params: list = []
    if workspace_id:
        clauses.append("workspace_id = %s")
        params.append(workspace_id)
    where = " AND ".join(clauses)

    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        agg = {
            r["agent_name"]: r
            for r in conn.execute(
                f"""SELECT agent_name,
                           count(*) FILTER (WHERE status='success') AS successes,
                           count(*) FILTER (WHERE status='failed') AS failures,
                           avg(latency_ms) AS avg_latency_ms,
                           COALESCE(sum(tokens_in),0) AS tokens_in,
                           COALESCE(sum(tokens_out),0) AS tokens_out
                    FROM agent_runs WHERE {where} GROUP BY agent_name""",
                tuple(params),
            ).fetchall()
        }
        last = {
            r["agent_name"]: r
            for r in conn.execute(
                """SELECT DISTINCT ON (agent_name)
                          agent_name, started_at, status, error AS last_error
                   FROM agent_runs ORDER BY agent_name, started_at DESC"""
            ).fetchall()
        }

    health = []
    for name in registry.AGENTS:
        a = agg.get(name, {})
        l = last.get(name, {})
        health.append({
            "agent": name,
            "last_run_at": l.get("started_at"),
            "last_status": l.get("status"),
            "last_error": l.get("last_error"),
            "successes_24h": int(a.get("successes") or 0),
            "failures_24h": int(a.get("failures") or 0),
            "avg_latency_ms": (
                round(float(a["avg_latency_ms"]), 1)
                if a.get("avg_latency_ms") is not None else None
            ),
            "tokens_24h": int(a.get("tokens_in") or 0) + int(a.get("tokens_out") or 0),
        })
    return health
