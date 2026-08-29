"""Central Adaptive Outbound Scheduler (spec §59).

tick() is the main entry point: compute capacity, get eligible messages,
filter by campaign allocation, assign mailboxes with pacing.  Called by
n8n workflow or worker.
"""

import json
import random
from datetime import datetime, timedelta, time as dtime, date as date_type

import psycopg.rows

import app.db as db
from app.services import flags


# ---------------------------------------------------------------------------
# Health multiplier map
# ---------------------------------------------------------------------------

HEALTH_MULTIPLIER = {
    "healthy": 1.0,
    "normal": 0.9,
    "reduced": 0.6,
    "restricted": 0.25,
    "paused": 0.0,
}


# ---------------------------------------------------------------------------
# Kill-switch / shadow helpers
# ---------------------------------------------------------------------------

def _get_kill_switches() -> dict:
    raw = flags.get_flag("kill_switches")
    if raw and isinstance(raw, dict):
        return raw
    return {
        "pause_all_sending": False,
        "pause_followups": False,
        "pause_ai_replies": False,
        "pause_hiring_campaigns": False,
        "pause_domain": {},
        "pause_mailbox": {},
        "pause_campaign": {},
    }


def _is_paused(message: dict, ks: dict) -> bool:
    if ks.get("pause_all_sending"):
        return True
    if ks.get("pause_followups") and message.get("kind") == "followup":
        return True
    mb_id = str(message.get("assigned_mailbox_id") or "")
    if ks.get("pause_mailbox", {}).get(mb_id):
        return True
    camp_id = str(message.get("campaign_id") or "")
    if camp_id and ks.get("pause_campaign", {}).get(camp_id):
        return True
    return False


def _is_shadow_mode() -> bool:
    v = flags.get_flag("shadow_mode")
    return bool(v)


# ---------------------------------------------------------------------------
# Approval mode
# ---------------------------------------------------------------------------

def _get_approval_mode() -> str:
    v = flags.get_flag("approval_mode")
    if isinstance(v, str):
        return v
    return "autonomous"


def _needs_approval(message: dict) -> bool:
    """Hybrid mode: A+ or A leads require approval."""
    mode = _get_approval_mode()
    if mode != "hybrid":
        return False
    # Check lead tier from scores table
    lead_id = message.get("lead_id")
    if not lead_id:
        return False
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        row = conn.execute(
            """SELECT tier FROM scores
               WHERE lead_id=%s ORDER BY computed_at DESC LIMIT 1""",
            (lead_id,),
        ).fetchone()
    tier = (row or {}).get("tier", "")
    return tier in ("A+", "A")


# ---------------------------------------------------------------------------
# Capacity
# ---------------------------------------------------------------------------

def get_daily_capacity() -> dict:
    """For each active mailbox, compute effective_limit per health state.

    Returns {domain: {mailboxes: [...], domain_total, domain_limit}, global_total, global_limit}.
    """
    today = date_type.today()
    now = datetime.utcnow()
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        mailboxes = conn.execute(
            """SELECT m.*, sd.id AS sd_id, sd.daily_cap AS domain_cap
               FROM mailboxes m
               LEFT JOIN sending_domains sd ON sd.id = m.domain_id
               WHERE m.status IN ('ready','paused')
                  OR m.health_state IN ('healthy','normal','reduced','restricted')
            """
        ).fetchall()

    domains: dict[str, dict] = {}
    global_total = 0
    global_limit = 0

    for mb in mailboxes:
        domain_key = str(mb.get("sd_id") or "none")
        health = mb.get("health_state", "healthy")
        multiplier = HEALTH_MULTIPLIER.get(health, 0.0)
        effective = round(mb["daily_send_limit"] * multiplier)

        # Reset sent_today if date changed
        sent = mb["sent_today"] if mb.get("sent_today_date") == today else 0
        remaining = max(0, effective - sent)

        if domain_key not in domains:
            domains[domain_key] = {
                "mailboxes": [],
                "domain_total": 0,
                "domain_limit": mb.get("domain_cap") or 600,
            }
        domains[domain_key]["mailboxes"].append({
            "id": str(mb["id"]),
            "email": mb["email"],
            "effective_limit": effective,
            "sent_today": sent,
            "remaining": remaining,
            "health_state": health,
            "timezone": mb.get("timezone", "America/New_York"),
            "window_start": str(mb.get("window_start") or "08:30"),
            "window_end": str(mb.get("window_end") or "16:30"),
        })
        domains[domain_key]["domain_total"] += sent
        global_total += sent
        global_limit += domains[domain_key]["domain_limit"]

    return {"domains": domains, "global_total": global_total, "global_limit": global_limit}


