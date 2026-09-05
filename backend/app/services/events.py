"""Event outbox: Postgres emits state changes; n8n orchestrates the response.
The backend NEVER performs long-running external work inline (spec §10.3)."""

import json


def emit(conn, *, event_type: str, payload: dict,
         workspace_id: str | None = None) -> str:
    row = conn.execute(
        """INSERT INTO event_outbox (workspace_id, event_type, payload)
           VALUES (%s,%s,%s) RETURNING id""",
        (workspace_id, event_type, json.dumps(payload)),
    ).fetchone()
    return str(row[0]) if not isinstance(row, dict) else str(row["id"])


def mark_processed(conn, event_id: str) -> None:
    conn.execute(
        "UPDATE event_outbox SET processed_at=now() WHERE id=%s", (event_id,)
    )
