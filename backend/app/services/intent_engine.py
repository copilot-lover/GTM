"""GTM_INTENT engine — continuous re-evaluation of existing leads from intent events.

Ingests intent_events, recalculates leads.priority_score deterministically
(base ICP + recency-decayed signal/event contributions), persists an
explainable 'opportunity' scores row for the Why panel, and derives a
P1/P2/P3 priority band. Scores decay naturally as evidence ages past 30 days.
"""

import json
import logging
from datetime import datetime, timezone

import psycopg.rows

import app.db as db

log = logging.getLogger(__name__)

DEFAULT_EVENT_WEIGHTS = {
    "JOB_POSTED": 35,
    "JOB_UPDATED": 15,
    "JOB_REMOVED": -10,
    "NEW_LOCATION": 25,
    "EXPANSION": 25,
    "HEADCOUNT_CHANGE": 15,
    "WEBSITE_CHANGE": 10,
    "TECHNOLOGY_CHANGE": 10,
    "LEADERSHIP_CHANGE": 10,
    "NEW_REVIEW_PATTERN": 10,
    "CONTACT_CHANGE": 10,
}

_extra_event_types: dict[str, int] = {}

EVENT_LOOKBACK_DAYS = 30


def register_event_type(event_type: str, weight: int) -> None:
    _extra_event_types[event_type] = weight


def known_event_types() -> dict[str, int]:
    return {**DEFAULT_EVENT_WEIGHTS, **_extra_event_types}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _age_days(ts: datetime | None) -> float:
    if ts is None:
        return EVENT_LOOKBACK_DAYS + 1
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0.0, (_utcnow() - ts).total_seconds() / 86400)


def ingest_event(
    workspace_id: str,
    *,
    event_type: str,
    company_id: str | None = None,
    lead_id: str | None = None,
    signal_id: str | None = None,
    source: str | None = None,
    payload: dict | None = None,
    occurred_at: datetime | None = None,
) -> dict:
    """Validate + insert one intent_event; resolve lead from company if omitted."""
    if event_type not in known_event_types():
        raise ValueError(f"unknown event_type: {event_type}")

    if lead_id is None and company_id is not None:
        terminal = _terminal_statuses_sql()
        with db.get_pool().connection() as conn:
            conn.row_factory = psycopg.rows.dict_row
            row = conn.execute(
                f"""SELECT id FROM leads
                    WHERE workspace_id=%s AND company_id=%s
                      AND status NOT IN ({terminal})
                    ORDER BY coalesce(priority_score,0) DESC, created_at DESC
                    LIMIT 1""",
                (workspace_id, company_id),
            ).fetchone()
        if row:
            lead_id = str(row["id"])

    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        row = conn.execute(
            """INSERT INTO intent_events
                   (workspace_id, company_id, lead_id, signal_id, event_type,
                    source, payload, occurred_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,COALESCE(%s, now()))
               RETURNING *""",
            (
                workspace_id, company_id, lead_id, signal_id, event_type,
                source, json.dumps(payload or {}), occurred_at,
            ),
        ).fetchone()

    try:
        from app.services import job_queue

        job_queue.enqueue(
            type="gtm_intent_process",
            pool="ai",
            payload={"workspace_id": str(workspace_id)},
            idempotency_key=f"intent-process-{row['id']}",
        )
    except Exception as e:  # queue optional
        log.warning(f"intent process enqueue failed: {e}")

    return row


def process_pending_events(workspace_id: str, limit: int = 200) -> dict:
    """Claim unprocessed events batch-safely, re-evaluate affected leads."""
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        claimed = conn.execute(
            """UPDATE intent_events SET processed=true, processed_at=now()
               WHERE id IN (
                   SELECT id FROM intent_events
                   WHERE processed=false AND workspace_id=%s
                   ORDER BY occurred_at ASC
                   LIMIT %s
                   FOR UPDATE SKIP LOCKED
               ) RETURNING *""",
            (workspace_id, limit),
        ).fetchall()

    lead_ids: set[str] = set()
    company_ids: set[str] = set()
    for ev in claimed:
        if ev["lead_id"]:
            lead_ids.add(str(ev["lead_id"]))
        elif ev["company_id"]:
            company_ids.add(str(ev["company_id"]))

    for cid in company_ids:
        lid = _resolve_lead_for_company(workspace_id, cid)
        if lid:
            lead_ids.add(lid)

    for lid in sorted(lead_ids):
        try:
            reevaluate_lead(workspace_id, lid)
        except ValueError:
            log.warning(f"reevaluate skipped, lead missing: {lid}")

    return {"processed": len(claimed), "leads_reevaluated": len(lead_ids)}


