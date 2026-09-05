"""Mailbox health scoring + daily audit.

Scoring weights: bounce_rate 40, complaint_rate 30, delivery_rate 15,
volume_consistency 10, recent_failures 5.  States map: >=90 healthy,
>=75 normal, >=60 reduced, >=40 restricted, else paused.
"""

import statistics
from datetime import datetime, timedelta, timezone

import psycopg.rows

import app.db as db


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def compute_health_score(mailbox_id: str) -> int:
    """Return 0-100 composite health score for a mailbox."""
    now = datetime.now(timezone.utc)
    last_30 = now - timedelta(days=30)
    last_7 = now - timedelta(days=7)

    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row

        # Bounce + complaint + delivery counts (last 30d)
        ev30 = conn.execute(
            """SELECT event_type, COUNT(*) AS cnt
               FROM mailbox_events
               WHERE mailbox_id=%s AND created_at >= %s
               GROUP BY event_type""",
            (mailbox_id, last_30),
        ).fetchall()
        events_map = {r["event_type"]: r["cnt"] for r in ev30}

        # Send counts (last 30d)
        sends30 = conn.execute(
            """SELECT COUNT(*) AS total,
                      COUNT(*) FILTER (WHERE status='sent') AS delivered
               FROM outbound_messages
               WHERE assigned_mailbox_id=%s AND created_at >= %s""",
            (mailbox_id, last_30),
        ).fetchone() or {"total": 0, "delivered": 0}

        # Daily sent volumes (last 7d) for consistency
        daily_rows = conn.execute(
            """SELECT date(created_at) AS d, COUNT(*) AS cnt
               FROM outbound_messages
               WHERE assigned_mailbox_id=%s AND created_at >= %s
               GROUP BY date(created_at) ORDER BY d""",
            (mailbox_id, last_7),
        ).fetchall()

        # Failed attempts (last 7d)
        failures_7d = conn.execute(
            """SELECT COUNT(*) AS cnt
               FROM outbound_messages
               WHERE assigned_mailbox_id=%s AND created_at >= %s
                 AND status='failed'""",
            (mailbox_id, last_7),
        ).fetchone() or {"cnt": 0}

    sent_total = sends30["total"] or 0
    delivered = sends30["delivered"] or 0
    bounces = events_map.get("bounce", 0)
    complaints = events_map.get("complaint", 0)
    failed_recent = failures_7d["cnt"] or 0

    # --- Individual components (0-100 each) ---
    # bounce_rate: lower is better. 0%→100, >=20%→0
    if sent_total > 0:
        bounce_pct = bounces / sent_total
        bounce_comp = max(0, 100 - bounce_pct * 500)
    else:
        bounce_comp = 100

    # complaint_rate: lower is better. 0%→100, >=1%→0
    if sent_total > 0:
        complaint_pct = complaints / sent_total
        complaint_comp = max(0, 100 - complaint_pct * 10000)
    else:
        complaint_comp = 100

    # delivery_rate: higher is better. 100%→100, 0%→0
    if sent_total > 0:
        delivery_comp = (delivered / sent_total) * 100
    else:
        delivery_comp = 100

    # volume_consistency: std_dev / mean of daily sends (last 7d). Lower CV→better
    volumes = [r["cnt"] for r in daily_rows]
    if len(volumes) >= 2 and statistics.mean(volumes) > 0:
        cv = statistics.stdev(volumes) / statistics.mean(volumes)
        volume_comp = max(0, 100 - cv * 50)
    else:
        volume_comp = 100

    # recent_failures: fewer is better. 0→100, >=10→0
    failure_comp = max(0, 100 - failed_recent * 10)

    # Weighted composite
    score = (
        bounce_comp * 0.40
        + complaint_comp * 0.30
        + delivery_comp * 0.15
        + volume_comp * 0.10
        + failure_comp * 0.05
    )
    score = max(0, min(100, round(score)))
    state = map_score_to_state(score)
    _update_mailbox_health(mailbox_id, score, state)
    return score


def map_score_to_state(score: int) -> str:
    if score >= 90:
        return "healthy"
    if score >= 75:
        return "normal"
    if score >= 60:
        return "reduced"
    if score >= 40:
        return "restricted"
    return "paused"


# ---------------------------------------------------------------------------
# Persist + event
# ---------------------------------------------------------------------------

def _update_mailbox_health(mailbox_id: str, score: int, state: str) -> None:
    import json
    with db.get_pool().connection() as conn:
        conn.execute(
            """UPDATE mailboxes
               SET health_score=%s, health_state=%s, last_health_check=now(),
                   updated_at=now()
               WHERE id=%s""",
            (score, state, mailbox_id),
        )
        conn.execute(
            """INSERT INTO mailbox_events (mailbox_id, event_type, metrics)
               VALUES (%s, 'health_check', %s)""",
            (mailbox_id, json.dumps({"score": score, "state": state})),
        )


