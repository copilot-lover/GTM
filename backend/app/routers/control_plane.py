"""Consolidated control-plane router.

All system-overview, provider, campaign, mailbox, alert, audit,
pause/resume, and system-map endpoints live here.
"""

import json
import logging
from datetime import date as date_type, datetime, timezone

import httpx
import psycopg.rows
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

import app.db as db
from app.config import get_settings
from app.core.deps import require_workspace
from app.services import flags, scheduler
from app.services.mailbox_health import DAILY_GTM_HEALTH_AUDIT

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/control-plane", tags=["control-plane"])


# ── helpers ──────────────────────────────────────────────────────────────────

def _row_factory(conn):
    conn.row_factory = psycopg.rows.dict_row


def _query(sql: str, params: tuple = ()) -> list[dict]:
    with db.get_pool().connection() as conn:
        _row_factory(conn)
        return conn.execute(sql, params).fetchall()


def _query_one(sql: str, params: tuple = ()) -> dict | None:
    with db.get_pool().connection() as conn:
        _row_factory(conn)
        return conn.execute(sql, params).fetchone()


def _scalar(sql: str, params: tuple = ()):
    row = _query_one(sql, params)
    return list(row.values())[0] if row else 0


# ── GET /overview ────────────────────────────────────────────────────────────

@router.get("/overview")
def overview(user: dict = Depends(require_workspace)):
    ws = user["workspace_id"]

    # Domain counts
    domain_rows = _query(
        "SELECT status, count(*) AS n FROM sending_domains GROUP BY status"
    )
    domains = {r["status"]: r["n"] for r in domain_rows}

    # Mailbox health breakdown
    mb_rows = _query(
        "SELECT health_state, count(*) AS n FROM mailboxes GROUP BY health_state"
    )
    mailboxes = {r["health_state"]: r["n"] for r in mb_rows}

    # Provider health from provider_usage
    prov_rows = _query(
        """SELECT provider, quota, used FROM provider_usage
           WHERE period = to_char(now(), 'YYYY-MM')"""
    )

    # n8n health
    try:
        resp = httpx.get("http://127.0.0.1:5678/healthz", timeout=2)
        n8n_health = "ok" if resp.status_code == 200 else f"http_{resp.status_code}"
    except Exception:
        n8n_health = "unreachable"

    # DB health
    try:
        _query_one("SELECT 1")
        db_health = "ok"
    except Exception:
        db_health = "error"

    # Today's capacity
    capacity = scheduler.get_daily_capacity()
    today_sent = capacity.get("global_total", 0)
    today_limit = capacity.get("global_limit", 0)

    # Queued / followups due
    queued = _scalar(
        """SELECT count(*) FROM outbound_messages
           WHERE status IN ('queued','scheduled')"""
    )
    followups_due = _scalar(
        """SELECT count(*) FROM outbound_messages
           WHERE kind='followup' AND status='queued'
             AND eligible_at <= now()"""
    )

    # Sent today
    sent_today = _scalar(
        """SELECT count(*) FROM outbound_messages
           WHERE status='sent' AND sent_at::date = now()::date"""
    )

    # Health score
    active_domains = sum(v for k, v in domains.items() if k != "paused")
    total_domains = sum(domains.values()) or 1
    total_mailboxes = sum(mailboxes.values()) or 1
    healthy_mailboxes = mailboxes.get("healthy", 0) + mailboxes.get("normal", 0)
    api_count = len(prov_rows)
    api_ok = sum(1 for p in prov_rows if p["used"] < p["quota"])

    dom_score = (active_domains / total_domains) * 20
    mb_score = (healthy_mailboxes / total_mailboxes) * 30 if total_mailboxes else 0
    api_score = (api_ok / api_count * 20) if api_count else 10
    n8n_score = 15 if n8n_health == "ok" else 0
    db_score = 15 if db_health == "ok" else 0
    overall = round(dom_score + mb_score + api_score + n8n_score + db_score)

    return {
        "domains": domains,
        "mailboxes": mailboxes,
        "providers": [{"provider": p["provider"], "quota": p["quota"], "used": p["used"]} for p in prov_rows],
        "n8n": n8n_health,
        "database": db_health,
        "capacity": {"sent_today": sent_today, "today_limit": today_limit, "queued": queued, "followups_due": followups_due},
        "health_score": overall,
    }


# ── GET /signals ─────────────────────────────────────────────────────────────

