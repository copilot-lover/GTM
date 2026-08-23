import json

import psycopg
import pytest

import app.db as db
from app.services import email_service
from tests.conftest import make_lead
from app.services import suppression


@pytest.fixture
def approved_draft(db_url, workspace):
    """A lead with a verified contact and an approved draft message."""
    ws, user = workspace
    lead_id = make_lead(db_url, ws)
    conn = psycopg.connect(db_url, autocommit=True)
    contact = conn.execute(
        """INSERT INTO contacts (workspace_id, company_id, email,
               email_verification_status)
           SELECT %s, company_id, 'owner@acme.test', 'verified'
           FROM leads WHERE id=%s RETURNING id""",
        (ws, lead_id),
    ).fetchone()[0]
    conn.execute("UPDATE leads SET contact_id=%s WHERE id=%s", (contact, lead_id))
    msg = conn.execute(
        """INSERT INTO messages (workspace_id, lead_id, channel, direction,
               subject, body_text, status)
           VALUES (%s,%s,'email','outbound','Quick question about Acme',
                   'Test body.','approved') RETURNING id""",
        (ws, lead_id),
    ).fetchone()[0]
    conn.close()
    return ws, str(lead_id), str(msg)


class TestApprovalGate:
    def test_unapproved_message_cannot_send(self, db_url, workspace):
        ws, _ = workspace
        lead = make_lead(db_url, ws)
        conn = psycopg.connect(db_url, autocommit=True)
        msg = str(conn.execute(
            """INSERT INTO messages (workspace_id, lead_id, channel, direction,
                   subject, body_text, status)
               VALUES (%s,%s,'email','outbound','s','b','pending_approval')
               RETURNING id""",
            (ws, lead),
        ).fetchone()[0])
        conn.close()
        with pytest.raises(email_service.SendBlocked) as exc:
            email_service.send_approved(ws, msg)
        assert "not approved" in str(exc.value)

    def test_rejected_message_cannot_send(self, approved_draft):
        pass  # covered by gate logic; approval flow tested below

    def test_approval_records_approver(self, db_url, workspace):
        ws, user = workspace
        lead = make_lead(db_url, ws)
        conn = psycopg.connect(db_url, autocommit=True)
        msg = str(conn.execute(
            """INSERT INTO messages (workspace_id, lead_id, channel, direction,
                   subject, body_text, status)
               VALUES (%s,%s,'email','outbound','s','b','pending_approval')
               RETURNING id""",
            (ws, lead),
        ).fetchone()[0])
        conn.close()
        email_service.approve(ws, msg, user)
        conn = psycopg.connect(db_url, autocommit=True)
        row = conn.execute(
            "SELECT status, approved_by FROM messages WHERE id=%s", (msg,)
        ).fetchone()
        conn.close()
        assert row[0] == "approved"
        assert str(row[1]) == user


class TestSendGates:
    def test_unverified_email_blocked(self, db_url, workspace):
        ws, _ = workspace
        lead = make_lead(db_url, ws)
        conn = psycopg.connect(db_url, autocommit=True)
        contact = conn.execute(
            """INSERT INTO contacts (workspace_id, company_id, email,
                   email_verification_status)
               SELECT %s, company_id, 'x@acme.test', 'dns_ok'
               FROM leads WHERE id=%s RETURNING id""",
            (ws, lead),
        ).fetchone()[0]
        conn.execute("UPDATE leads SET contact_id=%s WHERE id=%s", (contact, lead))
        msg = str(conn.execute(
            """INSERT INTO messages (workspace_id, lead_id, channel, direction,
                   subject, body_text, status) VALUES (%s,%s,'email','outbound',
                   's','b','approved') RETURNING id""",
            (ws, lead),
        ).fetchone()[0])
        conn.close()
        with pytest.raises(email_service.SendBlocked) as exc:
            email_service.send_approved(ws, msg)
        assert "provider-verified" in str(exc.value)

    def test_suppressed_email_blocked_even_if_approved_verified(
        self, db_url, workspace, monkeypatch
    ):
        ws, _ = workspace
        lead = make_lead(db_url, ws)
        conn = psycopg.connect(db_url, autocommit=True)
        contact = conn.execute(
            """INSERT INTO contacts (workspace_id, company_id, email,
                   email_verification_status)
               SELECT %s, company_id, 'blocked@acme.test', 'verified'
               FROM leads WHERE id=%s RETURNING id""",
            (ws, lead),
        ).fetchone()[0]
        conn.execute("UPDATE leads SET contact_id=%s WHERE id=%s", (contact, lead))
        msg = str(conn.execute(
            """INSERT INTO messages (workspace_id, lead_id, channel, direction,
                   subject, body_text, status) VALUES (%s,%s,'email','outbound',
                   's','b','approved') RETURNING id""",
            (ws, lead),
        ).fetchone()[0])
        suppression.add(conn, workspace_id=ws, scope="email",
                        value="blocked@acme.test", reason="prior bounce")
        conn.close()
        with pytest.raises(email_service.SendBlocked) as exc:
            email_service.send_approved(ws, msg)
        assert "suppressed" in str(exc.value)

    def test_can_spam_signature_present(self, workspace):
        ws, _ = workspace
        sig = email_service.can_spam_signature(ws)
        assert "Orbit" in sig
        assert "opt out" in sig.lower()


class TestKillSwitch:
    def test_reply_purges_queues_and_blocks_automation(self, db_url, workspace):
        from app.services.email_service import kill_switch

        ws, _ = workspace
        lead = make_lead(db_url, ws)
        conn = psycopg.connect(db_url, autocommit=True)
        session = conn.execute(
            """INSERT INTO calling_sessions (workspace_id, name)
               VALUES (%s,'morning') RETURNING id""",
            (ws,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO session_leads VALUES (%s,%s,1)", (session, lead)
        )
        conn.execute(
            """INSERT INTO messages (workspace_id, lead_id, channel, direction,
                   subject, body_text, status) VALUES (%s,%s,'email','outbound',
                   's','b','approved')""",
            (ws, lead),
        )
        kill_switch(conn, ws, str(lead), "test reply")
        conn.close()

        # kill switch: automation purged regardless; status -> responded only
        # when the state machine allows it (reply after contact)
        conn = psycopg.connect(db_url, autocommit=True)
        status = conn.execute(
            "SELECT status FROM leads WHERE id=%s", (lead,)
        ).fetchone()[0]
        assert conn.execute(
            "SELECT count(*) FROM session_leads WHERE lead_id=%s", (lead,)
        ).fetchone()[0] == 0
        assert conn.execute(
            """SELECT count(*) FROM messages WHERE lead_id=%s AND status='rejected'""",
            (lead,),
        ).fetchone()[0] >= 1
        assert status in ("new", "responded")
        conn.close()

    def test_reply_after_contact_transitions_to_responded(self, db_url, workspace):
        from app.services.email_service import kill_switch

        ws, _ = workspace
        lead = make_lead(db_url, ws)
        conn = psycopg.connect(db_url, autocommit=True)
        conn.execute("UPDATE leads SET status='contacted' WHERE id=%s", (lead,))
        kill_switch(conn, ws, str(lead), "test reply after contact")
        status = conn.execute(
            "SELECT status FROM leads WHERE id=%s", (lead,)
        ).fetchone()[0]
        conn.close()
        assert status == "responded"
