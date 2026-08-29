"""Opportunity Router — WS-D: API endpoints for scoring, research, and email QC."""

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from psycopg.rows import dict_row

import app.db as db
from app.core.deps import require_workspace
from app.services import opportunity, research, website_intel, email_qc

router = APIRouter(prefix="/opportunity", tags=["opportunity"])


class EmailQCRequest(BaseModel):
    draft_body: str
    company_id: str
    lead_id: str | None = None


@router.post("/score/{company_id}")
def compute_score(company_id: str, user: dict = Depends(require_workspace)):
    """Compute opportunity score + EMV for a company."""
    # Verify company belongs to workspace
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        company = conn.execute(
            "SELECT workspace_id FROM companies WHERE id=%s", (company_id,)
        ).fetchone()
    if not company:
        raise HTTPException(404, "Company not found")
    if str(company["workspace_id"]) != user["workspace_id"]:
        raise HTTPException(403, "Company not in workspace")

    try:
        breakdown = opportunity.compute_opportunity_score(company_id)
        emv = opportunity.compute_emv(company_id)
        return {
            "company_id": company_id,
            "opportunity_score": {
                "total": breakdown.total,
                "tier": breakdown.tier,
                "components": breakdown.components,
                "recommended_action": breakdown.recommended_action,
                "recommended_pitch": breakdown.recommended_pitch,
                "primary_problem": breakdown.primary_problem,
                "reason_now": breakdown.reason_now,
            },
            "emv": {
                "emv_usd": emv.emv,
                "p_positive_reply": emv.p_positive_reply,
                "p_meeting": emv.p_meeting,
                "est_customer_value": emv.est_customer_value,
            },
        }
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"Scoring failed: {type(e).__name__}: {e}")


@router.post("/research/{company_id}")
def research_company(company_id: str, user: dict = Depends(require_workspace)):
    """Run AI research on a company with QC validation."""
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        company = conn.execute(
            "SELECT workspace_id FROM companies WHERE id=%s", (company_id,)
        ).fetchone()
    if not company:
        raise HTTPException(404, "Company not found")
    if str(company["workspace_id"]) != user["workspace_id"]:
        raise HTTPException(403, "Company not in workspace")

    try:
        report = research.research_company(company_id)
        return {
            "company_id": company_id,
            "research_report": {
                "summary": report.summary,
                "primary_problem": report.primary_problem,
                "reason_now": report.reason_now,
                "recommended_offer": report.recommended_offer,
                "evidence": report.evidence,
                "model_used": report.model_used,
            },
        }
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"Research failed: {type(e).__name__}: {e}")


@router.get("/lead/{lead_id}")
def get_lead_opportunity(lead_id: str, user: dict = Depends(require_workspace)):
    """Get opportunity score + research summary for a lead's company."""
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        lead = conn.execute(
            """SELECT l.*, c.id as company_id, c.workspace_id as company_ws
               FROM leads l JOIN companies c ON c.id = l.company_id
               WHERE l.id=%s""",
            (lead_id,),
        ).fetchone()
    if not lead:
        raise HTTPException(404, "Lead not found")
    if str(lead["workspace_id"]) != user["workspace_id"]:
        raise HTTPException(403, "Lead not in workspace")

    company_id = str(lead["company_id"])

    # Get latest opportunity score
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        score = conn.execute(
            """SELECT * FROM scores
               WHERE lead_id=%s AND score_type='opportunity'
               ORDER BY computed_at DESC LIMIT 1""",
            (lead_id,),
        ).fetchone()

    # Get latest research
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        research_report = conn.execute(
            """SELECT * FROM research_reports
               WHERE company_id=%s ORDER BY created_at DESC LIMIT 1""",
            (company_id,),
        ).fetchone()

    return {
        "lead_id": lead_id,
        "company_id": company_id,
        "opportunity_score": dict(score) if score else None,
        "research_report": dict(research_report) if research_report else None,
    }


@router.post("/email-qc")
def qc_email(req: EmailQCRequest, user: dict = Depends(require_workspace)):
    """QC an email draft for a specific company/lead."""
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        company = conn.execute(
            "SELECT * FROM companies WHERE id=%s", (req.company_id,)
        ).fetchone()
    if not company:
        raise HTTPException(404, "Company not found")
    if str(company["workspace_id"]) != user["workspace_id"]:
        raise HTTPException(403, "Company not in workspace")

    # Get latest research report
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        research_report = conn.execute(
            """SELECT * FROM research_reports
               WHERE company_id=%s ORDER BY created_at DESC LIMIT 1""",
            (req.company_id,),
        ).fetchone()

    # Get lead context
    lead_context = {"company": dict(company)}
    if req.lead_id:
        with db.get_pool().connection() as conn:
            conn.row_factory = dict_row
            lead = conn.execute(
                "SELECT * FROM leads WHERE id=%s", (req.lead_id,)
            ).fetchone()
        if lead:
            lead_context["lead"] = dict(lead)

    result = email_qc.qc_email(req.draft_body, dict(research_report) if research_report else None, lead_context)

    return {
        "company_id": req.company_id,
        "lead_id": req.lead_id,
        "qc_result": {
            "has_specific_observation": result.has_specific_observation,
            "observation_sentence": result.observation_sentence,
            "connects_to_problem": result.connects_to_problem,
            "problem": result.problem,
            "pass": result.pass_,
            "failure_reasons": result.failure_reasons,
        },
    }


@router.post("/website-intel/{company_id}")
def fetch_website_intel(company_id: str, user: dict = Depends(require_workspace)):
    """Fetch and analyze website intelligence for a company."""
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        company = conn.execute(
            "SELECT workspace_id FROM companies WHERE id=%s", (company_id,)
        ).fetchone()
    if not company:
        raise HTTPException(404, "Company not found")
    if str(company["workspace_id"]) != user["workspace_id"]:
        raise HTTPException(403, "Company not in workspace")

    try:
        result = website_intel.fetch_website_intel(company_id)
        return {
            "company_id": company_id,
            "website_findings": result.website_findings,
            "tech_signals": result.tech_signals,
        }
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"Website intel failed: {type(e).__name__}: {e}")