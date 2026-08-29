"""Hiring-intent pipeline — ISOLATED subsystem, EMAIL ONLY (spec §8).
No code path here touches the dialer, SMS, or normal cold outreach."""

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from psycopg.rows import dict_row

import app.db as db
from app.core.deps import require_workspace
from app.services import scoring, hiring_signals

router = APIRouter(prefix="/hiring-intent", tags=["hiring-intent"])

SIGNAL_EXPIRY_DAYS = 30


class IngestFromProvidersIn(BaseModel):
    provider: str | None = None
    filters: dict[str, Any] | None = None


class SignalOut(BaseModel):
    id: str
    workspace_id: str
    company_id: str
    source: str
    source_job_id: str | None
    job_url: str | None
    title: str
    description: str
    role_category: str
    intent_category: str
    pain_hypothesis: str | None
    orbit_product_fit: str | None
    confidence: float
    signal_score: int
    freshness_multiplier: float
    expires_at: datetime | None
    status: str
    posted_at: datetime | None
    discovered_at: datetime


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


def detect_description_signals(description: str | None) -> dict:
    """Deterministic keyword detection of §8.4 signals — works without an LLM."""
    if not description:
        return {}
    d = description.lower()
    return {
        "after_hours": any(k in d for k in (
            "after hours", "after-hours", "evening", "weekend", "on-call")),
        "phone_heavy": any(k in d for k in (
            "inbound calls", "incoming calls", "answer calls", "answering calls",
            "phone calls", "multi-line", "multiline", "50+")),
        "scheduling_duties": any(k in d for k in (
            "schedul", "appointment", "book jobs", "dispatch")),
        "icp_match": any(k in d for k in (
            "hvac", "plumb", "electric", "roofing", "home services",
            "heating", "air conditioning")),
    }


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
    contact_id = None
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
            contact = conn.execute(
                """INSERT INTO contacts (workspace_id, company_id, email,
                       email_verification_status, source_url)
                   VALUES (%s,%s,%s,'unknown',%s) RETURNING id""",
                (user["workspace_id"], company_id, req.contact_email.lower(),
                 req.source_url),
            ).fetchone()
            contact_id = str(contact["id"])

    role_key, _ = classify_role(req.title)
    description_signals = detect_description_signals(req.description_raw)

    days_old = ((datetime.now(timezone.utc) - req.posted_at).days
                if req.posted_at else None)
    intent_score = scoring.hiring_intent_score(
        role_key=role_key,
        icp_match=bool(description_signals.get("icp_match")),
        after_hours=bool(description_signals.get("after_hours")),
        phone_heavy=bool(description_signals.get("phone_heavy")),
        scheduling_duties=bool(description_signals.get("scheduling_duties")),
        multiple_openings=False,
        days_old=days_old,
        multiple_locations=False,
    )

    ai_rationale = (
        "deterministic keyword match: "
        + (", ".join(k for k, v in description_signals.items() if v) or "no signals found")
    )
    relevant_responsibilities: list = []

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
                """INSERT INTO hiring_intent_queue (workspace_id, posting_id,
                       company_id, contact_id)
                   VALUES (%s,%s,%s,%s)
                   ON CONFLICT (workspace_id, posting_id) DO NOTHING RETURNING *""",
                (user["workspace_id"], str(posting["id"]), company_id, contact_id),
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
    from app.services import events

    with db.get_pool().connection() as conn:
        events.emit(
            conn, event_type="hiring.refine_requested",
            payload={"posting_id": str(posting["id"]),
                     "title": req.title,
                     "description": (req.description_raw or "")[:8000]},
            workspace_id=user["workspace_id"],
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
    # expire stale items BEFORE reading so a single call reflects reality
    with db.get_pool().connection() as conn:
        conn.execute(
            """UPDATE hiring_intent_queue SET status='expired'
               WHERE workspace_id=%s AND status IN ('ready','approved')
                 AND created_at < now() - interval '%s days'""",
            (user["workspace_id"], SIGNAL_EXPIRY_DAYS),
        )
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
    # context for n8n's LLM call; backend never calls the LLM itself
    return {
        "queue_item_id": req.queue_item_id,
        "system": (
            "Write a cold email to a home-services contractor who posted a "
            "receptionist-type job. Reference the ACTUAL posting (quote it briefly). "
            "Under 75 words, 4 sentences: Fact / Inference / Offer / Question. "
            "No invented facts. Return ONLY JSON with keys: subject, first_sentence, "
            "body, cta, followup_angle."
        ),
        "user": json.dumps({
            "business_name": item["business_name"],
            "job_title": item["title"],
            "posting_excerpt": excerpt,
            "offer": "ai_receptionist",
        }),
    }


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


@router.post("/ingest-from-providers")
def ingest_from_providers(req: IngestFromProvidersIn, user: dict = Depends(require_workspace)):
    """Discover jobs from registered job source adapters, normalize, upsert hiring_signals."""
    from app.providers import registry, ProviderUnavailable

    provider_name = req.provider
    filters = req.filters or {}
    query = filters.get("title_contains", "") or "receptionist dispatcher customer service"

    providers_to_use = []
    if provider_name:
        try:
            providers_to_use.append((provider_name, registry.get(provider_name)))
        except ProviderUnavailable:
            raise HTTPException(404, f"Provider '{provider_name}' not available")
    else:
        for name in ("jobspipe", "theirstack", "jsearch", "fantastic_jobs", "adzuna"):
            try:
                providers_to_use.append((name, registry.get(name)))
            except ProviderUnavailable:
                pass

    if not providers_to_use:
        return {"ingested": 0, "by_provider": {}, "errors": ["no providers available"]}

    total_ingested = 0
    by_provider = {}
    errors = []

    for name, provider in providers_to_use:
        try:
            postings = provider.search(query, filters)
            postings = hiring_signals.dedupe_postings(postings)
            count = 0
            for raw in postings:
                signal_id = hiring_signals.upsert_hiring_signal(user["workspace_id"], raw, name)
                if signal_id:
                    count += 1
            total_ingested += count
            by_provider[name] = count
        except Exception as e:
            errors.append(f"{name}: {e}")

    return {"ingested": total_ingested, "by_provider": by_provider, "errors": errors}


@router.get("/signals")
def list_signals(
    user: dict = Depends(require_workspace),
    status: str | None = Query(None),
    role_category: str | None = Query(None),
    min_score: int | None = Query(None),
    max_age_days: int | None = Query(None),
    company_id: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
):
    """Filtered list of hiring signals with pagination."""
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        where = ["hs.workspace_id = %s"]
        params = [user["workspace_id"]]
        if status:
            where.append("hs.status = %s")
            params.append(status)
        if role_category:
            where.append("hs.role_category = %s")
            params.append(role_category)
        if min_score is not None:
            where.append("hs.signal_score >= %s")
            params.append(min_score)
        if max_age_days is not None:
            where.append("hs.posted_at >= now() - interval '%s days'" % max_age_days)
        if company_id:
            where.append("hs.company_id = %s")
            params.append(company_id)
        where_sql = " AND ".join(where)
        rows = conn.execute(
            f"""SELECT hs.* FROM hiring_signals hs
               WHERE {where_sql}
               ORDER BY hs.signal_score DESC, hs.discovered_at DESC
               LIMIT %s OFFSET %s""",
            (*params, limit, offset),
        ).fetchall()
    return {"items": rows, "limit": limit, "offset": offset}


@router.post("/refresh-scores")
def refresh_scores(user: dict = Depends(require_workspace)):
    """Recompute scores for all active signals using current company data."""
    count = hiring_signals.refresh_scores(user["workspace_id"])
    return {"refreshed": count}
