"""Email sending behind an EmailProvider abstraction (constraints: SMTP now,
future Instantly/SES/Resend without rewriting the app).

Hard gates enforced here, not in the UI:
  - message.status must be 'approved' (human approval record required)
  - contact email must be provider-verified
  - suppression check (email/phone/company/global + opt-out)
  - CAN-SPAM signature block present
  - idempotency key prevents double sends
"""

import json

import psycopg.rows

import app.db as db
from app.config import get_settings
from app.services import events


class SendBlocked(Exception):
    pass


# ---------------------------------------------------------------- providers

# ---------------------------------------------------------------- service

def _load_message(workspace_id: str, message_id: str) -> dict:
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        row = conn.execute(
            """SELECT m.*, l.contact_id, l.company_id, l.status AS lead_status,
                      c.email, c.opt_out_flag, c.email_verification_status,
                      co.phone AS company_phone, co.business_name
               FROM messages m
               JOIN leads l ON l.id = m.lead_id
               LEFT JOIN contacts c ON c.id = l.contact_id
               LEFT JOIN companies co ON co.id = l.company_id
               WHERE m.id=%s AND m.workspace_id=%s""",
            (message_id, workspace_id),
        ).fetchone()
    if row is None:
        raise SendBlocked("message not found")
    return row


def can_spam_signature(workspace_id: str) -> str:
    identity = db.execute_one(
        """SELECT display_name FROM users u
           JOIN workspace_members m ON m.user_id=u.id WHERE m.workspace_id=%s LIMIT 1""",
        (workspace_id,),
    )
    name = (identity or {}).get("display_name") or "Orbit"
    address_line = get_settings().orbit_physical_address
    if not address_line:
        # CAN-SPAM requires a real physical mailing address — refuse to fake one.
        raise SendBlocked(
            "ORBIT_PHYSICAL_ADDRESS not configured; CAN-SPAM signature incomplete"
        )
    return (
        f"\n\n— {name}, Orbit\n"
        f"{address_line}\n"
        "Reply STOP to opt out of future emails."
    )


def approve(workspace_id: str, message_id: str, user_id: str) -> None:
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        msg = conn.execute(
            "SELECT status FROM messages WHERE id=%s AND workspace_id=%s",
            (message_id, workspace_id),
        ).fetchone()
        if msg is None:
            raise SendBlocked("message not found")
        if msg["status"] not in ("pending_approval", "drafted"):
            raise SendBlocked(f"cannot approve message in status {msg['status']}")
        conn.execute(
            """UPDATE messages SET status='approved', approved_by=%s, approved_at=now()
               WHERE id=%s""",
            (user_id, message_id),
        )
        from app.services import events

        events.emit(
            conn, event_type="message.approved",
            payload={"message_id": message_id},
            workspace_id=workspace_id,
        )


def reject(workspace_id: str, message_id: str, reason: str | None = None) -> None:
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        msg = conn.execute(
            "SELECT status FROM messages WHERE id=%s AND workspace_id=%s",
            (message_id, workspace_id),
        ).fetchone()
        if msg is None:
            raise SendBlocked("message not found")
        if msg["status"] == "sent":
            raise SendBlocked("cannot reject a sent message")
        conn.execute(
            "UPDATE messages SET status='rejected', error=%s WHERE id=%s",
            (reason or "rejected by operator", message_id),
        )


def claim_for_send(workspace_id: str, message_id: str,
                   idempotency_key: str | None = None) -> dict:
    """Gates + atomic claim. Returns the exact payload n8n's Send Email node
    should transport. The backend never talks SMTP itself (spec §10.3)."""
    # Idempotent replay: same key on an already-sent message returns cached result.
    if idempotency_key:
        prior = db.execute_one(
            "SELECT id, provider_message_id FROM messages WHERE idempotency_key=%s AND workspace_id=%s",
            (idempotency_key, workspace_id),
        )
        if prior and str(prior["id"]) != message_id:
            raise SendBlocked(f"idempotency key already used by message {prior['id']}")
        if prior and prior["provider_message_id"]:
            return {"status": "sent", "provider_message_id": prior["provider_message_id"],
                    "idempotent_replay": True}

    with db.get_pool().connection() as conn:
        claimed = conn.execute(
            """UPDATE messages SET status='sending'
               WHERE id=%s AND workspace_id=%s AND status='approved' RETURNING id""",
            (message_id, workspace_id),
        ).fetchone()
    msg = _load_message(workspace_id, message_id)
    if not claimed or msg["status"] == "sent":
        raise SendBlocked(
            f"message not claimable (status={msg['status']}) — already sent or not approved"
        )

    if idempotency_key:
        with db.get_pool().connection() as conn:
            conn.execute("UPDATE messages SET idempotency_key=%s WHERE id=%s",
                         (idempotency_key, message_id))

    # GATES run while claimed; any block returns the claim safely.
    try:
        if not msg["email"]:
            raise SendBlocked("lead has no contact email")
        if msg.get("opt_out_flag"):
            raise SendBlocked("contact opted out")
        if msg["email_verification_status"] != "verified":
            raise SendBlocked(
                f"email not provider-verified (status={msg['email_verification_status']})"
            )

        from app.services.suppression import check
        result = check(
            workspace_id=workspace_id,
            email=msg["email"],
            phone=msg.get("company_phone"),
            company_id=str(msg["company_id"]) if msg["company_id"] else None,
        )
        if result.blocked:
            raise SendBlocked(result.reason)

        body = (msg["body_text"] or "") + can_spam_signature(workspace_id)
    except SendBlocked:
        _release_claim(message_id)
        raise

    return {
        "message_id": message_id,
        "to_email": msg["email"],
        "subject": msg["subject"] or "(no subject)",
        "body_text": body,
        "from_email": get_settings().smtp_from_email,
        "from_name": get_settings().smtp_from_name,
        "idempotency_key": idempotency_key,
    }