# ---------------------------------------------------------------------------
# Eligible messages
# ---------------------------------------------------------------------------

def get_eligible_messages() -> list[dict]:
    now = datetime.utcnow()
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        rows = conn.execute(
            """SELECT * FROM outbound_messages
               WHERE status IN ('queued','scheduled')
                 AND eligible_at <= %s
                 AND shadow = false
                 AND (deadline IS NULL OR deadline > %s)
               ORDER BY priority ASC, eligible_at ASC""",
            (now, now),
        ).fetchall()
    return rows


# ---------------------------------------------------------------------------
# Business-day logic
# ---------------------------------------------------------------------------

def _is_business_day(dt: datetime) -> bool:
    return dt.weekday() < 5


def _next_business_day(dt: datetime) -> datetime:
    nxt = dt + timedelta(days=1)
    while not _is_business_day(nxt):
        nxt += timedelta(days=1)
    return nxt


# ---------------------------------------------------------------------------
# Slot generation
# ---------------------------------------------------------------------------

def _parse_time(val) -> tuple[int, int]:
    """Parse a time value (str like '08:30'/'08:30:00' or datetime.time) → (hour, minute)."""
    if isinstance(val, str):
        parts = val.split(":")
        return int(parts[0]), int(parts[1])
    return val.hour, val.minute