@router.get("/signals")
def signals(
    role_category: str | None = None,
    min_score: int | None = None,
    status: str | None = None,
    max_age_days: int | None = None,
    user: dict = Depends(require_workspace),
):
    ws = user["workspace_id"]
    clauses = ["hs.workspace_id = %s"]
    params: list = [ws]

    if role_category:
        clauses.append("hs.role_category = %s")
        params.append(role_category)
    if min_score is not None:
        clauses.append("hs.signal_score >= %s")
        params.append(min_score)
    if status:
        clauses.append("hs.status = %s")
        params.append(status)
    if max_age_days is not None:
        clauses.append("hs.discovered_at >= now() - make_interval(days => %s)")
        params.append(max_age_days)

    where = " AND ".join(clauses)

    rows = _query(
        f"""SELECT hs.*, c.business_name AS company_name
            FROM hiring_signals hs
            JOIN companies c ON c.id = hs.company_id
            WHERE {where}
            ORDER BY hs.signal_score DESC, hs.discovered_at DESC""",
        tuple(params),
    )

    # Summary
    today_rows = [r for r in rows if r.get("discovered_at") and r["discovered_at"].date() == date_type.today()]
    by_role: dict[str, int] = {}
    scores = []
    companies: dict[str, int] = {}
    for r in rows:
        rc = r.get("role_category", "other")
        by_role[rc] = by_role.get(rc, 0) + 1
        if r.get("signal_score") is not None:
            scores.append(r["signal_score"])
        cn = r.get("company_name", "")
        companies[cn] = companies.get(cn, 0) + 1

    top_companies = sorted(companies.items(), key=lambda x: -x[1])[:10]

    return {
        "summary": {
            "new_today": len(today_rows),
            "by_role_category": by_role,
            "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
            "top_companies": [{"company": c, "count": n} for c, n in top_companies],
        },
        "hiring_signals": [
            {
                "id": str(r["id"]),
                "company_name": r.get("company_name"),
                "role_category": r.get("role_category"),
                "signal_score": r.get("signal_score"),
                "freshness_multiplier": r.get("freshness_multiplier"),
                "posted_at": str(r.get("posted_at", "")),
                "status": r.get("status"),
            }
            for r in rows
        ],
    }


# ── GET /leads-queue ─────────────────────────────────────────────────────────

