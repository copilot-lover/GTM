from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from psycopg.rows import dict_row

import app.db as db
from app.core.deps import audit, require_workspace
from app.core.security import hash_password  # noqa: F401 (re-export convenience)
from app.services import phones, scoring, state_machine

router = APIRouter(prefix="/companies", tags=["companies"])


class CompanyIn(BaseModel):
    business_name: str = Field(min_length=1, max_length=300)
    website: str | None = None
    phone: str | None = None
    city: str | None = None
    state: str | None = None
    vertical: str | None = None
    owner_name: str | None = None
    source: str | None = None
    source_url: str | None = None


@router.post("", status_code=201)
def create_company(req: CompanyIn, user: dict = Depends(require_workspace)):
    """Create-or-return-existing company keyed on the canonical dedupe identity."""
    name, city, state = phones.dedupe_key(req.business_name, req.city, req.state)
    phone_e164 = phones.normalize_phone(req.phone)
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        existing = conn.execute(
            """SELECT * FROM companies
               WHERE workspace_id=%s AND lower(business_name)=%s
                 AND lower(coalesce(city,''))=%s AND lower(coalesce(state,''))=%s""",
            (user["workspace_id"], name, city, state),
        ).fetchone()
        if existing:
            return {"company": existing, "deduped": True}
        company = conn.execute(
            """INSERT INTO companies
               (workspace_id, business_name, website, phone, city, state,
                vertical, owner_name, source, source_url)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               RETURNING *""",
            (
                user["workspace_id"], req.business_name.strip(), req.website,
                phone_e164, req.city, req.state, req.vertical, req.owner_name,
                req.source, req.source_url,
            ),
        ).fetchone()
        audit(
            conn,
            actor_type="user",
            actor_id=str(user["id"]),
            action="create",
            entity="company",
            entity_id=str(company["id"]),
            workspace_id=user["workspace_id"],
        )
    return {"company": company, "deduped": False}


@router.get("")
def list_companies(
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user: dict = Depends(require_workspace),
):
    limit = min(limit, 200)
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        rows = conn.execute(
            """SELECT * FROM companies WHERE workspace_id=%s
               AND (%s IS NULL OR business_name ILIKE '%%' || %s || '%%')
               ORDER BY created_at DESC LIMIT %s OFFSET %s""",
            (user["workspace_id"], q, q, limit, offset),
        ).fetchall()
    return {"items": rows, "limit": limit, "offset": offset}
