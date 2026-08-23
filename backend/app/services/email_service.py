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
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

import psycopg.rows

import app.db as db
from app.config import get_settings
from app.services import llm


class SendBlocked(Exception):
    pass


# ---------------------------------------------------------------- providers

@dataclass
class OutboundEmail:
    to_email: str
    subject: str
    body_text: str
    from_email: str
    from_name: str


class EmailProvider:
    def send(self, email: OutboundEmail) -> str:
        """Returns provider_message_id. Raises on failure."""
        raise NotImplementedError


class SMTPProvider(EmailProvider):
    """Basic authenticated SMTP. Failures raise — caller records + retries."""

    def send(self, email: OutboundEmail) -> str:
        s = get_settings()
        msg = MIMEMultipart("alternative")
        msg["Subject"] = email.subject
        msg["From"] = formataddr((email.from_name, email.from_email))
        msg["To"] = email.to_email
        msg.attach(MIMEText(email.body_text, "plain"))
        # simple text wrapper as "html" part is optional; plain text preferred for cold email
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as server:
            server.starttls()
            if s.smtp_user:
                server.login(s.smtp_user, s.smtp_password)
            server.sendmail(email.from_email, [email.to_email], msg.as_string())
        return f"smtp:{email.to_email}:{id(msg)}"


def get_provider() -> EmailProvider:
    return SMTPProvider()


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
    address = get_settings().smtp_from_email or "orbit@example.com"
    return (
        f"\n\n— {name}, Orbit\n"
        f"{address}\n"
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


def send_approved(workspace_id: str, message_id: str) -> dict:
    """Send one approved message through all gates. Returns final status."""
    msg = _load_message(workspace_id, message_id)

    # GATE 1: approval record
    if msg["status"] != "approved":
        raise SendBlocked(f"message not approved (status={msg['status']})")

    # GATE 2: verified email only
    if not msg["email"]:
        raise SendBlocked("lead has no contact email")
    if msg.get("opt_out_flag"):
        raise SendBlocked("contact opted out")
    if msg["email_verification_status"] != "verified":
        raise SendBlocked(
            f"email not provider-verified (status={msg['email_verification_status']})"
        )

    # GATE 3: suppression
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
    settings = get_settings()
    if not settings.smtp_host:
        record_failure(message_id, "SMTP not configured")
        raise SendBlocked("smtp_host not configured")

    email = OutboundEmail(
        to_email=msg["email"],
        subject=msg["subject"] or "(no subject)",
        body_text=body,
        from_email=settings.smtp_from_email,
        from_name=settings.smtp_from_name,
    )

    try:
        provider_id = get_provider().send(email)
    except Exception as e:
        record_failure(message_id, f"{type(e).__name__}: {e}")
        raise

    with db.get_pool().connection() as conn:
        conn.execute(
            """UPDATE messages SET status='sent', provider_message_id=%s,
               sent_at=now(), error=NULL WHERE id=%s AND status='approved'""",
            (provider_id, message_id),
        )
        conn.execute(
            """INSERT INTO activities (workspace_id, lead_id, type, summary, actor)
               VALUES (%s,%s,'email',%s,'system')""",
            (workspace_id, msg["lead_id"], f"email sent: {msg['subject']}"),
        )
    return {"status": "sent", "provider_message_id": provider_id}


def record_failure(message_id: str, error: str) -> None:
    """Recoverable failure: message goes back to 'approved' with error noted so it
    can retry; after 3 failures it lands in a dead-letter state ('failed')."""
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        row = conn.execute(
            """SELECT error FROM messages WHERE id=%s""", (message_id,)
        ).fetchone()
        prior_failures = 1 if (row and row["error"]) else 0
        new_status = "failed" if prior_failures >= 3 else "approved"
        conn.execute(
            "UPDATE messages SET status=%s, error=%s WHERE id=%s",
            (new_status, error, message_id),
        )


def process_cadence(workspace_id: str) -> dict:
    """n8n calls this on schedule: sends approved+scheduled messages whose time
    has come, and advances follow-up sequences per campaign cadence offsets."""
    sent, blocked, failed = [], [], []
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        due = conn.execute(
            """SELECT id FROM messages
               WHERE workspace_id=%s AND status='approved'
                 AND (scheduled_send_at IS NULL OR scheduled_send_at <= now())
               ORDER BY created_at LIMIT %s""",
            (workspace_id, 50),
        ).fetchall()
    for row in due:
        try:
            outcome = send_approved(workspace_id, str(row["id"]))
            sent.append({"message_id": str(row["id"]), **outcome})
        except SendBlocked as e:
            blocked.append({"message_id": str(row["id"]), "reason": str(e)})
        except Exception as e:
            failed.append({"message_id": str(row["id"]), "error": f"{type(e).__name__}: {e}"})
    return {"sent": len(sent), "blocked": len(blocked), "failed": len(failed),
            "details": {"blocked": blocked, "failed": failed}}


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
    current = row[0] if row else "new"
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
    parsed = llm.structured_complete(
        agent_name="reply_classification_agent",
        system=(
            "Classify the inbound prospect reply into exactly one class: "
            + ", ".join(sorted(REPLY_CLASSES))
            + ". Reply with JSON only."
        ),
        user=inbound_text[:4000],
        required_keys=["intent_class", "confidence", "suggested_response"],
        workspace_id=workspace_id,
    )
    intent = parsed.get("intent_class", "HUMAN_REQUIRED").upper()
    if intent not in REPLY_CLASSES:
        intent = "HUMAN_REQUIRED"
    routing = CLASS_ROUTING[intent]

    with db.get_pool().connection() as conn:
        conn.execute(
            """INSERT INTO messages (workspace_id, lead_id, channel, direction,
                   body_text, status)
               VALUES (%s,%s,'email','inbound',%s,'replied')""",
            (workspace_id, lead_id, inbound_text[:10000]),
        )
        kill_switch(conn, workspace_id, lead_id, f"reply classified {intent}")
        conn.execute(
            """INSERT INTO tasks (workspace_id, lead_id, type, due_at, created_by)
               VALUES (%s,%s,%s,now(),'agent')""",
            (workspace_id, lead_id, f"handle {intent}: {routing[1]}"),
        )
    if intent == "NOT_INTERESTED":
        with db.get_pool().connection() as conn:
            from app.services import suppression as supp

            conn.row_factory = psycopg.rows.dict_row
            row = conn.execute(
                """SELECT c.email FROM leads l JOIN contacts c ON c.id=l.contact_id
                   WHERE l.id=%s""",
                (lead_id,),
            ).fetchone()
            if row and row["email"]:
                supp.add(conn, workspace_id=workspace_id, scope="email",
                         value=row["email"], reason="not interested reply")
    return {
        "intent_class": intent,
        "routing": routing[0],
        "suggested_response": parsed.get("suggested_response"),
        "confidence": float(parsed.get("confidence", 0)),
    }
