"""Hiring-intent pipeline — ISOLATED subsystem, EMAIL ONLY (spec §8).
No code path here touches the dialer, SMS, or normal cold outreach."""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from psycopg.rows import dict_row

import app.db as db
from app.core.deps import require_workspace
from app.services import llm, scoring

router = APIRouter(prefix="/hiring-intent", tags=["hiring-intent"])

SIGNAL_EXPIRY_DAYS = 30


class PostingIn(BaseModel):
    source: str
    source_url: str
    external_job_id: str
    title: str
    description_raw: str | None = None
    location: str | None = None
    posted_at: datetime | None = None
    company_name: str | None = None
    company_website: str | None = None
    company_phone: str | None = None
    contact_email: str | None = None


def classify_role(title: str) -> tuple[str | None, dict]:
    """Deterministic role taxonomy + description signal detection."""
    t = title.lower()
    role_key = None
    taxonomy = {
        "receptionist": "receptionist", "front desk": "front_desk_receptionist",
        "customer service representative": "customer_service_representative",
        "call center": "call_center_representative",
        "appointment setter": "appointment_setter",
        "service coordinator": "service_coordinator",
        "dispatcher": "dispatcher", "office manager": "office_manager",
    }
    for needle, key in taxonomy.items():
        if needle in t:
            role_key = key
            break
    return role_key, {}


QUALIFIER_SYSTEM = (
    "You are the Hiring-Intent Qualifier for Orbit (AI receptionist agency). "
    "Given a job posting, read the DESCRIPTION and detect: after_hours "
    "(bool), phone_heavy (e.g. 'answer 50+ inbound calls'), scheduling_duties "
    "('schedule appointments/service calls'), icp_match (home-services/plumbing/"
    "HVAC/electrical/roofing company), multiple_openings. Quote the responsibilities "
    "you relied on in relevant_responsibilities. Fail closed: unclear -> false."
)

QUALIFIER_KEYS = ["after_hours", "phone_heavy", "scheduling_duties", "icp_match",
                  "multiple_openings", "relevant_responsibilities", "rationale"]


