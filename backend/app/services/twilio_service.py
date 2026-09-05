"""Dialer: Twilio Voice via REST + WebRTC access tokens.
Application-owned call state in Postgres; webhooks idempotent by CallSid."""

import os
import time

import httpx
import jwt as pyjwt

import app.db as db


class TwilioError(Exception):
    pass


def _creds() -> tuple[str, str]:
    sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if not sid or not token:
        raise TwilioError("twilio credentials not configured")
    return sid, token


def configured() -> bool:
    try:
        _creds()
        return True
    except TwilioError:
        return False


# ------------------------------------------------------------- WebRTC token

def access_token(identity: str, ttl_seconds: int = 3600) -> str:
    """Short-lived Twilio Voice access token (JWT HS256 signed with API Key)."""
    account_sid, _ = _creds()
    api_key_sid = os.environ.get("TWILIO_API_KEY_SID", "")
    api_key_secret = os.environ.get("TWILIO_API_KEY_SECRET", "")
    twiml_app_sid = os.environ.get("TWILIO_TWIML_APP_SID", "")
    if not all([api_key_sid, api_key_secret, twiml_app_sid]):
        raise TwilioError("twilio API key / TwiML app not configured")
    now = int(time.time())
    payload = {
        "jti": f"{api_key_sid}-{now}",
        "iss": api_key_sid,
        "sub": account_sid,
        "nbf": now,
        "exp": now + ttl_seconds,
        "grants": {
            "identity": identity,
            "voice": {"outgoing": {"application_sid": twiml_app_sid},
                      "incoming": {"allow": True}},
        },
    }
    return pyjwt.encode(payload, api_key_secret, algorithm="HS256",
                        headers={"typ": "JWT", "cty": "twilio-fpa;v=1"})


# ------------------------------------------------------------- click-to-call

TIMEZONE_GUARD_START, TIMEZONE_GUARD_END = 8, 21  # 8 AM – 9 PM prospect local


def timezone_guard_ok(prospect_tz: str | None) -> bool:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(prospect_tz or "America/New_York")
    hour = datetime.now(tz).hour
    return TIMEZONE_GUARD_START <= hour < TIMEZONE_GUARD_END


def place_call(*, workspace_id: str, lead_id: str, to_number: str,
               operator_endpoint: str, session_id: str | None = None,
               prospect_tz: str | None = None) -> dict:
    """Click-to-call: dials the lead and connects the operator's browser/client."""
    if not timezone_guard_ok(prospect_tz):
        raise TwilioError(
            "outside allowed calling window (8 AM - 9 PM prospect local time)"
        )

    # DNC/suppression gate — enforced in code, not UI. Normalized phone AND
    # company scope, so a reformatted number cannot bypass a do_not_call.
    from app.services import suppression
    from app.services.phones import normalize_phone

    company_id: str | None = None
    if lead_id:
        with db.get_pool().connection() as conn:
            row = conn.execute(
                "SELECT company_id FROM leads WHERE id=%s AND workspace_id=%s",
                (lead_id, workspace_id),
            ).fetchone()
            if row:
                company_id = str(row["company_id"])
    result = suppression.check(
        workspace_id=workspace_id,
        phone=normalize_phone(to_number) or to_number,
        company_id=company_id,
    )
    if result.blocked:
        raise TwilioError(f"suppressed: {result.reason}")

    account_sid, token = _creds()
    caller_id = os.environ.get("TWILIO_CALLER_ID", "")
    if not caller_id:
        raise TwilioError("TWILIO_CALLER_ID not configured")

    params = {
        "To": to_number,
        "From": caller_id,
        "Url": operator_endpoint,
        "StatusCallbackEvent[]": ["initiated", "answered", "completed"],
        "RecordingStatusCallbackEvent": ["completed"],
    }
    resp = httpx.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Calls.json",
        auth=(account_sid, token),
        data=params,
        timeout=30,
    )
    if resp.status_code >= 400:
        raise TwilioError(f"twilio error {resp.status_code}: {resp.text[:300]}")
    data = resp.json()

    with db.get_pool().connection() as conn:
        conn.row_factory = db_psycopg_rows()
        row = conn.execute(
            """INSERT INTO calls (workspace_id, lead_id, session_id, twilio_call_sid,
                   direction, from_number, to_number, disposition, called_at)
               VALUES (%s,%s,%s,%s,'outbound',%s,%s,'dialed',now())
               ON CONFLICT (twilio_call_sid) DO NOTHING RETURNING id""",
            (workspace_id, lead_id, session_id, data["sid"], caller_id, to_number),
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT id FROM calls WHERE twilio_call_sid=%s", (data["sid"],)
            ).fetchone()
    return {"call_sid": data["sid"], "call_id": str(row["id"]), "status": data["status"]}