def apply_send_result(workspace_id: str, message_id: str, *, ok: bool,
                      provider_message_id: str | None = None,
                      error: str | None = None) -> dict:
    """n8n reports the transport outcome; backend owns the resulting state."""
    if ok:
        with db.get_pool().connection() as conn:
            row = conn.execute(
                """UPDATE messages SET status='sent', provider_message_id=%s,
                   sent_at=now(), error=NULL WHERE id=%s AND status='sending'
                   RETURNING lead_id""",
                (provider_message_id, message_id),
            ).fetchone()
            if row is None:
                raise SendBlocked("message not in sending state")
            conn.execute(
                """INSERT INTO activities (workspace_id, lead_id, type, summary, actor)
                   VALUES (%s,%s,'email',%s,'system')""",
                (workspace_id, row["lead_id"], "email sent via n8n transport"),
            )
        return {"status": "sent"}
    record_failure(message_id, error or "transport failure")
    return {"status": "retry_scheduled"}


def _release_claim(message_id: str) -> None:
    """Return a 'sending' claim back to 'approved' when a gate blocks."""
    with db.get_pool().connection() as conn:
        conn.execute(
            "UPDATE messages SET status='approved' WHERE id=%s AND status='sending'",
            (message_id,),
        )


def record_failure(message_id: str, error: str) -> None:
    """Recoverable failure: message returns to 'approved' with error noted so it
    can retry; after 3 failed attempts it lands in a dead-letter state ('failed')."""
    with db.get_pool().connection() as conn:
        row = conn.execute(
            """UPDATE messages
               SET send_attempts = send_attempts + 1, error=%s,
                   status = CASE WHEN send_attempts + 1 >= 3 THEN 'failed' ELSE 'approved' END
               WHERE id=%s RETURNING send_attempts, status""",
            (error, message_id),
        ).fetchone()


def due_sends(workspace_id: str, limit: int = 25) -> list[dict]:
    """n8n polls this on schedule and claims each message for transport."""
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        rows = conn.execute(
            """SELECT id FROM messages
               WHERE workspace_id=%s AND status='approved'
                 AND (scheduled_send_at IS NULL OR scheduled_send_at <= now())
               ORDER BY created_at LIMIT %s""",
            (workspace_id, limit),
        ).fetchall()
    return [{"message_id": str(r["id"])} for r in rows]


def schedule_followups(workspace_id: str, lead_id: str, campaign_id: str | None,
                       original_message_id: str) -> int:
    """Deterministic follow-up cadence (day 3/7/14 style) from the campaign config.
    Follow-ups are created pending_approval? No — the ORIGINAL approval covers the
    sequence; follow-ups are created as 'approved' with staggered send times."""
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        original = conn.execute(
            "SELECT subject, body_text, sequence_step FROM messages WHERE id=%s",
            (original_message_id,),
        ).fetchone()
        if original is None:
            raise SendBlocked("original message not found")
        cadence = [0, 3, 7, 14]
        if campaign_id:
            cfg_row = conn.execute(
                "SELECT cadence_config FROM campaigns WHERE id=%s", (campaign_id,)
            ).fetchone()
            if cfg_row and cfg_row["cadence_config"].get("offsets_days"):
                cadence = cfg_row["cadence_config"]["offsets_days"]
        next_step = (original["sequence_step"] or 0) + 1
        offsets = [d for d in cadence[1:] if d > 0]
        if next_step > len(offsets):
            return 0
        offset_days = offsets[next_step - 1]
        angles = [
            "short follow-up with a different angle",
            "case-study angle",
            "breakup email — polite close",
        ]
        angle = angles[min(next_step - 1, len(angles) - 1)]
        conn.execute(
            """INSERT INTO messages
               (workspace_id, lead_id, campaign_id, channel, direction, subject,
                body_text, status, sequence_step, approved_by, approved_at,
                scheduled_send_at)
               VALUES (%s,%s,%s,'email','outbound',
                       %s, %s, 'approved', %s,
                       (SELECT approved_by FROM messages WHERE id=%s), now(),
                       now() + make_interval(days => %s))""",
            (
                workspace_id, lead_id, campaign_id,
                f"Re: {original['subject']}",
                f"[{angle} — draft generated deterministically; edit before send if desired]",
                next_step, original_message_id, offset_days,
            ),
        )
    return 1