@router.post("/ingest", status_code=201)
def ingest(req: PostingIn, user: dict = Depends(require_workspace)):
    """Ingest -> normalize -> dedupe -> resolve company -> AI qualify -> queue.
    Permitted sources only; caller is responsible for ToS-compliant acquisition."""
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        existing = conn.execute(
            "SELECT id FROM job_postings WHERE workspace_id=%s AND external_job_id=%s",
            (user["workspace_id"], req.external_job_id),
        ).fetchone()
        if existing:
            return {"id": existing["id"], "duplicate": True}

    # company resolution from name+geo evidence provided by the adapter
    company_id = None
    if req.company_name and req.contact_email:
        from app.services.phones import normalize_phone

        with db.get_pool().connection() as conn:
            conn.row_factory = dict_row
            row = conn.execute(
                """INSERT INTO companies (workspace_id, business_name, website, phone,
                       city, state, source, source_url)
                   VALUES (%s,%s,%s,%s,%s,NULL,'job_posting',%s)
                   ON CONFLICT (workspace_id, lower(business_name),
                                coalesce(city,''), coalesce(state,''))
                   DO UPDATE SET updated_at=now() RETURNING id""",
                (
                    user["workspace_id"], req.company_name, req.company_website,
                    normalize_phone(req.company_phone), req.location,
                    req.source_url,
                ),
            ).fetchone()
            company_id = str(row["id"])

    role_key, _ = classify_role(req.title)
    description_signals = {}
    if req.description_raw and any(
        k in req.description_raw.lower()
        for k in ("icp", "hvac", "plumb", "electric", "roofing", "home services")
    ):
        description_signals["hint_icp"] = True

    intent_score = scoring.hiring_intent_score(
        role_key=role_key,
        icp_match=bool(description_signals.get("hint_icp")),
        after_hours=False,  # refined by AI qualifier below when configured
        phone_heavy=False,
        scheduling_duties=False,
        multiple_openings=False,
        days_old=((datetime.now(timezone.utc) - req.posted_at).days
                  if req.posted_at else None),
        multiple_locations=False,
    )

    # AI refinement of description signals (cheap tier); degrade gracefully
    ai_rationale = None
    relevant_responsibilities: list = []
    try:
        parsed = llm.structured_complete(
            agent_name="hiring_intent_qualifier",
            system=QUALIFIER_SYSTEM,
            user=json.dumps({
                "title": req.title,
                "company": req.company_name,
                "description": (req.description_raw or "")[:8000],
            }),
            required_keys=QUALIFIER_KEYS[:6] + ["rationale"],
            workspace_id=user["workspace_id"],
            max_tokens=700,
        )
        base = intent_score
        extra = scoring.hiring_intent_score(
            role_key=role_key, icp_match=parsed.get("icp_match", False),
            after_hours=parsed.get("after_hours", False),
            phone_heavy=parsed.get("phone_heavy", False),
            scheduling_duties=parsed.get("scheduling_duties", False),
            multiple_openings=parsed.get("multiple_openings", False),
            days_old=None, multiple_locations=False,
        )
        intent_score = max(intent_score, extra) if extra else base
        if parsed.get("icp_match") and not description_signals.get("hint_icp"):
            intent_score = min(100, intent_score + 30)
        ai_rationale = parsed.get("rationale")
        relevant_responsibilities = parsed.get("relevant_responsibilities") or []
    except (llm.MissingConfiguration, llm.BudgetExceeded, llm.ReviewRequired):
        pass  # deterministic score stands; fail-closed at send gate anyway

    category = scoring.hiring_category(intent_score)
    status = {"very_high": "qualified", "high": "qualified"}.get(category, "new")
    if category == "medium":
        status = "nurture"
    elif category == "low":
        status = "rejected"

    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        posting = conn.execute(
            """INSERT INTO job_postings (workspace_id, company_id, source, source_url,
                   external_job_id, title, description_raw, location, posted_at,
                   intent_score, intent_category, relevant_responsibilities,
                   qualification_rationale, recommended_offer, confidence, status)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'ai_receptionist',
                       %s,%s)
               RETURNING *""",
            (
                user["workspace_id"], company_id, req.source, req.source_url,
                req.external_job_id, req.title, req.description_raw, req.location,
                req.posted_at, intent_score, category,
                json.dumps(relevant_responsibilities), ai_rationale,
                round(min(0.99, 0.5 + intent_score / 200), 2), status,
            ),
        ).fetchone()

        # only qualified postings enter the EMAIL-ONLY queue
        queue_item = None
        if status == "qualified":
            queue_item = conn.execute(
                """INSERT INTO hiring_intent_queue (workspace_id, posting_id, company_id)
                   VALUES (%s,%s,%s)
                   ON CONFLICT (workspace_id, posting_id) DO NOTHING RETURNING *""",
                (user["workspace_id"], str(posting["id"]), company_id),
            ).fetchone()
            # create an expiring timing signal as well
            if company_id:
                conn.execute(
                    """INSERT INTO signals (workspace_id, company_id, type, payload,
                           score, expires_at)
                       VALUES (%s,%s,'hiring',%s,%s, now() + make_interval(days => %s))""",
                    (
                        user["workspace_id"], company_id,
                        json.dumps({"posting_id": str(posting["id"]), "title": req.title}),
                        intent_score, SIGNAL_EXPIRY_DAYS,
                    ),
                )
    return {
        "id": str(posting["id"]),
        "duplicate": False,
        "intent_score": intent_score,
        "intent_category": category,
        "status": status,
        "queued": bool(queue_item),
    }