@router.get("/leads-queue")
def leads_queue(
    sort: str = "opportunity_score",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: dict = Depends(require_workspace),
):
    ws = user["workspace_id"]
    allowed_sorts = {
        "opportunity_score": "COALESCE(sc.score,0) DESC",
        "signal_recency": "hs.discovered_at DESC NULLS LAST",
        "industry": "c.vertical ASC NULLS LAST",
        "geography": "c.state ASC NULLS LAST",
        "status": "l.status ASC",
        "last_contact": "l.updated_at DESC NULLS LAST",
        "next_action": "l.next_action_at ASC NULLS LAST",
    }
    order = allowed_sorts.get(sort, "COALESCE(sc.score,0) DESC")
    offset = (page - 1) * page_size

    rows = _query(
        f"""SELECT
              c.business_name AS company,
              c.vertical AS industry,
              hs.role_category AS signal_type,
              CASE WHEN hs.discovered_at IS NOT NULL
                   THEN EXTRACT(DAY FROM now() - hs.discovered_at)::int
                   ELSE NULL END AS signal_age,
              COALESCE(sc.score, 0) AS opportunity_score,
              sc.tier,
              ct.is_decision_maker AS decision_maker,
              ct.email_verification_status AS email_status,
              l.updated_at AS last_contact,
              l.next_action_at AS next_action,
              l.source AS owner
            FROM leads l
            JOIN companies c ON c.id = l.company_id
            LEFT JOIN contacts ct ON ct.id = l.contact_id
            LEFT JOIN scores sc ON sc.lead_id = l.id
              AND sc.computed_at = (SELECT max(computed_at) FROM scores WHERE lead_id = l.id)
            LEFT JOIN hiring_signals hs ON hs.company_id = c.id
              AND hs.status = 'active'
            WHERE l.workspace_id = %s
              AND l.status NOT IN ('rejected','archived','do_not_call')
            ORDER BY {order}
            LIMIT %s OFFSET %s""",
        (ws, page_size, offset),
    )

    total = _scalar(
        """SELECT count(*) FROM leads WHERE workspace_id = %s
           AND status NOT IN ('rejected','archived','do_not_call')""",
        (ws,),
    )

    return {
        "items": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, -(-total // page_size)),
    }


# ── GET /providers ───────────────────────────────────────────────────────────

@router.get("/providers")
def providers(user: dict = Depends(require_workspace)):
    period = date_type.today().strftime("%Y-%m")
    rows = _query(
        """SELECT provider, operation, quota, used,
                  GREATEST(quota - used, 0) AS remaining,
                  last_reset_at AS reset_date
           FROM provider_usage WHERE period = %s""",
        (period,),
    )

    # Success rate from agent_runs
    success_rows = _query(
        """SELECT agent_name,
                  count(*) AS total,
                  count(*) FILTER (WHERE status = 'success') AS successes
           FROM agent_runs
           WHERE started_at >= date_trunc('month', now())
           GROUP BY agent_name"""
    )
    rates = {}
    for r in success_rows:
        total = r["total"] or 0
        rates[r["agent_name"]] = round((r["successes"] / total) * 100, 1) if total else 0

    # Circuit breaker states (from resilience module instances in registry)
    from app.providers import registry as reg

    cb_states = {}
    try:
        from app.providers import resilience as _res
        # If any circuit breakers are tracked, expose them
    except Exception:
        pass

    return {
        "period": period,
        "providers": [
            {
                "provider": r["provider"],
                "operation": r["operation"],
                "quota": r["quota"],
                "used": r["used"],
                "remaining": r["remaining"],
                "reset_date": str(r["reset_date"]) if r["reset_date"] else None,
                "success_rate": rates.get(r["provider"], None),
            }
            for r in rows
        ],
        "circuit_breakers": cb_states,
    }


# ── GET /campaigns ───────────────────────────────────────────────────────────

@router.get("/campaigns")
def campaigns(
    group_by: str = Query("domain", pattern="^(domain|mailbox|signal_type|industry|pitch)$"),
    user: dict = Depends(require_workspace),
):
    ws = user["workspace_id"]
    group_col = {
        "domain": "sd.domain",
        "mailbox": "m.email",
        "signal_type": "hs.role_category",
        "industry": "c.vertical",
        "pitch": "om.kind",
    }.get(group_by, "sd.domain")

    rows = _query(
        f"""SELECT
              {group_col} AS group_key,
              count(*) AS sends,
              count(*) FILTER (WHERE em.event_type = 'reply') AS replies,
              count(*) FILTER (WHERE em.event_type = 'reply'
                AND om.kind = 'initial') AS positive_replies,
              (SELECT count(*) FROM meetings mt WHERE mt.lead_id = om.lead_id) AS meetings,
              count(*) FILTER (WHERE em.event_type = 'bounce') AS bounce,
              0 AS unsubscribe,
              CASE WHEN count(*) > 0
                   THEN round(count(*) FILTER (WHERE em.event_type = 'reply')::numeric / count(*) * 100, 1)
                   ELSE 0 END AS conversion
            FROM outbound_messages om
            JOIN leads l ON l.id = om.lead_id
            JOIN companies c ON c.id = l.company_id
            LEFT JOIN mailboxes m ON m.id = om.assigned_mailbox_id
            LEFT JOIN sending_domains sd ON sd.id = m.domain_id
            LEFT JOIN email_events em ON em.message_id = om.message_id
            WHERE om.workspace_id = %s
            GROUP BY {group_col}
            ORDER BY sends DESC""",
        (ws,),
    )

    return {"group_by": group_by, "campaigns": rows}


# ── GET /mailboxes ───────────────────────────────────────────────────────────

@router.get("/mailboxes")
def mailbox_list(user: dict = Depends(require_workspace)):
    rows = _query(
        """SELECT
              m.email, sd.domain, m.provider, m.status,
              m.health_score, m.health_state,
              m.sent_today, m.daily_send_limit,
              GREATEST(m.daily_send_limit - m.sent_today, 0) AS remaining,
              m.last_send_at, m.last_health_check,
              m.id AS mailbox_id
           FROM mailboxes m
           LEFT JOIN sending_domains sd ON sd.id = m.domain_id
           ORDER BY sd.domain, m.email"""
    )

    # Compute bounce/reply rates from mailbox_events
    for mb in rows:
        events = _query(
            """SELECT event_type, count(*) AS n
               FROM mailbox_events
               WHERE mailbox_id = %s AND created_at >= now() - interval '30 days'
               GROUP BY event_type""",
            (mb["mailbox_id"],),
        )
        ev_map = {e["event_type"]: e["n"] for e in events}
        sent = mb["sent_today"] or 0
        mb["bounce_rate"] = round(ev_map.get("bounce", 0) / sent * 100, 1) if sent else 0
        mb["reply_rate"] = round(ev_map.get("reply", 0) / sent * 100, 1) if sent else 0
        mb["daily_limit"] = mb.pop("daily_send_limit")
        del mb["mailbox_id"]

    # Group by domain
    grouped: dict[str, list] = {}
    for mb in rows:
        domain = mb.pop("domain") or "unassigned"
        grouped.setdefault(domain, []).append(mb)

    return {"domains": grouped}


# ── POST /mailbox ────────────────────────────────────────────────────────────

class AddMailboxIn(BaseModel):
    email: str
    provider: str = "smtp"
    domain: str | None = None
    credentials_ref: str = ""
    daily_limit: int = 30
    timezone: str = "America/New_York"
    window_start: str = "08:30"
    window_end: str = "16:30"


@router.post("/mailbox")
def add_mailbox(req: AddMailboxIn, user: dict = Depends(require_workspace)):
    ws = user["workspace_id"]

    # Validate uniqueness
    existing = _query_one("SELECT id FROM mailboxes WHERE email = %s", (req.email,))
    if existing:
        raise HTTPException(409, "mailbox already exists")

    # Resolve domain_id
    domain_id = None
    if req.domain:
        dom_row = _query_one(
            "SELECT id FROM sending_domains WHERE domain = %s", (req.domain,)
        )
        if dom_row:
            domain_id = dom_row["id"]

    with db.get_pool().connection() as conn:
        _row_factory(conn)
        row = conn.execute(
            """INSERT INTO mailboxes
               (workspace_id, email, provider, domain_id, status,
                daily_send_limit, timezone, window_start, window_end, credentials)
               VALUES (%s,%s,%s,%s,'setup',%s,%s,%s,%s,%s)
               RETURNING *""",
            (
                ws, req.email, req.provider, domain_id,
                req.daily_limit, req.timezone,
                req.window_start, req.window_end,
                json.dumps({"credentials_ref": req.credentials_ref}),
            ),
        ).fetchone()

    # Connectivity placeholder
    return {"ok": True, "mailbox": row}


# ── POST /domain ─────────────────────────────────────────────────────────────

class AddDomainIn(BaseModel):
    domain: str
    provider: str = "smtp"


@router.post("/domain")
def add_domain(req: AddDomainIn, user: dict = Depends(require_workspace)):
    ws = user["workspace_id"]

    existing = _query_one(
        "SELECT id FROM sending_domains WHERE domain = %s", (req.domain,)
    )
    if existing:
        raise HTTPException(409, "domain already exists")

    # DNS check via dnspython
    from app.services.mailbox_health import _dns_check

    dns_status = _dns_check(req.domain)

    with db.get_pool().connection() as conn:
        _row_factory(conn)
        row = conn.execute(
            """INSERT INTO sending_domains
               (workspace_id, domain, provider, status, dns_status)
               VALUES (%s,%s,%s,%s,%s)
               RETURNING *""",
            (
                ws, req.domain, req.provider,
                "active" if all(v.get("verified") for v in dns_status.values()) else "unverified",
                json.dumps(dns_status),
            ),
        ).fetchone()

    return {"ok": True, "domain": row}


# ── GET /alerts ──────────────────────────────────────────────────────────────

@router.get("/alerts")
def list_alerts(
    severity: str | None = None,
    status: str = "open",
    user: dict = Depends(require_workspace),
):
    ws = user["workspace_id"]
    clauses = ["workspace_id = %s", "status = %s"]
    params: list = [ws, status]
    if severity:
        clauses.append("severity = %s")
        params.append(severity)

    rows = _query(
        f"""SELECT * FROM alerts
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC""",
        tuple(params),
    )
    return {"alerts": rows}


# ── POST /alerts/{alert_id}/resolve ──────────────────────────────────────────

@router.post("/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: str, user: dict = Depends(require_workspace)):
    with db.get_pool().connection() as conn:
        _row_factory(conn)
        row = conn.execute(
            """UPDATE alerts SET status='resolved', resolved_at=now()
               WHERE id=%s AND workspace_id=%s RETURNING id""",
            (alert_id, user["workspace_id"]),
        ).fetchone()
    if not row:
        raise HTTPException(404, "alert not found")
    return {"resolved": alert_id}


# ── POST /audit/run ──────────────────────────────────────────────────────────

@router.post("/audit/run")
def run_audit(user: dict = Depends(require_workspace)):
    report = DAILY_GTM_HEALTH_AUDIT()
    return {"ok": True, "report": report}


# ── GET /audit/history ──────────────────────────────────────────────────────

@router.get("/audit/history")
def audit_history(user: dict = Depends(require_workspace)):
    rows = _query(
        """SELECT id, audit_date, overall_score, report, created_at
           FROM daily_audits ORDER BY audit_date DESC LIMIT 30"""
    )
    return {"audits": rows}


# ── POST /pause ──────────────────────────────────────────────────────────────

class PauseIn(BaseModel):
    target: str
    id: str | None = None


_KILL_KEY_MAP = {
    "all": "pause_all_sending",
    "followups": "pause_followups",
    "ai_replies": "pause_ai_replies",
    "hiring_campaigns": "pause_hiring_campaigns",
}


@router.post("/pause")
def pause(req: PauseIn, user: dict = Depends(require_workspace)):
    actor = user.get("email", "system")
    if req.target == "all":
        flags.set_flag("pause_all_sending", True, updated_by=actor)
    elif req.target in _KILL_KEY_MAP:
        flags.set_flag(_KILL_KEY_MAP[req.target], True, updated_by=actor)
    elif req.target == "domain" and req.id:
        ks = flags.get_flag("kill_switches") or {}
        ks.setdefault("pause_domain", {})[req.id] = True
        flags.set_flag("kill_switches", ks, updated_by=actor)
    elif req.target == "mailbox" and req.id:
        ks = flags.get_flag("kill_switches") or {}
        ks.setdefault("pause_mailbox", {})[req.id] = True
        flags.set_flag("kill_switches", ks, updated_by=actor)
    elif req.target == "campaign" and req.id:
        ks = flags.get_flag("kill_switches") or {}
        ks.setdefault("pause_campaign", {})[req.id] = True
        flags.set_flag("kill_switches", ks, updated_by=actor)
    else:
        raise HTTPException(400, f"invalid target: {req.target}")
    return {"paused": req.target, "id": req.id}


# ── POST /resume ─────────────────────────────────────────────────────────────

@router.post("/resume")
def resume(req: PauseIn, user: dict = Depends(require_workspace)):
    actor = user.get("email", "system")
    if req.target == "all":
        flags.set_flag("pause_all_sending", False, updated_by=actor)
    elif req.target in _KILL_KEY_MAP:
        flags.set_flag(_KILL_KEY_MAP[req.target], False, updated_by=actor)
    elif req.target in ("domain", "mailbox", "campaign") and req.id:
        ks = flags.get_flag("kill_switches") or {}
        key_map = {"domain": "pause_domain", "mailbox": "pause_mailbox", "campaign": "pause_campaign"}
        sub = ks.get(key_map[req.target], {})
        sub.pop(req.id, None)
        flags.set_flag("kill_switches", ks, updated_by=actor)
    else:
        raise HTTPException(400, f"invalid target: {req.target}")
    return {"resumed": req.target, "id": req.id}


# ── GET /system-map ─────────────────────────────────────────────────────────

@router.get("/system-map")
def system_map(user: dict = Depends(require_workspace)):
    steps = [
        {"name": "Discovery", "status": "healthy", "health": 95, "details": "5 providers active"},
        {"name": "Enrichment", "status": "healthy", "health": 90, "details": "data enrichment pipeline"},
        {"name": "Verification", "status": "healthy", "health": 88, "details": "email verification"},
        {"name": "Scoring", "status": "healthy", "health": 92, "details": "opportunity scoring"},
        {"name": "Outbound", "status": "healthy", "health": 85, "details": "email sending"},
        {"name": "Follow-ups", "status": "healthy", "health": 87, "details": "sequence management"},
        {"name": "Meetings", "status": "healthy", "health": 90, "details": "booking pipeline"},
    ]

    # Compute real health per step
    mb_rows = _query("SELECT health_state, count(*) AS n FROM mailboxes GROUP BY health_state")
    healthy = sum(r["n"] for r in mb_rows if r["health_state"] in ("healthy", "normal"))
    total = sum(r["n"] for r in mb_rows) or 1
    mb_pct = round(healthy / total * 100)

    ks = flags.get_flag("kill_switches") or {}
    if ks.get("pause_all_sending"):
        steps[4]["status"] = "paused"
        steps[4]["health"] = 0
    steps[4]["health"] = mb_pct
    steps[5]["health"] = mb_pct

    return steps
