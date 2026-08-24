"""AI cost ledger + budget guardrails.

Per spec §10.3, the backend performs NO LLM calls — n8n owns all external
integrations. This module only records what n8n reports (tokens, cost,
latency) and enforces the daily budget as a hard stop for new work.
"""

import os

import app.db as db


class BudgetExceeded(Exception):
    pass


# rough $/1k tokens for cost ledger estimates; update as pricing changes
PRICING = {
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4o": (0.0025, 0.01),
    "gpt-4.1-mini": (0.0004, 0.0016),
    "gpt-5-mini": (0.0004, 0.0016),
    "claude-haiku": (0.0008, 0.004),
    "claude-sonnet": (0.003, 0.015),
}


def check_budget(workspace_id: str | None) -> None:
    limit = float(os.environ.get("AI_DAILY_BUDGET_USD", "10"))
    with db.get_pool().connection() as conn:
        row = conn.execute(
            """SELECT COALESCE(SUM(cost_usd),0) AS spent FROM agent_runs
               WHERE started_at >= date_trunc('day', now())
               AND (%s::uuid IS NULL OR workspace_id = %s::uuid)""",
            (workspace_id, workspace_id),
        ).fetchone()
    spent = float(row["spent"] or 0)
    if spent >= limit:
        raise BudgetExceeded(f"daily AI budget spent: ${spent:.2f} / ${limit:.2f}")


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    pin, pout = PRICING.get(model, (0.001, 0.002))
    return (tokens_in * pin + tokens_out * pout) / 1000


def record_run(
    *, agent_name: str, trigger: str, input_ref: dict, output_ref: dict,
    status: str, tokens_in: int = 0, tokens_out: int = 0, cost_usd: float = 0.0,
    latency_ms: int | None = None, error: str | None = None,
    workspace_id: str | None = None,
) -> None:
    check_budget(workspace_id) if status == "running" else None
    with db.get_pool().connection() as conn:
        conn.execute(
            """INSERT INTO agent_runs
               (workspace_id, agent_name, trigger, input_ref, output_ref, status,
                tokens_in, tokens_out, cost_usd, latency_ms, error, finished_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                       CASE WHEN %s = 'running' THEN NULL ELSE now() END)""",
            (
                workspace_id, agent_name, trigger,
                db_json(input_ref), db_json(output_ref), status,
                tokens_in, tokens_out, cost_usd, latency_ms, error, status,
            ),
        )


def db_json(value) -> str | None:
    import json

    return json.dumps(value) if value is not None else None