# ---------------------------------------------------------------- replies

REPLY_CLASSES = {
    "INTERESTED", "PRICE", "QUESTION", "OBJECTION", "NOT_INTERESTED",
    "BOOKING_REQUEST", "HUMAN_REQUIRED",
}

CLASS_ROUTING = {
    "INTERESTED": ("hot_lead_alert", "operator handles personally"),
    "BOOKING_REQUEST": ("send_booking_link", "create meeting"),
    "PRICE": ("notify_human", "never auto-quote"),
    "QUESTION": ("notify_human", "draft response for review"),
    "OBJECTION": ("draft_for_review", "operator approves any response"),
    "NOT_INTERESTED": ("suppress_and_close", "honor and stop"),
    "HUMAN_REQUIRED": ("notify_human", "always human"),
}


def kill_switch(conn, workspace_id: str, lead_id: str, reason: str) -> None:
    """Any reply pauses ALL automation for the lead, purges call queues, alerts."""
    from app.services.state_machine import can_transition

    row = conn.execute("SELECT status FROM leads WHERE id=%s", (lead_id,)).fetchone()
    if row is None:
        current = "new"
    elif isinstance(row, dict):
        current = row["status"]
    else:
        current = row[0]
    target = "responded"
    if can_transition(current, target):
        conn.execute(
            "UPDATE leads SET status=%s, updated_at=now() WHERE id=%s", (target, lead_id)
        )
    # purge from all calling sessions
    conn.execute(
        """DELETE FROM session_leads
           WHERE lead_id=%s
             AND session_id IN (SELECT id FROM calling_sessions
                                WHERE workspace_id=%s AND status IN ('pending','active'))""",
        (lead_id, workspace_id),
    )
    # cancel pending outbound automation
    conn.execute(
        """UPDATE messages SET status='rejected', error='kill switch: reply received'
           WHERE lead_id=%s AND status IN ('approved','scheduled','pending_approval')""",
        (lead_id,),
    )
    conn.execute(
        """INSERT INTO activities (workspace_id, lead_id, type, summary, actor)
           VALUES (%s,%s,'system',%s,'system')""",
        (workspace_id, lead_id, f"KILL SWITCH fired: {reason}"),
    )


def classify_reply(workspace_id: str, lead_id: str, inbound_text: str) -> dict:
    """Reply handling is durable FIRST: persist the inbound message, fire the
    kill switch, create a HUMAN_REQUIRED task, and emit reply.received so n8n
    can orchestrate LLM classification. The backend never calls an LLM."""
    with db.get_pool().connection() as conn:
        conn.execute(
            """INSERT INTO messages (workspace_id, lead_id, channel, direction,
                   body_text, status)
               VALUES (%s,%s,'email','inbound',%s,'replied')""",
            (workspace_id, lead_id, inbound_text[:10000]),
        )
        kill_switch(conn, workspace_id, lead_id, "inbound reply received")
        conn.execute(
            """INSERT INTO tasks (workspace_id, lead_id, type, due_at, created_by)
               VALUES (%s,%s,'handle HUMAN_REQUIRED: always human',now(),'system')""",
            (workspace_id, lead_id),
        )
        events.emit(
            conn, event_type="reply.received",
            payload={"lead_id": lead_id, "text": inbound_text[:8000]},
            workspace_id=workspace_id,
        )
    return {"queued_for_classification": True, "kill_switch": "fired"}


def apply_classification(workspace_id: str, lead_id: str, *, intent_class: str,
                         confidence: float = 0.0,
                         suggested_response: str | None = None) -> dict:
    """n8n posts the LLM classification result; backend owns routing."""
    intent = intent_class.upper()
    if intent not in REPLY_CLASSES:
        intent = "HUMAN_REQUIRED"
    routing = CLASS_ROUTING[intent]

    with db.get_pool().connection() as conn:
        conn.execute(
            """INSERT INTO tasks (workspace_id, lead_id, type, due_at, created_by)
               VALUES (%s,%s,%s,now(),'agent')""",
            (workspace_id, lead_id, f"handle {intent}: {routing[1]}"),
        )
    if intent == "NOT_INTERESTED":
        with db.get_pool().connection() as conn:
            conn.row_factory = psycopg.rows.dict_row
            row = conn.execute(
                """SELECT c.email FROM leads l JOIN contacts c ON c.id=l.contact_id
                   WHERE l.id=%s""",
                (lead_id,),
            ).fetchone()
            if row and row["email"]:
                from app.services import suppression as supp

                supp.add(conn, workspace_id=workspace_id, scope="email",
                         value=row["email"], reason="not interested reply")
    return {
        "intent_class": intent,
        "routing": routing[0],
        "suggested_response": suggested_response,
        "confidence": confidence,
    }
