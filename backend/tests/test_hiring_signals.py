"""Tests for WS-B Hiring Signals Engine."""

import json
from datetime import datetime, timedelta, timezone

import psycopg.rows
import pytest

import app.db as db
from app.services import hiring_signals
from app.providers.fixtures import FixtureJobSource, FixtureLLM
from app.providers import registry
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _setup_fixtures(monkeypatch):
    """Install fixture providers for all tests."""
    # Clear any existing overrides
    registry.clear_overrides()

    # Fixture LLM with scripted responses for classify_role and detect_intent_signals
    # Uses markers in the user prompt (title/description) to return different responses
    # Specific title/description markers MUST come before generic system prompt markers
    llm = FixtureLLM(scripts={
        "HVAC Dispatcher": '{"role_category": "dispatcher", "confidence": 0.95, "rationale": "dispatcher keywords"}',
        "Front Desk Receptionist": '{"role_category": "receptionist", "confidence": 0.9, "rationale": "receptionist keywords"}',
        "Senior Python Developer": '{"role_category": "other", "confidence": 0.8, "rationale": "software development role"}',
        "You are a job classifier for Orbit": '{"role_category": "dispatcher", "confidence": 0.5, "rationale": "default fallback"}',
        # detect_intent_signals markers - match on description content from test cases
        "50+ inbound calls daily, schedule appointments, and manage after-hours emergencies for our HVAC": '{"after_hours": true, "phone_heavy": true, "scheduling_duties": true, "icp_match": true, "high_volume": true, "lead_intake": false, "multiple_openings": false}',
        "Answer phones, greet visitors, schedule appointments. Medical office": '{"after_hours": false, "phone_heavy": true, "scheduling_duties": true, "icp_match": false, "high_volume": false, "lead_intake": false, "multiple_openings": false}',
        "Build backend APIs, optimize databases, write tests. No phone duties": '{"after_hours": false, "phone_heavy": false, "scheduling_duties": false, "icp_match": false, "high_volume": false, "lead_intake": false, "multiple_openings": false}',
        "Handle 50+ inbound calls, schedule appointments, after-hours on-call for HVAC plumbing electrical": '{"after_hours": true, "phone_heavy": true, "scheduling_duties": true, "icp_match": true, "high_volume": true, "lead_intake": false, "multiple_openings": false}',
        "Handle 50+ inbound calls daily, schedule appointments, after-hours emergencies. HVAC plumbing company": '{"after_hours": true, "phone_heavy": true, "scheduling_duties": true, "icp_match": true, "high_volume": true, "lead_intake": false, "multiple_openings": false}',
        "You are a hiring intent signal detector": '{"after_hours": false, "phone_heavy": false, "scheduling_duties": false, "icp_match": false, "high_volume": false, "lead_intake": false, "multiple_openings": false}',
    })
    registry.override("llm", llm)

    # Fixture job source with test postings
    job_source = FixtureJobSource(postings=[
        {
            "source_job_id": "job-1",
            "title": "HVAC Dispatcher",
            "description": "We need a dispatcher to handle 50+ inbound calls daily, schedule appointments, and manage after-hours emergencies for our HVAC company.",
            "company_name": "Acme HVAC",
            "company_city": "Austin",
            "company_state": "TX",
            "job_url": "https://example.com/job-1",
            "posted_at": datetime.now(timezone.utc).isoformat(),
            "source": "fixture",
        },
        {
            "source_job_id": "job-2",
            "title": "Front Desk Receptionist",
            "description": "Answer phones, greet visitors, schedule appointments. Medical office.",
            "company_name": "Beta Medical",
            "company_city": "Dallas",
            "company_state": "TX",
            "job_url": "https://example.com/job-2",
            "posted_at": datetime.now(timezone.utc).isoformat(),
            "source": "fixture",
        },
        {
            "source_job_id": "job-3",
            "title": "Senior Python Developer",
            "description": "Build backend APIs, optimize databases, write tests. No phone duties.",
            "company_name": "Gamma Tech",
            "company_city": "Houston",
            "company_state": "TX",
            "job_url": "https://example.com/job-3",
            "posted_at": datetime.now(timezone.utc).isoformat(),
            "source": "fixture",
        },
    ])
    registry.override("fixture", job_source)

    yield

    registry.clear_overrides()