@router.get("/queue")
def queue(user: dict = Depends(require_workspace)):
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        rows = conn.execute(
            """SELECT q.id, q.status, q.created_at, q.sent_at,
                      p.title, p.intent_score, p.intent_category, p.source_url,
                      p.posted_at, p.qualification_rationale,
                      c.business_name, c.website
               FROM hiring_intent_queue q
               JOIN job_postings p ON p.id = q.posting_id
               LEFT JOIN companies c ON c.id = q.company_id
               WHERE q.workspace_id=%s
               ORDER BY p.intent_score DESC, q.created_at DESC""",
            (user["workspace_id"],),
        ).fetchall()
    # expire stale items
    with db.get_pool().connection() as conn:
        conn.execute(
            """UPDATE hiring_intent_queue SET status='expired'
               WHERE workspace_id=%s AND status IN ('ready','approved')
                 AND created_at < now() - interval '%s days'""",
            (user["workspace_id"], SIGNAL_EXPIRY_DAYS),
        )
    return {"items": rows}


class DraftIn(BaseModel):
    queue_item_id: str


@router.post("/draft")
def draft_email(req: DraftIn, user: dict = Depends(require_workspace)):
    """Hiring-Intent Email Writer — references the ACTUAL posting. Draft-only."""
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        item = conn.execute(
            """SELECT q.id, q.posting_id, q.company_id, p.title, p.description_raw,
                      p.source_url, c.business_name
               FROM hiring_intent_queue q
               JOIN job_postings p ON p.id=q.posting_id
               LEFT JOIN companies c ON c.id=q.company_id
               WHERE q.id=%s AND q.workspace_id=%s AND q.status IN ('ready','approved')""",
            (req.queue_item_id, user["workspace_id"]),
        ).fetchone()
    if item is None:
        raise HTTPException(404, "queue item not found or not actionable")

    excerpt = (item["description_raw"] or "")[:1500]
    parsed = llm.structured_complete(
        agent_name="email_personalization_agent",
        system=(
            "Write a cold email to a home-services contractor who posted a "
            "receptionist-type job. Reference the ACTUAL posting (quote it briefly). "
            "Under 75 words, 4 sentences: Fact / Inference / Offer / Question. "
            "No invented facts."
        ),
        user=json.dumps({
            "business_name": item["business_name"],
            "job_title": item["title"],
            "posting_excerpt": excerpt,
            "offer": "ai_receptionist",
        }),
        required_keys=["subject", "first_sentence", "body", "cta", "followup_angle"],
        workspace_id=user["workspace_id"],
        max_tokens=600,
    )
    body_text = " ".join(filter(None, [parsed.get("first_sentence"), parsed.get("body"),
                                       parsed.get("cta")]))
    if len(body_text.split()) >= 75:
        raise HTTPException(422, f"draft too long ({len(body_text.split())} words)")

    with db.get_pool().connection() as conn:
        msg = conn.execute(
            """INSERT INTO messages (workspace_id, lead_id, channel, direction, subject,
                   body_text, status)
               SELECT %s, NULL, 'email','outbound',%s,%s,'pending_approval'
               RETURNING id""",
            (user["workspace_id"], parsed.get("subject"), body_text),
        ).fetchone()
        # attach draft to a lead-less flow via queue reference
        conn.execute(
            "UPDATE hiring_intent_queue SET drafted_message_id=%s WHERE id=%s",
            (str(msg["id"]), req.queue_item_id),
        )
    return {"message_id": str(msg["id"]), "draft": parsed}


class ApproveIn(BaseModel):
    queue_item_id: str
    message_id: str


@router.post("/approve")
def approve(req: ApproveIn, user: dict = Depends(require_workspace)):
    """Human approval; sending happens through the SAME email gates (verified email,
    CAN-SPAM block, suppression). Queue remains email-only by construction."""
    from app.services import email_service

    email_service.approve(user["workspace_id"], req.message_id, str(user["id"]))
    with db.get_pool().connection() as conn:
        conn.execute(
            """UPDATE hiring_intent_queue SET status='approved', approved_by=%s
               WHERE id=%s AND workspace_id=%s""",
            (str(user["id"]), req.queue_item_id, user["workspace_id"]),
        )
    return {"ok": True}
