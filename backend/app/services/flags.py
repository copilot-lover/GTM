"""Global system flags (kill switches) backed by the system_flags table.

Known keys: pause_all_sending, pause_followups, pause_ai_replies,
pause_hiring_campaigns, shadow_mode, approval_mode
(approval_mode is 'autonomous' | 'approval' | 'hybrid').
"""

import json

import psycopg.rows

import app.db as db


def set_flag(key: str, value, updated_by: str | None = None) -> dict:
    """Upsert a flag; value may be any JSON-serializable object."""
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        return conn.execute(
            """INSERT INTO system_flags (key, value, updated_by)
               VALUES (%s,%s,%s)
               ON CONFLICT (key) DO UPDATE
                   SET value=EXCLUDED.value, updated_at=now(),
                       updated_by=EXCLUDED.updated_by
               RETURNING *""",
            (key, json.dumps(value), updated_by),
        ).fetchone()


def get_flag(key: str):
    with db.get_pool().connection() as conn:
        row = conn.execute(
            "SELECT value FROM system_flags WHERE key=%s", (key,)
        ).fetchone()
    return row["value"] if row else None


def all_flags() -> dict:
    with db.get_pool().connection() as conn:
        rows = conn.execute("SELECT key, value FROM system_flags").fetchall()
    return {r["key"]: r["value"] for r in rows}