def _resolve_lead_for_company(workspace_id: str, company_id: str) -> str | None:
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        row = conn.execute(
            f"""SELECT id FROM leads
                WHERE workspace_id=%s AND company_id=%s
                  AND status NOT IN ({_terminal_statuses_sql()})
                ORDER BY coalesce(priority_score,0) DESC, created_at DESC
                LIMIT 1""",
            (workspace_id, company_id),
        ).fetchone()
    return str(row["id"]) if row else None


def _terminal_statuses_sql() -> str:
    from app.services.state_machine import TERMINAL

    return ",".join(f"'{s}'" for s in sorted(TERMINAL))


# hiring_signals.signal_score is a 0-100 composite already scaled to match the
# top event weight (JOB_POSTED=35); capping each signal at 35 keeps one signal
# from dominating while letting multiple signals stack toward the 100 clamp.
MAX_SIGNAL_CONTRIBUTION = 35


def reevaluate_lead(workspace_id: str, lead_id: str) -> dict:
    """Full deterministic recalculation of a lead's priority score."""
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        lead = conn.execute(
            "SELECT * FROM leads WHERE id=%s AND workspace_id=%s",
            (lead_id, workspace_id),
        ).fetchone()
    if not lead:
        raise ValueError(f"Lead {lead_id} not found")

    company_id = lead["company_id"]
    base_icp = int((lead["lead_score"] or 0) * 10)

    contributions: list[dict] = []

    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        signals = conn.execute(
            """SELECT id, role_category, signal_score, freshness_multiplier, posted_at
               FROM hiring_signals
               WHERE company_id=%s AND workspace_id=%s AND status='active'""",
            (company_id, workspace_id),
        ).fetchall()
        events = conn.execute(
            """SELECT id, event_type, occurred_at FROM intent_events
               WHERE (company_id=%s OR lead_id=%s)
                 AND workspace_id=%s
                 AND occurred_at >= now() - interval '30 days'""",
            (company_id, lead_id, workspace_id),
        ).fetchall()

    freshest_age = None
    for s in signals:
        age = _age_days(s["posted_at"])
        recency = max(0.0, 1 - age / EVENT_LOOKBACK_DAYS)
        points = round(
            min(MAX_SIGNAL_CONTRIBUTION,
                float(s["signal_score"] or 0) * float(s["freshness_multiplier"] or 0) * recency),
            1,
        )
        label = f"{s['role_category']} hiring"
        contributions.append({
            "label": label, "points": points,
            "evidence_ref": str(s["id"]), "age_days": round(age, 1),
        })
        freshest_age = age if freshest_age is None else min(freshest_age, age)

    weights = known_event_types()
    for ev in events:
        age = _age_days(ev["occurred_at"])
        recency = max(0.0, 1 - age / EVENT_LOOKBACK_DAYS)
        points = round(weights.get(ev["event_type"], 0) * recency, 1)
        contributions.append({
            "label": ev["event_type"], "points": points,
            "evidence_ref": str(ev["id"]), "age_days": round(age, 1),
        })
        freshest_age = age if freshest_age is None else min(freshest_age, age)

    total = base_icp + sum(c["points"] for c in contributions)
    signal_count = len(contributions)
    if signal_count >= 4:
        total += 10
    elif signal_count >= 2:
        total += 5
    total = max(0, min(100, round(total)))

    components = {
        "source": "GTM_INTENT",
        "base_icp": base_icp,
        "contributions": contributions,
        "signal_count": signal_count,
        "computed_at": _utcnow().isoformat(),
    }

    if total >= 70 and freshest_age is not None and freshest_age <= 7:
        priority = "P1"
    elif total >= 50 or _has_tier_a(lead_id):
        priority = "P2"
    else:
        priority = "P3"

    with db.get_pool().connection() as conn:
        conn.execute(
            "UPDATE leads SET priority_score=%s, updated_at=now() WHERE id=%s",
            (total, lead_id),
        )
        conn.execute(
            """INSERT INTO scores (workspace_id, lead_id, score_type, score, components)
               VALUES (%s,%s,'opportunity',%s,%s)""",
            (workspace_id, lead_id, total, json.dumps(components)),
        )

    return {
        "lead_id": str(lead_id),
        "opportunity_score": total,
        "priority": priority,
        "components": components,
    }


def _has_tier_a(lead_id: str) -> bool:
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        row = conn.execute(
            """SELECT tier FROM scores
               WHERE lead_id=%s AND score_type='opportunity' AND tier IS NOT NULL
               ORDER BY computed_at DESC LIMIT 1""",
            (lead_id,),
        ).fetchone()
    return bool(row) and row["tier"] in ("A", "A+")