def continuous_hook(event_type: str, mailbox_id: str, metrics: dict) -> None:
    """Call after bounce/complaint/send/failure to recompute score immediately."""
    compute_health_score(mailbox_id)


# ---------------------------------------------------------------------------
# DNS checks
# ---------------------------------------------------------------------------

def _dns_check(domain: str) -> dict:
    """Check SPF, DKIM, DMARC, MX for a domain. Returns {key: {verified, details}}."""
    from dns import resolver, rdatatype

    result = {}
    # MX
    try:
        answers = resolver.resolve(domain, "MX")
        result["mx"] = {"verified": bool(answers), "details": str(answers[0].exchange) if answers else ""}
    except Exception as e:
        result["mx"] = {"verified": False, "details": str(e)}

    # SPF (TXT containing v=spf1)
    try:
        answers = resolver.resolve(domain, "TXT")
        spf = any("v=spf1" in str(r) for r in answers)
        result["spf"] = {"verified": spf, "details": "found" if spf else "missing"}
    except Exception as e:
        result["spf"] = {"verified": False, "details": str(e)}

    # DMARC
    try:
        answers = resolver.resolve(f"_dmarc.{domain}", "TXT")
        dmarc = any("v=DMARC1" in str(r) for r in answers)
        result["dmarc"] = {"verified": dmarc, "details": "found" if dmarc else "missing"}
    except Exception as e:
        result["dmarc"] = {"verified": False, "details": str(e)}

    # DKIM (common selector _default or selector1)
    dkim_verified = False
    for sel in ("_default", "selector1", "google", "s1"):
        try:
            answers = resolver.resolve(f"{sel}._domainkey.{domain}", "TXT")
            if answers:
                dkim_verified = True
                break
        except Exception:
            continue
    result["dkim"] = {"verified": dkim_verified, "details": "found" if dkim_verified else "no common selector"}

    return result


# ---------------------------------------------------------------------------
# Daily audit
# ---------------------------------------------------------------------------

def DAILY_GTM_HEALTH_AUDIT() -> dict:
    """Run health scoring + DNS checks for all active domains/mailboxes.

    Writes mailbox_events, updates mailboxes, aggregates to daily_audits.
    Returns summary dict.
    """
    from datetime import date as date_type
    import json

    today = date_type.today()
    report_sections = {"domains": {}, "mailboxes": {}, "problems": []}
    mailbox_scores = []

    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row

        # Mailboxes
        mailboxes = conn.execute(
            """SELECT m.*, sd.domain, sd.dns_status, sd.daily_cap
               FROM mailboxes m
               LEFT JOIN sending_domains sd ON sd.id = m.domain_id
               WHERE m.status IN ('ready','paused','error')
            """
        ).fetchall()

        for mb in mailboxes:
            mb_id = str(mb["id"])
            score = compute_health_score(mb_id)
            state = map_score_to_state(score)
            mailbox_scores.append({"id": mb_id, "email": mb["email"], "score": score, "state": state})

            domain = mb.get("domain")
            if domain:
                dns = _dns_check(domain)
                conn.execute(
                    """UPDATE sending_domains SET dns_status=%s, updated_at=now()
                       WHERE id=%s""",
                    (json.dumps(dns), str(mb["domain_id"])),
                )
                if not all(v.get("verified") for v in dns.values()):
                    report_sections["problems"].append(
                        {"domain": domain, "dns_issues": [k for k, v in dns.items() if not v["verified"]]}
                    )

            # Auth connectivity check (placeholder for provider-specific check)
            try:
                from app.providers import registry
                provider = registry.get(mb.get("provider", "smtp"))
                # Provider-specific connectivity check would go here
            except Exception:
                pass

            report_sections["mailboxes"][mb_id] = {"email": mb["email"], "score": score, "state": state}

        # Aggregate
        overall = round(statistics.mean([m["score"] for m in mailbox_scores])) if mailbox_scores else 100
        report_md = f"# Daily Health Audit — {today}\n\n"
        report_md += f"Overall score: **{overall}**\n\n"
        report_md += "## Mailboxes\n\n"
        report_md += "| Email | Score | State |\n|---|---|---|\n"
        for m in mailbox_scores:
            report_md += f"| {m['email']} | {m['score']} | {m['state']} |\n"
        if report_sections["problems"]:
            report_md += "\n## Problems\n\n"
            for p in report_sections["problems"]:
                report_md += f"- **{p['domain']}**: {', '.join(p['dns_issues'])}\n"

        conn.execute(
            """INSERT INTO daily_audits (audit_date, overall_score, report, report_md)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (audit_date) DO UPDATE
                   SET overall_score=EXCLUDED.overall_score, report=EXCLUDED.report,
                       report_md=EXCLUDED.report_md""",
            (today, overall, json.dumps(report_sections), report_md),
        )

    return {"overall_score": overall, "mailboxes": mailbox_scores, "problems": report_sections["problems"]}
