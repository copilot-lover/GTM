"""Enrichment & verification API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import app.db as db
from app.core.deps import require_workspace
from app.services import enrichment
from app.services.job_queue import enqueue

router = APIRouter(prefix="/enrichment", tags=["enrichment"])


class CompanyEnrichResponse(BaseModel):
    company_id: str
    enriched_fields: dict
    provider_used: str | None = None


@router.post("/company/{company_id}", response_model=CompanyEnrichResponse)
def enrich_company(company_id: str, user: dict = Depends(require_workspace)):
    """Trigger company enrichment waterfall."""
    workspace_id = user["workspace_id"]
    with db.get_pool().connection() as conn:
        conn.row_factory = db.get_pool().connection().row_factory
        row = conn.execute(
            "SELECT id FROM companies WHERE id=%s AND workspace_id=%s",
            (company_id, workspace_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "company not found")

    try:
        result = enrichment.enrich_company_waterfall(company_id)
        provider_used = None
        for provider in ["apollo", "hunter", "clearbit"]:
            if any(k in result for k in ["website", "phone", "employee_estimate"]):
                provider_used = provider
                break
        return CompanyEnrichResponse(
            company_id=company_id,
            enriched_fields={k: v for k, v in result.items() if k in [
                "website", "phone", "address", "city", "state", "zip",
                "employee_estimate", "tech_signals", "owner_name", "owner_email"
            ]},
            provider_used=provider_used,
        )
    except Exception as e:
        raise HTTPException(500, f"enrichment failed: {e}")


class VerifyResponse(BaseModel):
    contact_id: str
    email: str
    result: str
    confidence: float
    provider: str | None = None
    local_checks: dict = {}


@router.post("/contact/{contact_id}/verify", response_model=VerifyResponse)
def verify_contact_email(contact_id: str, user: dict = Depends(require_workspace)):
    """Trigger email verification waterfall for a contact."""
    workspace_id = user["workspace_id"]
    with db.get_pool().connection() as conn:
        conn.row_factory = db.get_pool().connection().row_factory
        row = conn.execute(
            "SELECT id, email FROM contacts WHERE id=%s AND workspace_id=%s",
            (contact_id, workspace_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "contact not found")

    try:
        result = enrichment.verify_email_waterfall(contact_id)
        return VerifyResponse(
            contact_id=contact_id,
            email=result.email,
            result=result.result,
            confidence=result.confidence,
            provider=result.raw.get("provider") if isinstance(result.raw, dict) else None,
            local_checks=result.raw.get("local_checks", {}) if isinstance(result.raw, dict) else {},
        )
    except Exception as e:
        raise HTTPException(500, f"verification failed: {e}")


class FindEmailRequest(BaseModel):
    contact_name: str | None = None
    title: str | None = None


class FindEmailResponse(BaseModel):
    contact_id: str | None = None
    email: str | None = None
    confidence: float = 0
    source: str | None = None


@router.post("/contact/{contact_id}/find-email", response_model=FindEmailResponse)
def find_contact_email(contact_id: str, req: FindEmailRequest, user: dict = Depends(require_workspace)):
    """Find decision-maker email for a contact's company."""
    workspace_id = user["workspace_id"]
    with db.get_pool().connection() as conn:
        conn.row_factory = db.get_pool().connection().row_factory
        contact = conn.execute(
            "SELECT c.*, co.id as company_id, co.business_name, co.owner_name "
            "FROM contacts c JOIN companies co ON co.id = c.company_id "
            "WHERE c.id=%s AND c.workspace_id=%s",
            (contact_id, workspace_id),
        ).fetchone()
    if not contact:
        raise HTTPException(404, "contact not found")

    company = {
        "id": str(contact["company_id"]),
        "business_name": contact["business_name"],
        "owner_name": contact["owner_name"],
        "website": contact.get("website"),
    }

    try:
        result = enrichment.find_decision_maker_email(str(contact["company_id"]))
        if result:
            return FindEmailResponse(
                contact_id=contact_id,
                email=result["email"],
                confidence=result["confidence"],
                source=result.get("source"),
            )
        return FindEmailResponse(contact_id=contact_id)
    except Exception as e:
        raise HTTPException(500, f"email find failed: {e}")


class EnqueueEnrichmentRequest(BaseModel):
    company_id: str


@router.post("/enqueue/company")
def enqueue_company_enrichment(req: EnqueueEnrichmentRequest, user: dict = Depends(require_workspace)):
    """Enqueue company enrichment as a background job."""
    workspace_id = user["workspace_id"]
    with db.get_pool().connection() as conn:
        row = conn.execute(
            "SELECT id FROM companies WHERE id=%s AND workspace_id=%s",
            (req.company_id, workspace_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "company not found")

    job = enqueue(
        type="company_enrichment",
        pool="enrichment",
        payload={"company_id": req.company_id},
        workspace_id=workspace_id,
        idempotency_key=f"enrich:{req.company_id}",
    )
    return {"job_id": str(job["id"]), "status": "queued"}


class EnqueueVerificationRequest(BaseModel):
    contact_id: str


@router.post("/enqueue/contact/verify")
def enqueue_contact_verification(req: EnqueueVerificationRequest, user: dict = Depends(require_workspace)):
    """Enqueue contact email verification as a background job."""
    workspace_id = user["workspace_id"]
    with db.get_pool().connection() as conn:
        row = conn.execute(
            "SELECT id FROM contacts WHERE id=%s AND workspace_id=%s",
            (req.contact_id, workspace_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "contact not found")

    job = enqueue(
        type="email_verification",
        pool="verification",
        payload={"contact_id": req.contact_id},
        workspace_id=workspace_id,
        idempotency_key=f"verify:{req.contact_id}",
    )
    return {"job_id": str(job["id"]), "status": "queued"}


class EnqueueFindEmailRequest(BaseModel):
    contact_id: str


@router.post("/enqueue/contact/find-email")
def enqueue_find_email(req: EnqueueFindEmailRequest, user: dict = Depends(require_workspace)):
    """Enqueue decision-maker email finding as a background job."""
    workspace_id = user["workspace_id"]
    with db.get_pool().connection() as conn:
        row = conn.execute(
            "SELECT id FROM contacts WHERE id=%s AND workspace_id=%s",
            (req.contact_id, workspace_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "contact not found")

    job = enqueue(
        type="email_finder",
        pool="enrichment",
        payload={"contact_id": req.contact_id},
        workspace_id=workspace_id,
        idempotency_key=f"find_email:{req.contact_id}",
    )
    return {"job_id": str(job["id"]), "status": "queued"}