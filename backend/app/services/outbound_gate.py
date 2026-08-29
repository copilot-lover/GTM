"""Structural outbound send gate — evaluates every eligibility check for a
message and returns an auditable decision. Enforced in code (claim_for_send
calls this first); the UI never decides sendability.

Legacy rows (messages.gtm_stage IS NULL) skip only the QA / compliance /
stage checks so pre-existing flows are unchanged. Managed rows must be at
an authorized send stage.
"""

from datetime import date

import psycopg.rows

import app.db as db


def _add(checks: list[dict], name: str, passed: bool, detail: str) -> None:
    checks.append({"name": name, "passed": passed, "detail": detail})


def _load_message(workspace_id: str, message_id: str) -> dict | None:
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        return conn.execute(
            """SELECT m.id, m.gtm_stage, m.sequence_step, m.campaign_id,
                      m.originating_mailbox_id, m.thread_id, m.lead_id,
                      l.status AS lead_status, l.company_id,
                      c.email, c.opt_out_flag, c.email_verification_status,
                      co.phone AS company_phone,
                      cam.status AS campaign_status
               FROM messages m
               JOIN leads l ON l.id = m.lead_id
               LEFT JOIN contacts c ON c.id = l.contact_id
               LEFT JOIN companies co ON co.id = l.company_id
               LEFT JOIN campaigns cam ON cam.id = m.campaign_id
               WHERE m.id=%s AND m.workspace_id=%s""",
            (message_id, workspace_id),
        ).fetchone()


def _load_mailbox(mailbox_id: str) -> dict | None:
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        return conn.execute(
            """SELECT mb.email, mb.status, mb.health_state,
                      mb.daily_send_limit, mb.sent_today, mb.sent_today_date,
                      mb.provider,
                      sd.id AS sd_id, sd.status AS domain_status, sd.domain
               FROM mailboxes mb
               LEFT JOIN sending_domains sd ON sd.id = mb.domain_id
               WHERE mb.id=%s""",
            (mailbox_id,),
        ).fetchone()


def _latest_qa(workspace_id: str, object_type: str, object_id: str) -> dict | None:
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        return conn.execute(
            """SELECT status, score, findings, failed_rules, attempt, created_at
               FROM qa_runs
               WHERE workspace_id=%s AND object_type=%s AND object_id=%s
               ORDER BY created_at DESC LIMIT 1""",
            (workspace_id, object_type, object_id),
        ).fetchone()


def _original_mailbox(lead_id: str, sequence_step: int) -> str | None:
    """Mailbox record of the earlier sequence step's message on this lead."""
    with db.get_pool().connection() as conn:
        row = conn.execute(
            """SELECT originating_mailbox_id FROM messages
               WHERE lead_id=%s AND direction='outbound' AND sequence_step < %s
               ORDER BY sequence_step DESC, created_at DESC LIMIT 1""",
            (lead_id, sequence_step),
        ).fetchone()
    return row["originating_mailbox_id"] if row else None


def _lead_replied_after_last_outbound(lead_id: str) -> bool:
    with db.get_pool().connection() as conn:
        row = conn.execute(
            """SELECT EXISTS(
                   SELECT 1 FROM messages inbound
                   WHERE inbound.lead_id=%s AND inbound.direction='inbound'
                     AND inbound.created_at > COALESCE(
                         (SELECT MAX(outbound.sent_at) FROM messages outbound
                          WHERE outbound.lead_id=%s AND outbound.direction='outbound'
                            AND outbound.sent_at IS NOT NULL),
                         to_timestamp(0))) AS replied""",
            (lead_id, lead_id),
        ).fetchone()
    return bool(row["replied"])


