from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg.rows import dict_row

import app.db as db
from app.core.security import decode_token

bearer = HTTPBearer(auto_error=False)


def fetch_one(query: str, params: tuple) -> dict | None:
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        return conn.execute(query, params).fetchone()


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict:
    if creds is None:
        raise HTTPException(401, "missing token")
    payload = decode_token(creds.credentials)
    if payload is None:
        raise HTTPException(401, "invalid or expired token")
    user = fetch_one(
        "SELECT id, email, display_name FROM users WHERE id = %s", (payload["sub"],)
    )
    if user is None:
        raise HTTPException(401, "user not found")
    member = fetch_one(
        """SELECT m.workspace_id, m.role FROM workspace_members m
           WHERE m.user_id = %s AND m.workspace_id = %s""",
        (str(user["id"]), payload["ws"]),
    )
    if member is None:
        raise HTTPException(403, "not a member of the tokenized workspace")
    return {
        **user,
        "workspace_id": member["workspace_id"],
        "role": member["role"],
    }


def require_workspace(user: dict = Depends(get_current_user)) -> dict:
    if not user.get("workspace_id"):
        raise HTTPException(403, "no workspace")
    return user


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
