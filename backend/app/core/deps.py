from fastapi import HTTPException, Request
from psycopg.rows import dict_row

import app.db as db

# Single-user, no-auth mode: one implicit identity, auto-provisioned.
_SINGL_USER_CACHE: dict | None = None


def _bootstrap_solo() -> dict:
    """Ensure the default workspace + user exist; return the identity."""
    global _SINGL_USER_CACHE
    if _SINGL_USER_CACHE:
        return _SINGL_USER_CACHE
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        ws = conn.execute(
            "SELECT id, name FROM workspaces WHERE name = 'Orbit' ORDER BY id LIMIT 1"
        ).fetchone()
        if ws is None:
            ws = conn.execute(
                """INSERT INTO workspaces (name, onboarding_completed, onboarding_step)
                   VALUES ('Orbit', true, 'complete')
                   RETURNING id, name"""
            ).fetchone()
        user = conn.execute(
            """INSERT INTO users (email, password_hash, display_name)
               VALUES ('solo@orbit.local', '', 'Owner')
               ON CONFLICT (email) DO NOTHING
               RETURNING id, email, display_name"""
        ).fetchone()
        if user is None:
            user = conn.execute(
                "SELECT id, email, display_name FROM users WHERE email = 'solo@orbit.local' LIMIT 1"
            ).fetchone()
        if ws is None:
            ws = conn.execute(
                "SELECT id, name FROM workspaces WHERE name = 'Orbit' LIMIT 1"
            ).fetchone()
        if user is None:
            user = conn.execute(
                "SELECT id, email, display_name FROM users WHERE email = 'solo@orbit.local' LIMIT 1"
            ).fetchone()
        conn.execute(
            """INSERT INTO workspace_members (workspace_id, user_id, role)
               SELECT %s,%s,'owner'
               WHERE NOT EXISTS (
                 SELECT 1 FROM workspace_members
                 WHERE workspace_id = %s AND user_id = %s)""",
            (ws["id"], user["id"], ws["id"], user["id"]),
        )
    _SINGL_USER_CACHE = {
        **user,
        "workspace_id": ws["id"],
        "role": "owner",
    }
    return _SINGL_USER_CACHE


def fetch_one(query: str, params: tuple) -> dict | None:
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        return conn.execute(query, params).fetchone()


def get_current_user() -> dict:
    return _bootstrap_solo()


def require_workspace() -> dict:
    return _bootstrap_solo()


def audit(
    conn,
    *,
    actor_type: str,
    actor_id: str | None,
    action: str,
    entity: str,
    entity_id: str | None,
    before_state: dict | None = None,
    after_state: dict | None = None,
    workspace_id: str | None = None,
    ip: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO audit_log
           (workspace_id, actor_type, actor_id, action, entity, entity_id,
            before_state, after_state, ip)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            workspace_id,
            actor_type,
            actor_id,
            action,
            entity,
            entity_id,
            json_dumps(before_state),
            json_dumps(after_state),
            ip,
        ),
    )


def json_dumps(value):
    import json

    return json.dumps(value) if value is not None else None


def client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else request.client.host if request.client else None