"""Follow-up State Machine (spec §52-57) + Reply classification (§20-22).

on_initial_sent: creates followup outbound_messages from sequence_steps.
check_followup_cancellation: cancels pending followups on reply/terminal status.
classify_reply: keyword-based escalation check.
create_human_task: inserts tasks row for human follow-up.
"""

from datetime import datetime, timedelta

import psycopg.rows

import app.db as db


# ---------------------------------------------------------------------------
# Business-day helpers
# ---------------------------------------------------------------------------

def _is_business_day(dt: datetime) -> bool:
    return dt.weekday() < 5


def _next_business_day(dt: datetime) -> datetime:
    nxt = dt + timedelta(days=1)
    while not _is_business_day(nxt):
        nxt += timedelta(days=1)
    return nxt


# ---------------------------------------------------------------------------
# Follow-up creation
# ---------------------------------------------------------------------------

def on_initial_sent(message_id: str, lead_id: str, sequence_id: str) -> int:
    """Create follow-up outbound_messages from sequence_steps WHERE step_no > 0."""
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        steps = conn.execute(
            """SELECT * FROM sequence_steps
               WHERE sequence_id=%s AND step_no > 0
               ORDER BY step_no""",
            (sequence_id,),
        ).fetchall()
        msg = conn.execute(
            "SELECT sent_at FROM outbound_messages WHERE id=%s", (message_id,)
        ).fetchone()

    if not steps or not msg or not msg.get("sent_at"):
        return 0

    sent_at = msg["sent_at"]
    created = 0

    with db.get_pool().connection() as conn:
        for step in steps:
            eligible = sent_at
            remaining = step["offset_days"]
            while remaining > 0:
                eligible = eligible + timedelta(days=1)
                if _is_business_day(eligible):
                    remaining -= 1
            eligible = eligible.replace(hour=8, minute=30, second=0, microsecond=0)
            deadline = eligible + timedelta(days=2)

            conn.execute(
                """INSERT INTO outbound_messages
                   (workspace_id, lead_id, sequence_id, sequence_step_id,
                    kind, priority, eligible_at, deadline, status)
                   VALUES ((SELECT workspace_id FROM outbound_messages WHERE id=%s),
                           %s, %s, %s, 'followup', 2, %s, %s, 'queued')""",
                (message_id, lead_id, sequence_id, str(step["id"]), eligible, deadline),
            )
            created += 1

    return created


# ---------------------------------------------------------------------------
# Follow-up cancellation
# ---------------------------------------------------------------------------

def check_followup_cancellation(lead_id: str) -> bool:
    """Cancel pending followups if lead replied, has terminal status, or is suppressed."""
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row

        reply = conn.execute(
            """SELECT id FROM messages
               WHERE lead_id=%s AND direction='inbound' LIMIT 1""",
            (lead_id,),
        ).fetchone()
        if reply:
            _cancel(conn, lead_id, "lead has reply")
            return True

        lead = conn.execute(
            "SELECT status FROM leads WHERE id=%s", (lead_id,)
        ).fetchone()
        if lead and lead["status"] in (
            "responded", "qualified_conversation", "meeting_booked",
            "won", "do_not_call", "rejected", "unreachable", "archived",
        ):
            _cancel(conn, lead_id, f"terminal status {lead['status']}")
            return True

        contact = conn.execute(
            """SELECT c.email, c.company_id FROM leads l
               JOIN contacts c ON c.id=l.contact_id WHERE l.id=%s""",
            (lead_id,),
        ).fetchone()
        if contact:
            from app.services.suppression import check as supp_check
            ws = conn.execute(
                "SELECT workspace_id FROM leads WHERE id=%s", (lead_id,)
            ).fetchone()
            result = supp_check(
                workspace_id=str(ws["workspace_id"]),
                email=contact.get("email"),
                company_id=str(contact["company_id"]) if contact.get("company_id") else None,
            )
            if result.blocked:
                _cancel(conn, lead_id, f"suppressed: {result.reason}")
                return True

    return False


def _cancel(conn, lead_id: str, reason: str) -> None:
    conn.execute(
        """UPDATE outbound_messages
           SET status='cancelled', error=%s, updated_at=now()
           WHERE lead_id=%s AND kind='followup' AND status IN ('queued','scheduled')""",
        (reason, lead_id),
    )


# ---------------------------------------------------------------------------
# Reply classification
# ---------------------------------------------------------------------------

ESCALATION_KEYWORDS = [
    "legal", "lawyer", "attorney", "cease", "desist", "spam", "report",
    "human", "real person", "speak to someone", "call me", "angry",
    "furious", "unacceptable", "lawsuit", "complaint", "fraud",
]

HUMAN_REQUIRED_CLASSES = {"HUMAN_REQUIRED", "PRICE", "QUESTION"}


def classify_reply(text: str) -> dict:
    """Simple keyword-based escalation check. Returns {classification, needs_human}."""
    lower = text.lower()
    needs_human = any(kw in lower for kw in ESCALATION_KEYWORDS)
    classification = "HUMAN_REQUIRED" if needs_human else "INTERESTED"
    return {"classification": classification, "needs_human": needs_human}


def create_human_task(lead_id: str, classification: str, draft_response: str | None = None) -> dict:
    """Insert a tasks row for human follow-up."""
    task_type = f"handle {classification}: human reply required"
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        row = conn.execute(
            """INSERT INTO tasks (workspace_id, lead_id, type, due_at, created_by)
               VALUES ((SELECT workspace_id FROM leads WHERE id=%s),
                       %s, %s, now(), 'system')
               RETURNING id""",
            (lead_id, lead_id, task_type),
        ).fetchone()
    return {"task_id": str(row["id"]), "classification": classification}
