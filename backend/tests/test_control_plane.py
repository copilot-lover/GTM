"""Tests for WS-F Control-Plane APIs."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import psycopg
import psycopg.rows
import pytest
from fastapi.testclient import TestClient

import app.db as db
from app.services import flags

from tests.conftest import TEST_DB_URL


def _test_conn():
    return psycopg.connect(TEST_DB_URL, autocommit=True)


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_header(workspace):
    ws_id, user_id = workspace
    from app.core.security import create_token
    token = create_token(user_id, ws_id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def seed_mailboxes(workspace):
    ws_id, _ = workspace
    conn = _test_conn()
    domain_id = conn.execute(
        """INSERT INTO sending_domains (domain, provider, status)
           VALUES ('testdomain.com', 'smtp', 'active') RETURNING id"""
    ).fetchone()[0]
    for i, email in enumerate(["a@testdomain.com", "b@testdomain.com"]):
        conn.execute(
            """INSERT INTO mailboxes (workspace_id, email, provider, domain_id, status,
               health_score, health_state, daily_send_limit, sent_today)
               VALUES (%s,%s,'smtp',%s,'ready',%s,%s,30,%s)""",
            (ws_id, email, domain_id,
             95 if i == 0 else 70,
             "healthy" if i == 0 else "reduced",
             10 if i == 0 else 25),
        )
    conn.close()
    return ws_id


@pytest.fixture
def seed_hiring_signals(workspace):
    ws_id, _ = workspace
    conn = _test_conn()
    company_id = conn.execute(
        """INSERT INTO companies (workspace_id, business_name, city, state)
           VALUES (%s, 'SignalCo', 'Austin', 'TX') RETURNING id""",
        (ws_id,),
    ).fetchone()[0]
    now = datetime.now(timezone.utc)
    for i in range(3):
        conn.execute(
            """INSERT INTO hiring_signals
               (workspace_id, company_id, source, source_job_id, title, description,
                role_category, signal_score, freshness_multiplier, status, posted_at,
                discovered_at)
               VALUES (%s,%s,'test',%s,%s,'desc','dispatcher',%s,1.0,'active',%s,%s)""",
            (ws_id, company_id, f"sig-{i}", f"Dispatcher {i}", 70 + i * 5,
             now - timedelta(days=i), now - timedelta(days=i)),
        )
    conn.close()
    return ws_id


@pytest.fixture
def seed_leads(workspace):
    ws_id, _ = workspace
    conn = _test_conn()
    company_id = conn.execute(
        """INSERT INTO companies (workspace_id, business_name, city, state, vertical)
           VALUES (%s, 'LeadCo', 'Dallas', 'TX', 'plumbing') RETURNING id""",
        (ws_id,),
    ).fetchone()[0]
    contact_id = conn.execute(
        """INSERT INTO contacts (workspace_id, company_id, name, email, is_decision_maker)
           VALUES (%s,%s,'John Doe','john@leadco.com',true) RETURNING id""",
        (ws_id, company_id),
    ).fetchone()[0]
    lead_id = conn.execute(
        """INSERT INTO leads (workspace_id, company_id, contact_id, status)
           VALUES (%s,%s,%s,'new') RETURNING id""",
        (ws_id, company_id, contact_id),
    ).fetchone()[0]
    conn.execute(
        """INSERT INTO scores (workspace_id, lead_id, score_type, score, tier)
           VALUES (%s,%s,'opportunity',85,'A')""",
        (ws_id, lead_id),
    )
    conn.close()
    return ws_id


class TestOverview:
    def test_overview_returns_health_data(self, client, auth_header, seed_mailboxes):
        resp = client.get("/api/control-plane/overview", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert "domains" in data
        assert "mailboxes" in data
        assert "n8n" in data
        assert "database" in data
        assert "capacity" in data
        assert "health_score" in data
        assert isinstance(data["health_score"], int)
        assert 0 <= data["health_score"] <= 100
        assert data["database"] == "ok"


class TestSignals:
    def test_signals_dashboard_filters(self, client, auth_header, seed_hiring_signals):
        resp = client.get(
            "/api/control-plane/signals?role_category=dispatcher&min_score=70",
            headers=auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "summary" in data
        assert "hiring_signals" in data
        assert data["summary"]["by_role_category"].get("dispatcher", 0) >= 1
        for sig in data["hiring_signals"]:
            assert sig["role_category"] == "dispatcher"
            assert sig["signal_score"] >= 70


class TestLeadsQueue:
    def test_leads_queue_sorting(self, client, auth_header, seed_leads):
        resp = client.get(
            "/api/control-plane/leads-queue?sort=opportunity_score&page=1&page_size=10",
            headers=auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert data["total"] >= 1
        scores = [item["opportunity_score"] for item in data["items"]]
        assert scores == sorted(scores, reverse=True)


class TestProviders:
    def test_provider_dashboard_shows_usage(self, client, auth_header):
        resp = client.get("/api/control-plane/providers", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert "period" in data
        assert "providers" in data
        assert "circuit_breakers" in data


class TestPauseResume:
    def test_pause_resume_kill_switches(self, client, auth_header):
        resp = client.post(
            "/api/control-plane/pause",
            json={"target": "all"},
            headers=auth_header,
        )
        assert resp.status_code == 200
        assert resp.json()["paused"] == "all"

        val = flags.get_flag("pause_all_sending")
        assert val is True

        resp = client.post(
            "/api/control-plane/resume",
            json={"target": "all"},
            headers=auth_header,
        )
        assert resp.status_code == 200
        val = flags.get_flag("pause_all_sending")
        assert val is False


class TestAddDomain:
    def test_add_domain_dns_check(self, client, auth_header):
        mock_dns = {
            "spf": {"verified": True, "details": "found"},
            "dkim": {"verified": True, "details": "found"},
            "dmarc": {"verified": True, "details": "found"},
            "mx": {"verified": True, "details": "mx1.example.com"},
        }
        with patch("app.services.mailbox_health._dns_check", return_value=mock_dns):
            resp = client.post(
                "/api/control-plane/domain",
                json={"domain": "newdomain.com", "provider": "smtp"},
                headers=auth_header,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert data["domain"]["status"] == "active"
            assert data["domain"]["dns_status"]["spf"]["verified"] is True


class TestAddMailbox:
    def test_add_mailbox_creates_record(self, client, auth_header, seed_mailboxes):
        resp = client.post(
            "/api/control-plane/mailbox",
            json={
                "email": "new@testdomain.com",
                "provider": "smtp",
                "domain": "testdomain.com",
                "daily_limit": 25,
            },
            headers=auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["mailbox"]["email"] == "new@testdomain.com"
        assert data["mailbox"]["daily_send_limit"] == 25


class TestAlerts:
    def test_alerts_lifecycle(self, client, auth_header, workspace):
        ws_id, _ = workspace
        # Create alert
        with db.get_pool().connection() as conn:
            conn.row_factory = psycopg.rows.dict_row
            alert = conn.execute(
                """INSERT INTO alerts (workspace_id, severity, message, status)
                   VALUES (%s,'warning','test alert','open') RETURNING id""",
                (ws_id,),
            ).fetchone()
        alert_id = str(alert["id"])

        # List
        resp = client.get("/api/control-plane/alerts", headers=auth_header)
        assert resp.status_code == 200
        assert len(resp.json()["alerts"]) >= 1

        # Resolve
        resp = client.post(
            f"/api/control-plane/alerts/{alert_id}/resolve", headers=auth_header
        )
        assert resp.status_code == 200
        assert resp.json()["resolved"] == alert_id


class TestAuditHistory:
    def test_audit_history(self, client, auth_header, workspace):
        ws_id, _ = workspace
        # Seed an audit record
        with db.get_pool().connection() as conn:
            conn.execute(
                """INSERT INTO daily_audits (audit_date, overall_score, report)
                   VALUES (now()::date, 85, '{}')
                   ON CONFLICT (audit_date) DO NOTHING"""
            )
        resp = client.get("/api/control-plane/audit/history", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert "audits" in data
        assert len(data["audits"]) >= 1


class TestTelegram:
    def test_telegram_send_message(self, client, auth_header):
        from app.services import telegram

        with db.get_pool().connection() as conn:
            conn.execute(
                """INSERT INTO telegram_settings (id, bot_token_encrypted, chat_id, enabled)
                   VALUES (true, 'fake_encrypted', '12345', true)
                   ON CONFLICT (id) DO UPDATE
                   SET bot_token_encrypted=EXCLUDED.bot_token_encrypted,
                       chat_id=EXCLUDED.chat_id, enabled=EXCLUDED.enabled"""
            )

        with patch.object(telegram, "_decrypt_token", return_value="fake:token"), \
             patch("app.services.telegram.httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"ok": True}
            mock_post.return_value = mock_resp

            result = telegram.send_message("test")
            assert result["ok"] is True

    def test_telegram_settings_encrypt_token(self, client, auth_header):
        from app.services import telegram
        from app.config import get_settings

        settings = get_settings()
        if not settings.app_secret:
            pytest.skip("app_secret not set")

        token = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"
        encrypted = telegram._encrypt_token(token)
        assert encrypted != token
        decrypted = telegram._decrypt_token(encrypted)
        assert decrypted == token


class TestMailboxes:
    def test_mailboxes_endpoint(self, client, auth_header, seed_mailboxes):
        resp = client.get("/api/control-plane/mailboxes", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert "domains" in data
        assert "testdomain.com" in data["domains"]
        assert len(data["domains"]["testdomain.com"]) == 2