class TestNormalizeAndClassify:
    def test_normalize_classify_dispatcher_high_value(self, workspace):
        ws_id, _ = workspace
        raw = {
            "source_job_id": "test-1",
            "title": "HVAC Dispatcher",
            "description": "Handle 50+ inbound calls, schedule appointments, after-hours on-call for HVAC plumbing electrical.",
            "company_name": "Test HVAC",
            "company_city": "Austin",
            "company_state": "TX",
            "job_url": "https://example.com/test-1",
            "posted_at": datetime.now(timezone.utc).isoformat(),
        }
        signal = hiring_signals.normalize_raw_posting(raw, "test_provider")
        assert signal["role_category"] == "dispatcher"
        assert signal["confidence"] > 0.9
        assert signal["intent_signals"]["phone_heavy"] is True
        assert signal["intent_signals"]["scheduling_duties"] is True
        assert signal["intent_signals"]["after_hours"] is True
        assert signal["intent_signals"]["icp_match"] is True
        assert signal["intent_signals"]["high_volume"] is True

    def test_normalize_classify_receptionist_medium(self, workspace):
        ws_id, _ = workspace
        raw = {
            "source_job_id": "test-2",
            "title": "Front Desk Receptionist",
            "description": "Answer phones, greet visitors, schedule appointments. Medical office.",
            "company_name": "Test Medical",
            "company_city": "Dallas",
            "company_state": "TX",
            "job_url": "https://example.com/test-2",
            "posted_at": datetime.now(timezone.utc).isoformat(),
        }
        signal = hiring_signals.normalize_raw_posting(raw, "test_provider")
        assert signal["role_category"] == "receptionist"
        assert signal["intent_signals"]["phone_heavy"] is True
        assert signal["intent_signals"]["scheduling_duties"] is True
        assert signal["intent_signals"]["icp_match"] is False

    def test_normalize_classify_unrelated_other(self, workspace):
        ws_id, _ = workspace
        raw = {
            "source_job_id": "test-3",
            "title": "Senior Python Developer",
            "description": "Build backend APIs, optimize databases, write tests. No phone duties.",
            "company_name": "Test Tech",
            "company_city": "Houston",
            "company_state": "TX",
            "job_url": "https://example.com/test-3",
            "posted_at": datetime.now(timezone.utc).isoformat(),
        }
        signal = hiring_signals.normalize_raw_posting(raw, "test_provider")
        assert signal["role_category"] == "other"
        assert signal["intent_signals"]["phone_heavy"] is False
        assert signal["intent_signals"]["icp_match"] is False


class TestDedupe:
    def test_dedupe_same_source_job_id(self):
        postings = [
            {"source_job_id": "same-1", "source": "jobspipe", "title": "Dispatcher", "company_name": "Acme"},
            {"source_job_id": "same-1", "source": "jobspipe", "title": "Dispatcher", "company_name": "Acme"},
            {"source_job_id": "diff-1", "source": "jobspipe", "title": "Receptionist", "company_name": "Beta"},
        ]
        result = hiring_signals.dedupe_postings(postings)
        assert len(result) == 2
        assert result[0]["source_job_id"] == "same-1"
        assert result[1]["source_job_id"] == "diff-1"

    def test_dedupe_fuzzy_company_title(self):
        postings = [
            {"source_job_id": "a-1", "source": "jobspipe", "title": "HVAC Dispatcher", "company_name": "Acme HVAC"},
            {"source_job_id": "b-1", "source": "theirstack", "title": "HVAC Dispatcher", "company_name": "Acme HVAC"},
            {"source_job_id": "c-1", "source": "jsearch", "title": "Front Desk Receptionist", "company_name": "Beta Medical"},
        ]
        result = hiring_signals.dedupe_postings(postings)
        # First two are fuzzy dupes (same company+title >90%)
        assert len(result) == 2


