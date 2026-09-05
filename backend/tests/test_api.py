import os

import psycopg
import pytest

from conftest import make_lead


from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers(client):
    resp = client.post("/api/auth/register", json={
        "email": "api@test.dev", "password": "password-123456",
        "display_name": "API Tester",
    })
    assert resp.status_code == 201, resp.text
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}


class TestAuth:
    def test_register_login_me(self, client, auth_headers):
        me = client.get("/api/auth/me", headers=auth_headers)
        assert me.status_code == 200
        assert me.json()["email"] == "api@test.dev"

    def test_wrong_password_401(self, client):
        client.post("/api/auth/register", json={
            "email": "pw@test.dev", "password": "password-123456"})
        resp = client.post("/api/auth/login", json={
            "email": "pw@test.dev", "password": "wrong-password"})
        assert resp.status_code == 401

    def test_weak_password_rejected(self, client):
        resp = client.post("/api/auth/register", json={
            "email": "weak@test.dev", "password": "short"})
        assert resp.status_code == 422


class TestLeadApi:
    def test_create_with_dedupe(self, client, auth_headers):
        body = {"company": {"business_name": "Dedupe Test Co",
                            "city": "Gboro", "state": "NC"}}
        r1 = client.post("/api/leads", json=body, headers=auth_headers)
        r2 = client.post("/api/leads", json=body, headers=auth_headers)
        assert r1.json()["deduped"] is False
        assert r2.json()["deduped"] is True
        assert r1.json()["company_id"] == r2.json()["company_id"]

    def test_workspace_isolation(self, client, auth_headers):
        """RLS-equivalent: another workspace's leads are invisible."""
        client.post("/api/leads", json={
            "company": {"business_name": "Mine Only"}}, headers=auth_headers)
        # second workspace
        token2 = client.post("/api/auth/register", json={
            "email": "other@test.dev", "password": "password-123456"}).json()["token"]
        resp = client.get("/api/leads?q=Mine", headers={
            "Authorization": f"Bearer {token2}"})
        assert resp.json()["total"] == 0

    def test_score_endpoint(self, client, auth_headers):
        lead = client.post("/api/leads", json={
            "company": {"business_name": "Score Co"}}, headers=auth_headers).json()
        resp = client.post(f"/api/leads/{lead['id']}/score", headers=auth_headers,
                           json={"signals": {"single_location": True,
                                             "owner_visible": True}})
        data = resp.json()
        assert 0 <= data["lead_score"] <= 10
        assert data["fit_status"] in ("qualified", "borderline",
                                      "rejected_not_relevant")

    def test_transition_validation(self, client, auth_headers):
        lead = client.post("/api/leads", json={
            "company": {"business_name": "Trans Co"}}, headers=auth_headers).json()
        bad = client.post(f"/api/leads/{lead['id']}/transition", headers=auth_headers,
                          json={"to_status": "won"})
        assert bad.status_code == 409
        good = client.post(f"/api/leads/{lead['id']}/transition", headers=auth_headers,
                           json={"to_status": "rejected", "reason": "test"})
        assert good.status_code == 200


class TestHiringIntentIsolation:
    def test_queue_email_only_no_call_path(self):
        """Spec §19.5: no code path from hiring-intent queue to dialer/SMS."""
        import pathlib

        source = (pathlib.Path(__file__).parents[1] / "app" / "routers"
                  / "hiring_intent.py").read_text()
        assert "twilio" not in source.lower()
        assert "'sms'" not in source
        assert "/dialer" not in source

    def test_ingest_dedupes_and_queues(self, client, auth_headers, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        posting = {
            "source": "test_feed", "source_url": "https://jobs.example.com/1",
            "external_job_id": "job-001", "title": "Front Desk Receptionist",
            "description_raw": "Answer 50+ calls daily, schedule service appointments. "
                               "HVAC company.",
            "company_name": "Test HVAC", "contact_email": "owner@testhvac.test",
            "posted_at": "2026-08-20T12:00:00Z",
        }
        r1 = client.post("/api/hiring-intent/ingest", json=posting,
                         headers=auth_headers)
        r2 = client.post("/api/hiring-intent/ingest", json=posting,
                         headers=auth_headers)
        assert r1.json()["duplicate"] is False
        assert r2.json()["duplicate"] is True
        q = client.get("/api/hiring-intent/queue", headers=auth_headers).json()
        titles = [i["title"] for i in q["items"]]
        assert titles.count("Front Desk Receptionist") <= 1


class TestWebhooksIdempotent:
    def test_twilio_status_replay_safe(self, db_url, workspace, client, auth_headers):
        ws, _ = workspace
        lead = make_lead(db_url, ws)
        conn = psycopg.connect(db_url, autocommit=True)
        call = str(conn.execute(
            """INSERT INTO calls (workspace_id, lead_id, direction, to_number,
                   twilio_call_sid) VALUES (%s,%s,'outbound','+13365550000','SMTW1')
               RETURNING id""",
            (ws, lead),
        ).fetchone()[0])
        conn.close()
        # Set env vars so the webhook endpoint doesn't 503 and skips HMAC validation
        os.environ["TWILIO_AUTH_TOKEN"] = "test-token"
        os.environ["ORBIT_ENV"] = "test"
        try:
            payload = {"CallSid": "SMTW1", "CallDuration": "42"}
            for _ in range(3):  # duplicate webhook deliveries
                resp = client.post("/api/dialer/twilio-webhook", data=payload)
                assert resp.status_code == 200
        finally:
            os.environ.pop("TWILIO_AUTH_TOKEN", None)
        conn = psycopg.connect(db_url, autocommit=True)
        duration = conn.execute(
            "SELECT duration_seconds FROM calls WHERE id=%s", (call,)
        ).fetchone()[0]
        count = conn.execute(
            "SELECT count(*) FROM calls WHERE twilio_call_sid='SMTW1'"
        ).fetchone()[0]
        conn.close()
        assert duration == 42
        assert count == 1