def next_available_slot(mailbox: dict, now: datetime) -> datetime:
    """Pick next available sending slot respecting business hours + pacing."""
    sh, sm = _parse_time(mailbox.get("window_start", "08:30"))
    eh, em = _parse_time(mailbox.get("window_end", "16:30"))
    tz_name = mailbox.get("timezone", "America/New_York")
    window_start_t = dtime(sh, sm)
    window_end_t = dtime(eh, em)

    min_gap = timedelta(minutes=5)
    max_jitter = timedelta(minutes=45)

    # Start from now, find the next business day
    candidate = now
    if not _is_business_day(candidate):
        candidate = _next_business_day(candidate).replace(hour=sh, minute=sm, second=0, microsecond=0)

    # Try today's remaining slots
    day_start = candidate.replace(hour=sh, minute=sm, second=0, microsecond=0)
    day_end = candidate.replace(hour=eh, minute=em, second=0, microsecond=0)

    slot_time = max(candidate, day_start) + min_gap + timedelta(minutes=random.randint(0, int(max_jitter.total_seconds() // 60)))

    if slot_time < day_end:
        return slot_time

    # No slot today → first slot tomorrow (next business day)
    next_day = _next_business_day(candidate)
    return next_day.replace(hour=sh, minute=sm, second=0, microsecond=0)


# ---------------------------------------------------------------------------
# Campaign allocation filter
# ---------------------------------------------------------------------------

def campaign_allocation_filter(messages: list[dict]) -> tuple[list[dict], list[dict]]:
    """Partition messages by kind.  Enforce allocation caps from system_flags.

    Returns (allowed, deferred).
    """
    raw = flags.get_flag("campaign_allocation")
    cfg = {
        "new_prospects_pct": 40,
        "followups_pct": 30,
        "hiring_pct": 30,
        "min_new": 50,
        "max_followup": 30,
    }
    if raw and isinstance(raw, dict):
        cfg.update(raw)

    total = len(messages)
    if total == 0:
        return [], []

    initial_cap = max(cfg["min_new"], round(total * cfg["new_prospects_pct"] / 100))
    followup_cap = max(1, round(total * cfg["followups_pct"] / 100))

    # Separate by kind
    initials = [m for m in messages if m.get("kind") == "initial"]
    followups = [m for m in messages if m.get("kind") == "followup"]
    other = [m for m in messages if m.get("kind") not in ("initial", "followup")]

    allowed_initial = initials[:initial_cap]
    allowed_followup = followups[:followup_cap]
    deferred_initial = initials[initial_cap:]
    deferred_followup = followups[followup_cap:]

    return allowed_initial + allowed_followup + other, deferred_initial + deferred_followup


# ---------------------------------------------------------------------------
# Assign mailboxes
# ---------------------------------------------------------------------------

def assign_mailboxes(messages: list[dict], capacity: dict) -> tuple[list[dict], list[dict]]:
    """Assign each message to the best mailbox. Returns (assigned, deferred)."""
    ks = _get_kill_switches()
    shadow = _is_shadow_mode()
    assigned = []
    deferred = []
    now = datetime.utcnow()

    # Build mailbox lookup with remaining capacity
    mb_remaining: dict[str, int] = {}
    mb_info: dict[str, dict] = {}
    for domain_key, dom in capacity.get("domains", {}).items():
        for mb in dom["mailboxes"]:
            mb_id = mb["id"]
            mb_remaining[mb_id] = mb["remaining"]
            mb_info[mb_id] = {**mb, "domain_key": domain_key}

    # Track domain remaining
    domain_remaining: dict[str, int] = {}
    for dk, dom in capacity.get("domains", {}).items():
        domain_remaining[dk] = max(0, dom["domain_limit"] - dom["domain_total"])

    for msg in messages:
        if _is_paused(msg, ks):
            msg["status"] = "deferred"
            deferred.append(msg)
            continue

        msg_id = str(msg["id"])

        # Find best mailbox
        best_mb = None
        best_ratio = 2.0

        for mb_id, remaining in mb_remaining.items():
            if remaining <= 0:
                continue
            mb = mb_info[mb_id]
            if mb["health_state"] == "paused":
                continue
            dk = mb["domain_key"]
            if domain_remaining.get(dk, 0) <= 0:
                continue

            # Prefer lowest sent_today / effective_limit ratio
            eff = mb.get("effective_limit", 1) or 1
            ratio = (mb.get("sent_today", 0) or 0) / eff
            if ratio < best_ratio:
                best_ratio = ratio
                best_mb = mb_id

        if best_mb is None:
            msg["status"] = "deferred"
            deferred.append(msg)
            continue

        # Check mailbox-specific kill switch after selection
        if ks.get("pause_mailbox", {}).get(best_mb):
            msg["status"] = "deferred"
            deferred.append(msg)
            continue

        # Check domain-specific kill switch
        domain_of_mb = mb_info[best_mb].get("domain_key")
        if ks.get("pause_domain", {}).get(domain_of_mb):
            msg["status"] = "deferred"
            deferred.append(msg)
            continue

        slot = next_available_slot(mb_info[best_mb], now)

        if shadow:
            with db.get_pool().connection() as conn:
                conn.execute(
                    """UPDATE outbound_messages
                       SET status='claimed', assigned_mailbox_id=%s,
                           shadow=true, updated_at=now()
                       WHERE id=%s""",
                    (best_mb, msg_id),
                )
        elif _needs_approval(msg):
            with db.get_pool().connection() as conn:
                conn.execute(
                    """UPDATE outbound_messages
                       SET status='pending_approval', assigned_mailbox_id=%s,
                           scheduled_slot_at=%s, updated_at=now()
                       WHERE id=%s""",
                    (best_mb, slot, msg_id),
                )
        else:
            with db.get_pool().connection() as conn:
                conn.execute(
                    """UPDATE outbound_messages
                       SET status='scheduled', assigned_mailbox_id=%s,
                           scheduled_slot_at=%s, updated_at=now()
                       WHERE id=%s""",
                    (best_mb, slot, msg_id),
                )

            # Update capacity counters
            mb_remaining[best_mb] = max(0, mb_remaining[best_mb] - 1)
            dk = mb_info[best_mb]["domain_key"]
            domain_remaining[dk] = max(0, domain_remaining[dk] - 1)

        msg["assigned_mailbox_id"] = best_mb
        msg["scheduled_slot_at"] = slot
        msg["status"] = "shadow_queued" if shadow else ("pending_approval" if _needs_approval(msg) else "scheduled")
        assigned.append(msg)

    return assigned, deferred


# ---------------------------------------------------------------------------
# tick() — main entry
# ---------------------------------------------------------------------------

def tick() -> dict:
    """Main scheduler tick: capacity → eligible → allocation filter → assign."""
    capacity = get_daily_capacity()
    eligible = get_eligible_messages()
    allowed, deferred_alloc = campaign_allocation_filter(eligible)
    assigned, deferred_assign = assign_mailboxes(allowed, capacity)

    return {
        "assigned": len(assigned),
        "deferred": len(deferred_alloc) + len(deferred_assign),
        "capacity_remaining": {
            dk: {
                "remaining": domain_remaining_value(dk, capacity),
            }
            for dk in capacity.get("domains", {})
        },
        "total_eligible": len(eligible),
    }


def domain_remaining_value(dk: str, capacity: dict) -> int:
    dom = capacity.get("domains", {}).get(dk, {})
    return max(0, dom.get("domain_limit", 0) - dom.get("domain_total", 0))


# Re-export from sequences for convenience
from app.services.sequences import (  # noqa: E402, F401
    on_initial_sent,
    check_followup_cancellation,
    classify_reply,
    create_human_task,
)