# ------------------------------------------------------------------ webhooks

def process_status_webhook(payload: dict) -> dict:
    """Idempotent reconciliation of Twilio status callbacks."""
    call_sid = payload.get("CallSid") or payload.get("CallUUID")
    if not call_sid:
        return {"ignored": True}
    duration = payload.get("CallDuration") or payload.get("DialCallDuration") or 0
    recording_sid = payload.get("RecordingSid")
    recording_url = (
        f"https://api.twilio.com/2010-04-01/Accounts/{os.environ.get('TWILIO_ACCOUNT_SID','')}"
        f"/Recordings/{recording_sid}.mp3"
        if recording_sid else payload.get("RecordingUrl")
    )
    with db.get_pool().connection() as conn:
        conn.execute(
            """UPDATE calls SET duration_seconds=%s,
                   recording_url=COALESCE(%s, recording_url),
                   called_at=COALESCE(called_at, now())
               WHERE twilio_call_sid=%s""",
            (int(duration), recording_url, call_sid),
        )
    return {"updated": call_sid}


def set_disposition(workspace_id: str, call_id: str, disposition: str,
                    notes: str | None = None) -> dict:
    valid = {"connected_dm", "connected_gk", "connected_other", "voicemail", "busy",
             "no_answer", "bad_number", "not_interested", "do_not_call",
             "callback_requested", "appointment_set", "dialed"}
    if disposition not in valid:
        raise TwilioError(f"invalid disposition {disposition}")
    with db.get_pool().connection() as conn:
        conn.row_factory = db_psycopg_rows()
        row = conn.execute(
            "SELECT lead_id FROM calls WHERE id=%s AND workspace_id=%s",
            (call_id, workspace_id),
        ).fetchone()
        if row is None:
            raise TwilioError("call not found")
        conn.execute(
            """UPDATE calls SET disposition=%s, notes=COALESCE(%s, notes),
               edited_at=now(), duration_seconds=
                   COALESCE(NULLIF(duration_seconds,0),
                       EXTRACT(EPOCH FROM (now()-called_at))::int)
               WHERE id=%s""",
            (disposition, notes, call_id),
        )
        lead_id = str(row["lead_id"]) if row["lead_id"] else None
        conn.execute("UPDATE leads SET outcome='completed' WHERE id=%s", (row["lead_id"],))
        if lead_id:
            conn.execute(
                """INSERT INTO activities (workspace_id, lead_id, type, summary, actor)
                   VALUES (%s,%s,'call',%s,'human')""",
                (workspace_id, lead_id, f"call dispositioned: {disposition}"),
            )
            if disposition == "do_not_call":
                _suppress_lead(conn, workspace_id, lead_id)
            elif disposition == "appointment_set":
                conn.execute(
                    """INSERT INTO activities (workspace_id, lead_id, type, summary, actor)
                       VALUES (%s,%s,'system','appointment_set — create meeting + alert','system')""",
                    (workspace_id, lead_id),
                )
    return {"ok": True}


def db_psycopg_rows():
    from psycopg.rows import dict_row

    return dict_row


def _suppress_lead(conn, workspace_id: str, lead_id: str) -> None:
    from app.services import suppression
    from app.services.phones import normalize_phone
    from app.services.state_machine import can_transition

    row = conn.execute(
        """SELECT l.company_id, c.email, c.phone AS contact_phone,
                  co.phone AS company_phone
           FROM leads l
           JOIN companies co ON co.id=l.company_id
           LEFT JOIN contacts c ON c.id=l.contact_id
           WHERE l.id=%s""",
        (lead_id,),
    ).fetchone()
    if row is None:
        return
    suppression.add(conn, workspace_id=workspace_id, scope="company",
                    value=str(row["company_id"]), reason="do_not_call disposition")
    if row["email"]:
        suppression.add(conn, workspace_id=workspace_id, scope="email",
                        value=row["email"], reason="do_not_call disposition")
    for phone in (row.get("contact_phone"), row.get("company_phone")):
        if phone:
            suppression.add(conn, workspace_id=workspace_id, scope="phone",
                            value=normalize_phone(phone) or phone,
                            reason="do_not_call disposition")
    current = conn.execute(
        "SELECT status FROM leads WHERE id=%s", (lead_id,)
    ).fetchone()
    current_status = current["status"] if isinstance(current, dict) else current[0]
    if can_transition(current_status, "do_not_call"):
        conn.execute("UPDATE leads SET status='do_not_call', updated_at=now() WHERE id=%s",
                     (lead_id,))