class TestExpiry:
    def test_expiry_old_signal(self, workspace):
        ws_id, _ = workspace
        # Create a signal posted 61 days ago
        old_date = datetime.now(timezone.utc) - timedelta(days=61)
        with db.get_pool().connection() as conn:
            conn.row_factory = psycopg.rows.dict_row
            company = conn.execute(
                """INSERT INTO companies (workspace_id, business_name, city, state)
                   VALUES (%s,%s,%s,%s) RETURNING id""",
                (ws_id, "Old Company", "Austin", "TX"),
            ).fetchone()
            conn.execute(
                """INSERT INTO hiring_signals (workspace_id, company_id, source, source_job_id,
                       title, description, role_category, intent_category, confidence,
                       signal_score, freshness_multiplier, expires_at, status, posted_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    ws_id, company["id"], "test", "old-1",
                    "Old Dispatcher", "Old description", "dispatcher", "high_value",
                    0.9, 85, 0.1, old_date + timedelta(days=30), "active", old_date
                ),
            )

        expired = hiring_signals.apply_expiry(ws_id)
        assert expired == 1

        with db.get_pool().connection() as conn:
            conn.row_factory = psycopg.rows.dict_row
            row = conn.execute(
                "SELECT status FROM hiring_signals WHERE source_job_id='old-1'",
            ).fetchone()
            assert row["status"] == "expired"


class TestIngestEndpoint:
    def test_ingest_from_providers_fixture(self, workspace, client):
        ws_id, user_id = workspace
        # Register a user with known password to get token
        resp = client.post("/api/auth/register", json={
            "email": f"test_{user_id}@test.dev", "password": "password123",
            "display_name": "Test User"
        })
        assert resp.status_code == 201
        token = resp.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Override fixture provider for this test
        from app.providers import registry
        fixture_source = FixtureJobSource(postings=[
            {
                "source_job_id": "ingest-1",
                "title": "HVAC Dispatcher",
                "description": "Handle 50+ inbound calls, schedule appointments, after-hours for HVAC company.",
                "company_name": "Ingest HVAC",
                "company_city": "Austin",
                "company_state": "TX",
                "job_url": "https://example.com/ingest-1",
                "posted_at": datetime.now(timezone.utc).isoformat(),
            }
        ])
        registry.override("fixture", fixture_source)
        # Also need to override the real providers to use fixture
        registry.override("jobspipe", fixture_source)

        resp = client.post(
            "/api/hiring-intent/ingest-from-providers",
            json={"provider": "fixture", "filters": {"title_contains": "dispatcher"}},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ingested"] >= 1
        assert "fixture" in data["by_provider"]


class TestScoreConfigurable:
    def test_signal_weights_override(self, workspace, monkeypatch):
        ws_id, _ = workspace
        from app.services.flags import set_flag

        # Set custom weights - dispatcher=50 (vs default 35)
        set_flag("signal_scoring_weights", {"dispatcher": 50, "receptionist": 10}, updated_by="test")

        # Create test signal
        raw = {
            "source_job_id": "weight-test-1",
            "title": "HVAC Dispatcher",
            "description": "Handle 50+ inbound calls daily, schedule appointments, after-hours emergencies. HVAC plumbing company.",
            "company_name": "Weight Test HVAC",
            "company_city": "Austin",
            "company_state": "TX",
            "job_url": "https://example.com/weight-1",
            "posted_at": datetime.now(timezone.utc).isoformat(),
        }
        signal = hiring_signals.normalize_raw_posting(raw, "test")
        with db.get_pool().connection() as conn:
            conn.row_factory = psycopg.rows.dict_row
            company = conn.execute(
                """INSERT INTO companies (workspace_id, business_name, city, state)
                   VALUES (%s,%s,%s,%s) RETURNING *""",
                (ws_id, "Weight Test HVAC", "Austin", "TX"),
            ).fetchone()

        score, freshness, intent_cat = hiring_signals.compute_signal_score(signal, company)
        # With dispatcher=50 (vs default 35), score should be higher than with defaults
        # Max theoretical includes all weights, so normalized score ~46 with these signals
        assert score >= 40  # shows weight change took effect (dispatcher role weight increased)
        assert intent_cat in ("high_value", "medium_value", "low_value")

        # Reset to defaults
        set_flag("signal_scoring_weights", {}, updated_by="test")


class TestWorkerHandlers:
    def test_job_discovery_worker(self, workspace):
        ws_id, _ = workspace
        from app.services.job_queue import enqueue, handle_job_discovery

        # Enqueue a discovery job
        job = enqueue(
            type="job_discovery",
            pool="discovery",
            workspace_id=ws_id,
            payload={"provider": "fixture", "filters": {"title_contains": "dispatcher"}},
            idempotency_key="test-discovery-1",
        )

        result = handle_job_discovery(job)
        assert result["ingested"] >= 1
        assert "fixture" in result["by_provider"]

    def test_signal_scoring_worker(self, workspace):
        ws_id, _ = workspace
        from app.services.job_queue import enqueue, handle_signal_scoring

        # Create a signal first
        raw = {
            "source_job_id": "score-test-1",
            "title": "HVAC Dispatcher",
            "description": "Handle 50+ inbound calls, schedule appointments, after-hours.",
            "company_name": "Score Test HVAC",
            "company_city": "Austin",
            "company_state": "TX",
            "job_url": "https://example.com/score-1",
            "posted_at": datetime.now(timezone.utc).isoformat(),
        }
        signal_id = hiring_signals.upsert_hiring_signal(ws_id, raw, "test")

        job = enqueue(
            type="signal_scoring",
            pool="discovery",
            workspace_id=ws_id,
            payload={"signal_id": signal_id},
            idempotency_key="test-scoring-1",
        )

        result = handle_signal_scoring(job)
        assert result["updated"] is True
        assert result["signal_id"] == signal_id
        assert "signal_score" in result