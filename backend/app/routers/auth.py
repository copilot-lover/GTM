from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from psycopg.rows import dict_row

import app.db as db
from app.core.deps import audit, get_current_user
from app.core.security import create_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    display_name: str | None = None
    workspace_name: str = "Orbit"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/register", status_code=201)
def register(req: RegisterRequest):
    if len(req.password) < 10:
        raise HTTPException(422, "password must be at least 10 characters")
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        existing = conn.execute(
            "SELECT id FROM users WHERE email = %s", (req.email.lower(),)
        ).fetchone()
        if existing:
            raise HTTPException(409, "email already registered")
        user = conn.execute(
            """INSERT INTO users (email, password_hash, display_name)
               VALUES (%s,%s,%s) RETURNING id, email, display_name""",
            (req.email.lower(), hash_password(req.password), req.display_name),
        ).fetchone()
        ws = conn.execute(
            "INSERT INTO workspaces (name) VALUES (%s) RETURNING id, name",
            (req.workspace_name,),
        ).fetchone()
        conn.execute(
            """INSERT INTO workspace_members (workspace_id, user_id, role)
               VALUES (%s,%s,'owner')""",
            (ws["id"], user["id"]),
        )
        audit(
            conn,
            actor_type="user",
            actor_id=str(user["id"]),
            action="register",
            entity="user",
            entity_id=str(user["id"]),
            workspace_id=str(ws["id"]),
        )
    return {
        "token": create_token(str(user["id"]), str(ws["id"])),
        "user": {"id": user["id"], "email": user["email"], "display_name": user["display_name"]},
        "workspace": {"id": ws["id"], "name": ws["name"]},
    }


@router.post("/login")
def login(req: LoginRequest):
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        user = conn.execute(
            "SELECT id, email, display_name, password_hash FROM users WHERE email = %s",
            (req.email.lower(),),
        ).fetchone()
        if not user or not verify_password(req.password, user["password_hash"]):
            raise HTTPException(401, "invalid credentials")
        member = conn.execute(
            "SELECT workspace_id FROM workspace_members WHERE user_id = %s LIMIT 1",
            (str(user["id"]),),
        ).fetchone()
        if member is None:
            raise HTTPException(403, "no workspace membership")
        workspace_id = str(member["workspace_id"])
        audit(
            conn,
            actor_type="user",
            actor_id=str(user["id"]),
            action="login",
            entity="user",
            entity_id=str(user["id"]),
            workspace_id=workspace_id,
        )
    return {
        "token": create_token(str(user["id"]), workspace_id),
        "user": {"id": user["id"], "email": user["email"], "display_name": user["display_name"]},
        "workspace_id": workspace_id,
    }


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    return user