def can_send(workspace_id: str, message_id: str) -> dict:
    msg = _load_message(workspace_id, message_id)
    if msg is None:
        return {"allowed": False, "reasons": ["message not found"], "checks": []}

    checks: list[dict] = []
    legacy = msg["gtm_stage"] is None

    # ---------------------------------------------------------- lead + contact
    bad_lead_statuses = ("rejected", "do_not_call", "archived", "lost")
    _add(checks, "lead_eligible",
         msg["lead_status"] not in bad_lead_statuses,
         f"lead status {msg['lead_status']!r}"
         if msg["lead_status"] in bad_lead_statuses
         else f"lead status {msg['lead_status']!r}")

    contact_ok = bool(msg["email"]) and not msg.get("opt_out_flag")
    detail = "contact email present, not opted out"
    if not msg["email"]:
        detail = "contact has no email"
    elif msg.get("opt_out_flag"):
        detail = "contact opted out"
    _add(checks, "contact_eligible", contact_ok, detail)

    from app.services.suppression import check as suppression_check
    supp = suppression_check(
        workspace_id=workspace_id,
        email=msg["email"],
        phone=msg.get("company_phone"),
        company_id=str(msg["company_id"]) if msg["company_id"] else None,
    )
    _add(checks, "not_suppressed", not supp.blocked,
         supp.reason or "no suppression match")

    verified = msg["email_verification_status"] == "verified"
    _add(checks, "email_verified", verified,
         f"email not provider-verified (status={msg['email_verification_status']!r})"
         if not verified
         else f"email verification status {msg['email_verification_status']!r}")

    # ------------------------------------------------------- QA + stage gates
    if legacy:
        legacy_detail = "legacy unmanaged message"
        _add(checks, "copy_qa_passed", True, legacy_detail)
        _add(checks, "compliance_passed", True, legacy_detail)
    else:
        from app.services import gtm_lifecycle  # lazy: avoid import cycles

        copy_qa = _latest_qa(workspace_id, "copy", str(msg["id"]))
        _add(checks, "copy_qa_passed",
             bool(copy_qa) and copy_qa["status"] == "passed",
             "no copy qa_runs row" if copy_qa is None
             else f"latest copy qa run {copy_qa['status']}")
        comp_qa = _latest_qa(workspace_id, "compliance", str(msg["id"]))
        _add(checks, "compliance_passed",
             bool(comp_qa) and comp_qa["status"] == "passed",
             "no compliance qa_runs row" if comp_qa is None
             else f"latest compliance qa run {comp_qa['status']}")
        authorized = msg["gtm_stage"] in gtm_lifecycle.AUTHORIZED_SEND_STAGES
        _add(checks, "stage_authorized", authorized,
             f"gtm_stage {msg['gtm_stage']!r} not in "
             f"{gtm_lifecycle.AUTHORIZED_SEND_STAGES}"
             if not authorized else f"gtm_stage {msg['gtm_stage']!r} authorized")

    # ---------------------------------------------------------------- mailbox
    mailbox = None
    provider = None
    if msg["originating_mailbox_id"]:
        mailbox = _load_mailbox(str(msg["originating_mailbox_id"]))
        if mailbox is None:
            _add(checks, "mailbox_healthy", False,
                 "bound mailbox record not found")
            _add(checks, "domain_healthy", False,
                 "bound mailbox has no resolvable domain")
            _add(checks, "within_sending_limits", False,
                 "bound mailbox record not found")
            provider = None
        else:
            healthy = mailbox["health_state"] != "paused"
            _add(checks, "mailbox_healthy", healthy,
                 f"mailbox {mailbox['email']} health_state="
                 f"{mailbox['health_state']!r}")
            if mailbox["sd_id"]:
                domain_ok = mailbox["domain_status"] == "active"
                _add(checks, "domain_healthy", domain_ok,
                     f"sending domain {mailbox['domain']} status="
                     f"{mailbox['domain_status']!r}")
            else:
                _add(checks, "domain_healthy", False,
                     "mailbox has no sending domain bound")
            sent_today = (mailbox["sent_today"]
                          if mailbox["sent_today_date"] == date.today() else 0)
            within = sent_today < mailbox["daily_send_limit"]
            _add(checks, "within_sending_limits", within,
                 f"sent today {sent_today}/{mailbox['daily_send_limit']}")
            provider = mailbox["provider"]
    else:
        _add(checks, "mailbox_healthy", True, "no mailbox bound")
        _add(checks, "domain_healthy", True, "no sending domain bound")
        _add(checks, "within_sending_limits", True, "no mailbox bound")

    _add(checks, "provider_available", True,
         f"transport provider {provider!r}" if provider
         else "no mailbox bound — default transport")

    # --------------------------------------------------------------- campaign
    if msg["campaign_id"] is None:
        _add(checks, "campaign_active", True, "no campaign")
    else:
        active = msg["campaign_status"] == "active"
        _add(checks, "campaign_active", active,
             f"campaign status {msg['campaign_status']!r}")

    # --------------------------------------------------------------- sequence
    sequence_step = msg["sequence_step"] or 0
    if sequence_step == 0:
        _add(checks, "sequence_state_ok", True, "initial send (step 0)")
        _add(checks, "followup_mailbox_correct", True, "initial send (step 0)")
    else:
        replied = _lead_replied_after_last_outbound(str(msg["lead_id"]))
        _add(checks, "sequence_state_ok", not replied,
             "lead replied after last outbound"
             if replied else "no inbound reply after last outbound")
        original_mb = _original_mailbox(str(msg["lead_id"]), sequence_step)
        bound = msg["originating_mailbox_id"]
        if original_mb is None:
            _add(checks, "followup_mailbox_correct", False,
                 "original message has no mailbox record")
        elif bound is None:
            _add(checks, "followup_mailbox_correct", False,
                 "no originating mailbox bound to follow-up")
        elif str(original_mb) != str(bound):
            _add(checks, "followup_mailbox_correct", False,
                 f"follow-up mailbox {bound} != original mailbox {original_mb}")
        else:
            _add(checks, "followup_mailbox_correct", True,
                 "matches original message mailbox")

    reasons = [c["detail"] for c in checks if not c["passed"]]
    return {"allowed": not reasons, "reasons": reasons, "checks": checks}
