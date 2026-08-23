import psycopg
import pytest

from app.services import suppression
from app.services.phones import dedupe_key, normalize_phone
from tests.conftest import make_lead


class TestPhoneNormalization:
    def test_ten_digit(self):
        assert normalize_phone("3365551212") == "+13365551212"

    def test_formatted(self):
        assert normalize_phone("(336) 555-1212") == "+13365551212"

    def test_leading_one(self):
        assert normalize_phone("1-336-555-1212") == "+13365551212"

    def test_already_e164(self):
        assert normalize_phone("+13365551212") == "+13365551212"

    def test_garbage_returns_none(self):
        assert normalize_phone("no phone") is None
        assert normalize_phone("") is None
        assert normalize_phone(None) is None

    def test_dedupe_key_case_insensitive(self):
        assert dedupe_key("Acme Plumbing", "Greensboro", "NC") == \
               dedupe_key("acme plumbing ", "greensboro", "nc")


class TestSuppression:
    def test_blocks_suppressed_email(self, db_url, workspace):
        ws, _ = workspace
        conn = psycopg.connect(db_url, autocommit=True)
        suppression.add(conn, workspace_id=ws, scope="email",
                        value="bad@corp.com", reason="bounce")
        conn.close()
        result = suppression.check(workspace_id=ws, email="BAD@corp.com")
        assert result.blocked
        assert "bounce" in result.reason

    def test_global_scope_blocks_everything(self, db_url, workspace):
        ws, _ = workspace
        conn = psycopg.connect(db_url, autocommit=True)
        suppression.add(conn, workspace_id=ws, scope="global", value="*",
                        reason="workspace paused")
        conn.close()
        assert suppression.check(workspace_id=ws, email="a@b.co").blocked
        assert suppression.check(workspace_id=ws, phone="+13365550000").blocked

    def test_clean_lead_passes(self, db_url, workspace):
        ws, _ = workspace
        result = suppression.check(workspace_id=ws, email="fine@ok.com")
        assert not result.blocked

    def test_do_not_call_disposition_suppresses_everywhere(self, db_url, workspace):
        """Spec §19.4: do_not_call disposition immediately suppresses the lead."""
        from app.services.twilio_service import set_disposition

        ws, _ = workspace
        lead_id = make_lead(db_url, ws)
        conn = psycopg.connect(db_url, autocommit=True)
        contact = conn.execute(
            """INSERT INTO contacts (workspace_id, company_id, email, phone)
               SELECT %s, company_id, 'owner@acme.test', '+13365550001'
               FROM leads WHERE id=%s RETURNING id""",
            (ws, lead_id),
        ).fetchone()[0]
        conn.execute("UPDATE leads SET contact_id=%s WHERE id=%s", (contact, lead_id))
        call = conn.execute(
            """INSERT INTO calls (workspace_id, lead_id, direction, to_number, called_at)
               VALUES (%s,%s,'outbound','+13365550001',now()) RETURNING id""",
            (ws, lead_id),
        ).fetchone()[0]
        conn.close()

        set_disposition(ws, str(call), "do_not_call")

        conn = psycopg.connect(db_url, autocommit=True)
        status = conn.execute(
            "SELECT status FROM leads WHERE id=%s", (lead_id,)
        ).fetchone()[0]
        assert status == "do_not_call"
        assert suppression.check(workspace_id=ws, email="owner@acme.test").blocked
        assert suppression.check(workspace_id=ws, phone="+13365550001").blocked
        conn.close()
