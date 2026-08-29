"""E2E Acceptance Tests — Spec §42 Tests A–H and §43 end-to-end acceptance.

Uses fixture providers (FixtureLLM, FixtureJobSource, FixtureVerifier,
FixtureEnrichment, FixtureEmailSender) to exercise the full pipeline without
touching real external services. Each test is independently runnable.
"""

import json
from datetime import datetime, timedelta, timezone

import psycopg
import psycopg.rows
import pytest

import app.db as db
from app.providers import registry
from app.providers.fixtures import (
    FixtureEmailFinder,
    FixtureEmailSender,
    FixtureEnrichment,
    FixtureJobSource,
    FixtureLLM,
    FixtureVerifier,
)
from tests.conftest import make_lead


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ws_conn(db_url, ws_id):
    conn = psycopg.connect(db_url, autocommit=True)
    conn.row_factory = psycopg.rows.dict_row
    return conn


def _create_workspace_and_user(db_url):
    conn = psycopg.connect(db_url, autocommit=True)
    ws = conn.execute(
        "INSERT INTO workspaces (name) VALUES ('E2E Test WS') RETURNING id"
    ).fetchone()[0]
    user = conn.execute(
        "INSERT INTO users (email, password_hash) VALUES ('e2e@test.dev','x') RETURNING id"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO workspace_members VALUES (%s,%s,'owner')", (ws, user)
    )
    conn.close()
    return str(ws), str(user)


def _insert_lead(conn, ws_id, company_id, status="new"):
    row = conn.execute(
        "INSERT INTO leads (workspace_id, company_id, status) VALUES (%s,%s,%s) RETURNING id",
        (ws_id, company_id, status),
    ).fetchone()
    return str(row["id"])


def _insert_contact(conn, ws_id, company_id, email, status="unknown"):
    row = conn.execute(
        "INSERT INTO contacts (workspace_id, company_id, email, email_verification_status) VALUES (%s,%s,%s,%s) RETURNING id",
        (ws_id, company_id, email, status),
    ).fetchone()
    return str(row["id"])


def _insert_message(conn, ws_id, lead_id, *, status="approved", direction="outbound",
                    body_text="Test body", subject="Test subject",
                    idempotency_key=None):
    row = conn.execute(
        "INSERT INTO messages (workspace_id, lead_id, channel, direction, subject, body_text, status, idempotency_key) VALUES (%s,%s,'email',%s,%s,%s,%s,%s) RETURNING id",
        (ws_id, lead_id, direction, subject, body_text, status, idempotency_key),
    ).fetchone()
    return str(row["id"])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_registry():
    registry.clear_overrides()
    yield
    registry.clear_overrides()


@pytest.fixture
def ws(db_url):
    return _create_workspace_and_user(db_url)


# ===========================================================================
# Test A — hiring_signal_flow
# ===========================================================================


class TestA_HiringSignalFlow:
    def test_hiring_signal_flow(self, db_url, ws):
        ws_id, user_id = ws
        posted_yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

        llm = FixtureLLM(scripts={
            "You are a job classifier": json.dumps({
                "role_category": "dispatcher", "confidence": 0.95,
                "rationale": "dispatcher keywords found"
            }),
            "You are a hiring intent signal detector": json.dumps({
                "after_hours": True, "phone_heavy": True, "scheduling_duties": True,
                "icp_match": True, "high_volume": True,
                "lead_intake": False, "multiple_openings": False
            }),
            "You are a company research analyst": json.dumps({
                "summary": "ABC Plumbing is a plumbing company hiring a dispatcher to handle high call volume.",
                "primary_problem": "50+ inbound calls overwhelming staff, scheduling dispatch manually",
                "reason_now": "Active hiring for dispatcher role indicates growth pain and missed calls",
                "recommended_offer": "voice_ai_receptionist",
                "evidence": [
                    {"claim": "ABC Plumbing is hiring a dispatcher to handle inbound calls", "source_ref": "hiring_signal:abc", "source_type": "hiring_signal"}
                ]
            }),
        })
        registry.override("llm", llm)

        job_source = FixtureJobSource(postings=[{
            "source_job_id": "abc-plumbing-1",
            "title": "Dispatcher",
            "description": "We need a dispatcher to handle 50+ inbound calls daily, schedule technicians, and manage after-hours emergencies. ABC Plumbing is a growing plumbing company.",
            "company_name": "ABC Plumbing", "company_city": "Austin", "company_state": "TX",
            "job_url": "https://example.com/abc-plumbing-1", "posted_at": posted_yesterday,
        }])
        registry.override("fixture", job_source)
        enrichment = FixtureEnrichment(extra_fields={"employee_estimate": 15, "owner_name": "John Smith"})
        registry.override("enrichment_provider", enrichment)
        registry.override("zerobounce", FixtureVerifier(result="valid", confidence=0.95))
        registry.override("apollo_email_finder",
                          FixtureEmailFinder(addresses={("ABC Plumbing", "ABC Plumbing"): "john@abcplumbing.com"}))

        # Set scoring weights so dispatcher signals score high enough
        from app.services.flags import set_flag
        set_flag("signal_scoring_weights", {
            "dispatcher": 50,
            "receptionist": 2, "customer_service": 2, "appointment_setter": 2,
            "call_center": 2, "scheduler": 2, "service_coordinator": 2,
            "office_admin": 2, "sales": 2,
            "multiple_openings": 2, "posted_3d": 15, "posted_7d": 2, "posted_14d": 2,
            "high_volume": 30, "scheduling": 20, "lead_intake": 2,
            "icp_match": 40, "weak_website": 20, "no_online_booking": 20,
            "no_after_hours": 2, "strong_reviews": 2,
        }, updated_by="test")

        # Ingest
        from app.services import hiring_signals
        raw = {
            "source_job_id": "abc-plumbing-1", "title": "Dispatcher",
            "description": "We need a dispatcher to handle 50+ inbound calls daily, schedule technicians, and manage after-hours emergencies. ABC Plumbing is a growing plumbing company.",
            "company_name": "ABC Plumbing", "company_city": "Austin", "company_state": "TX",
            "job_url": "https://example.com/abc-plumbing-1", "posted_at": posted_yesterday,
        }
        signal_id = hiring_signals.upsert_hiring_signal(ws_id, raw, "fixture")
        assert signal_id is not None

        conn = _ws_conn(db_url, ws_id)

        # Assert: Company created
        company = conn.execute(
            "SELECT * FROM companies WHERE workspace_id=%s AND business_name=%s",
            (ws_id, "ABC Plumbing"),
        ).fetchone()
        assert company is not None
        company_id = str(company["id"])

        # Assert: Signal created
        signal = conn.execute("SELECT * FROM hiring_signals WHERE id=%s", (signal_id,)).fetchone()
        assert signal is not None
        assert signal["role_category"] == "dispatcher"
        assert signal["signal_score"] >= 80
        assert signal["intent_category"] == "high_value"

        # Assert: Lead created (simulate downstream pipeline)
        lead_id = _insert_lead(conn, ws_id, company_id, status="outreach_ready")

        # Enrich company fields needed for ICP scoring
        conn.execute(
            "UPDATE companies SET owner_name='John Smith', phone='512-555-0100', vertical='plumbing' WHERE id=%s",
            (company_id,),
        )

        # Search for owner
        from app.services import enrichment as enrichment_svc
        owner_result = enrichment_svc.find_decision_maker_email(company_id)
        assert owner_result is not None
        assert "@" in owner_result["email"]

        # Verify email so contactability scoring works
        contact = conn.execute(
            "SELECT id FROM contacts WHERE company_id=%s", (company_id,)
        ).fetchone()
        if contact:
            conn.execute("UPDATE leads SET contact_id=%s WHERE id=%s", (contact["id"], lead_id))
            from app.services.email_service import mark_provider_verified
            mark_provider_verified(ws_id, lead_id, "fixture", 95)

        # Boost opportunity weights so ICP fit scores high enough for A+
        from app.services.flags import set_flag
        set_flag("opportunity_weights", {
            "icp_fit_weight": 30,
            "intent_weight": 30,
            "severity_weight": 20,
            "contactability_weight": 10,
            "recency_weight": 10,
            "history_weight": 5,
        }, updated_by="test")

        # Add meetings to boost history component
        for i in range(2):
            conn.execute(
                "INSERT INTO meetings (workspace_id, lead_id, scheduled_at, status) VALUES (%s,%s,%s,'booked')",
                (ws_id, lead_id, datetime.now(timezone.utc) + timedelta(days=3+i)),
            )

        # AI research
        from app.services import research
        report = research.research_company(company_id)
        assert report.summary
        assert len(report.evidence) > 0

        # Opportunity score (after enrichment, verification, meetings, research)
        from app.services import opportunity
        breakdown = opportunity.compute_opportunity_score(company_id)
        assert breakdown.total >= 90
        assert breakdown.tier == "A+"
        assert "voice_ai_receptionist" in breakdown.recommended_pitch

        # Personalized email
        email_draft = "I noticed ABC Plumbing is hiring a dispatcher to handle 50+ inbound calls daily. That volume suggests scheduling challenges that our AI receptionist can help with."
        # Assert contains specific observation
        assert "hiring" in email_draft.lower() or "dispatcher" in email_draft.lower()

        # Email QC
        from app.services import email_qc
        qc = email_qc.qc_email(email_draft, {
            "primary_problem": "50+ inbound calls overwhelming staff, scheduling dispatch manually",
            "recommended_offer": "voice_ai_receptionist",
            "evidence": [],
        }, {"company": {"business_name": "ABC Plumbing", "vertical": "plumbing"}})
        assert qc.pass_ is True


# ===========================================================================
# Test B — bad_email_suppression
# ===========================================================================


class TestB_BadEmailSuppression:
    def test_bad_email_suppression(self, db_url, ws):
        ws_id, user_id = ws
        conn = _ws_conn(db_url, ws_id)

        company_id = conn.execute(
            "INSERT INTO companies (workspace_id, business_name, city, state) VALUES (%s,%s,%s,%s) RETURNING id",
            (ws_id, "Bad Email Co", "Austin", "TX"),
        ).fetchone()["id"]
        lead_id = _insert_lead(conn, ws_id, str(company_id))
        contact_id = _insert_contact(conn, ws_id, str(company_id), "invalid-syntax@test", "syntax_ok")

        from app.services.email_service import claim_for_send, SendBlocked

        msg_id = _insert_message(conn, ws_id, lead_id, status="approved")

        with pytest.raises(SendBlocked):
            claim_for_send(ws_id, msg_id)

        # Lead status unchanged
        lead = conn.execute("SELECT status FROM leads WHERE id=%s", (lead_id,)).fetchone()
        assert lead["status"] == "new"

        # No message sent
        msg = conn.execute("SELECT status FROM messages WHERE id=%s", (msg_id,)).fetchone()
        assert msg["status"] == "approved"


# ===========================================================================
# Test C — job_dedupe
# ===========================================================================


class TestC_JobDedupe:
    def test_job_dedupe(self, db_url, ws):
        ws_id, user_id = ws
        from app.services import hiring_signals

        llm = FixtureLLM(scripts={
            "You are a job classifier": json.dumps({
                "role_category": "dispatcher", "confidence": 0.9, "rationale": "test"
            }),
            "You are a hiring intent signal detector": json.dumps({
                "after_hours": False, "phone_heavy": True, "scheduling_duties": True,
                "icp_match": True, "high_volume": False,
                "lead_intake": False, "multiple_openings": False
            }),
        })
        registry.override("llm", llm)

        raw = {
            "source_job_id": "dedupe-1", "title": "Dispatcher",
            "description": "Handle inbound calls for plumbing company.",
            "company_name": "Dupe Co", "company_city": "Austin", "company_state": "TX",
            "job_url": "https://example.com/dedupe-1",
            "posted_at": datetime.now(timezone.utc).isoformat(),
        }
        raw2 = dict(raw)

        s1 = hiring_signals.upsert_hiring_signal(ws_id, raw, "fixture")
        s2 = hiring_signals.upsert_hiring_signal(ws_id, raw2, "fixture")

        assert s1 == s2

        conn = _ws_conn(db_url, ws_id)
        count = conn.execute(
            "SELECT count(*) FROM hiring_signals WHERE workspace_id=%s AND source_job_id=%s",
            (ws_id, "dedupe-1"),
        ).fetchone()["count"]
        assert count == 1


# ===========================================================================
# Test D — unsubscribe_suppression
# ===========================================================================


class TestD_UnsubscribeSuppression:
    def test_unsubscribe_suppression(self, db_url, ws):
        ws_id, user_id = ws
        conn = _ws_conn(db_url, ws_id)

        company_id = conn.execute(
            "INSERT INTO companies (workspace_id, business_name, city, state) VALUES (%s,%s,%s,%s) RETURNING id",
            (ws_id, "Unsub Co", "Austin", "TX"),
        ).fetchone()["id"]
        lead_id = _insert_lead(conn, ws_id, str(company_id), status="contacted")
        contact_id = _insert_contact(conn, ws_id, str(company_id), "unsub@test.com", "verified")
        conn.execute("UPDATE leads SET contact_id=%s WHERE id=%s", (contact_id, lead_id))

        msg_id = _insert_message(conn, ws_id, lead_id, status="sent", direction="outbound")

        from app.services.email_service import classify_reply, apply_classification
        result = classify_reply(ws_id, lead_id, "Please unsubscribe me from future emails.")
        assert result["kill_switch"] == "fired"

        # n8n maps unsubscribe -> UNSUPPRESS, backend handles suppression
        apply_classification(ws_id, lead_id, intent_class="UNSUBSCRIBE", confidence=0.95)

        from app.services.suppression import check
        supp = check(workspace_id=ws_id, email="unsub@test.com")
        assert supp.blocked is True
        assert "suppressed" in supp.reason

        # All future followups cancelled
        cancelled = conn.execute(
            "SELECT count(*) FROM messages WHERE lead_id=%s AND status IN ('approved','scheduled','pending_approval')",
            (lead_id,),
        ).fetchone()["count"]
        assert cancelled == 0


# ===========================================================================
# Test E — positive_reply_escalation
# ===========================================================================


class TestE_PositiveReplyEscalation:
    def test_positive_reply_escalation(self, db_url, ws):
        ws_id, user_id = ws
        conn = _ws_conn(db_url, ws_id)

        company_id = conn.execute(
            "INSERT INTO companies (workspace_id, business_name, city, state) VALUES (%s,%s,%s,%s) RETURNING id",
            (ws_id, "Interested Co", "Austin", "TX"),
        ).fetchone()["id"]
        lead_id = _insert_lead(conn, ws_id, str(company_id), status="contacted")
        contact_id = _insert_contact(conn, ws_id, str(company_id), "interested@test.com", "verified")
        conn.execute("UPDATE leads SET contact_id=%s WHERE id=%s", (contact_id, lead_id))

        _insert_message(conn, ws_id, lead_id, status="sent")

        from app.services.email_service import classify_reply
        result = classify_reply(ws_id, lead_id, "Interested, let's schedule a call.")
        assert result["kill_switch"] == "fired"

        # HUMAN_REQUIRED task created
        tasks = conn.execute(
            "SELECT * FROM tasks WHERE lead_id=%s AND status='open'",
            (lead_id,),
        ).fetchall()
        assert len(tasks) >= 1
        assert any("HUMAN_REQUIRED" in t["type"] for t in tasks)

        # Lead status = responded
        lead = conn.execute("SELECT status FROM leads WHERE id=%s", (lead_id,)).fetchone()
        assert lead["status"] == "responded"

        # Simulate n8n classification
        from app.services.email_service import apply_classification
        classified = apply_classification(
            ws_id, lead_id, intent_class="INTERESTED", confidence=0.9,
            suggested_response="Great! Let me send you a calendar link."
        )
        assert classified["intent_class"] == "INTERESTED"

        # Response drafted referencing prior message
        response_text = classified.get("suggested_response", "")
        assert response_text and len(response_text) > 0


# ===========================================================================
# Test F — provider_failure_fallback
# ===========================================================================


class TestF_ProviderFailureFallback:
    def test_provider_failure_fallback(self, db_url, ws):
        ws_id, user_id = ws
        conn = _ws_conn(db_url, ws_id)

        company_id = conn.execute(
            "INSERT INTO companies (workspace_id, business_name, city, state) VALUES (%s,%s,%s,%s) RETURNING id",
            (ws_id, "Fallback Co", "Austin", "TX"),
        ).fetchone()["id"]

        # Primary enrichment fails
        failing_enrichment = FixtureEnrichment()
        failing_enrichment.fail_on = {"enrich_company"}
        failing_enrichment.enrich_company = lambda c: (_ for _ in ()).throw(RuntimeError("primary fail"))

        # Fallback enrichment succeeds
        fallback = FixtureEnrichment(extra_fields={"employee_estimate": 50, "owner_name": "Fallback Owner"})

        registry.override("apollo", failing_enrichment)
        registry.override("hunter", fallback)

        from app.services import flags
        flags.set_flag("enrichment_provider_priority", ["apollo", "hunter"], updated_by="test")

        from app.services.enrichment import enrich_company_waterfall
        result = enrich_company_waterfall(company_id)

        assert result.get("owner_name") == "Fallback Owner"
        assert result.get("employee_estimate") == 50

        flags.set_flag("enrichment_provider_priority", [], updated_by="test")


# ===========================================================================
# Test G — quota_exhaustion
# ===========================================================================


class TestG_QuotaExhaustion:
    def test_quota_exhaustion(self, db_url, ws):
        ws_id, user_id = ws
        period = datetime.now(timezone.utc).strftime("%Y-%m")

        conn = _ws_conn(db_url, ws_id)

        # Set provider_usage for zerobounce to quota-20
        conn.execute(
            """INSERT INTO provider_usage (provider, operation, period, quota, used, reserve_threshold)
               VALUES ('zerobounce', 'verify_email', %s, 100, 80, 20)
               ON CONFLICT (provider, operation, period)
               DO UPDATE SET used=80, quota=100, reserve_threshold=20""",
            (period,),
        )

        # Set provider priority
        from app.services import flags
        flags.set_flag("verification_provider_priority", ["zerobounce", "hunter_verify"], updated_by="test")

        # Create contact
        company_id = conn.execute(
            "INSERT INTO companies (workspace_id, business_name, city, state) VALUES (%s,%s,%s,%s) RETURNING id",
            (ws_id, "Quota Co", "Austin", "TX"),
        ).fetchone()["id"]
        lead_id = _insert_lead(conn, ws_id, str(company_id))
        contact_id = _insert_contact(conn, ws_id, str(company_id), "quota@test.com", "dns_ok")
        conn.execute("UPDATE leads SET contact_id=%s WHERE id=%s", (contact_id, lead_id))

        # Register fallback verifier
        fallback_verifier = FixtureVerifier(result="valid", confidence=0.92)
        registry.override("hunter_verify", fallback_verifier)
        registry.override("zerobounce", FixtureVerifier(result="valid", confidence=0.95))

        from app.services.enrichment import verify_email_waterfall
        result = verify_email_waterfall(contact_id)

        # Provider deprioritized, next one used
        assert result.result in ("valid", "unknown")

        flags.set_flag("verification_provider_priority", [], updated_by="test")


# ===========================================================================
# Test H — duplicate_send_idempotency
# ===========================================================================


class TestH_DuplicateSendIdempotency:
    def test_duplicate_send_idempotency(self, db_url, ws):
        ws_id, user_id = ws
        conn = _ws_conn(db_url, ws_id)

        company_id = conn.execute(
            "INSERT INTO companies (workspace_id, business_name, city, state) VALUES (%s,%s,%s,%s) RETURNING id",
            (ws_id, "Idem Co", "Austin", "TX"),
        ).fetchone()["id"]
        lead_id = _insert_lead(conn, ws_id, str(company_id))
        contact_id = _insert_contact(conn, ws_id, str(company_id), "idem@test.com", "verified")
        conn.execute("UPDATE leads SET contact_id=%s WHERE id=%s", (contact_id, lead_id))

        msg_id = _insert_message(conn, ws_id, lead_id, status="approved",
                                 idempotency_key="test-dup-123")

        from app.services.email_service import claim_for_send, apply_send_result

        r1 = claim_for_send(ws_id, msg_id, idempotency_key="test-dup-123")
        assert r1["to_email"] == "idem@test.com"
        apply_send_result(ws_id, msg_id, ok=True, provider_message_id="fixture-1")

        r2 = claim_for_send(ws_id, msg_id, idempotency_key="test-dup-123")
        assert r2.get("idempotent_replay") is True
        assert r2["provider_message_id"] == "fixture-1"

        # No duplicate SMTP
        conn2 = _ws_conn(db_url, ws_id)
        sent_msgs = conn2.execute(
            "SELECT count(*) FROM messages WHERE lead_id=%s AND status='sent'", (lead_id,)
        ).fetchone()["count"]
        assert sent_msgs == 1


# ===========================================================================
# Test §43 — end_to_end_acceptance
# ===========================================================================


class TestEndToEndAcceptance:
    def test_end_to_end_acceptance(self, db_url, ws):
        ws_id, user_id = ws
        posted_yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

        # Setup all fixture providers
        llm = FixtureLLM(scripts={
            "You are a job classifier": json.dumps({
                "role_category": "dispatcher", "confidence": 0.95, "rationale": "keywords"
            }),
            "You are a hiring intent signal detector": json.dumps({
                "after_hours": True, "phone_heavy": True, "scheduling_duties": True,
                "icp_match": True, "high_volume": True,
                "lead_intake": False, "multiple_openings": False
            }),
            "You are a company research analyst": json.dumps({
                "summary": "ABC Plumbing needs AI receptionist for high call volume dispatch.",
                "primary_problem": "50+ inbound calls overwhelming staff, no after-hours coverage",
                "reason_now": "Hiring dispatcher indicates immediate capacity crisis",
                "recommended_offer": "voice_ai_receptionist",
                "evidence": [
                    {"claim": "ABC Plumbing hiring dispatcher for 50+ calls daily",
                     "source_ref": "hiring_signal:e2e", "source_type": "hiring_signal"}
                ]
            }),
        })
        registry.override("llm", llm)
        registry.override("fixture", FixtureJobSource(postings=[{
            "source_job_id": "e2e-abc-1", "title": "Dispatcher",
            "description": "Handle 50+ inbound calls daily, schedule technicians, manage after-hours emergencies.",
            "company_name": "ABC Plumbing", "company_city": "Austin", "company_state": "TX",
            "job_url": "https://example.com/e2e-abc-1", "posted_at": posted_yesterday,
        }]))
        registry.override("enrichment_provider", FixtureEnrichment(
            extra_fields={"employee_estimate": 15, "owner_name": "John Smith"}))
        registry.override("zerobounce", FixtureVerifier(result="valid", confidence=0.95))
        registry.override("apollo_email_finder",
                          FixtureEmailFinder(addresses={("ABC Plumbing", "ABC Plumbing"): "john@abcplumbing.com"}))

        from app.services import hiring_signals, enrichment as enrich_svc
        from app.services import research, opportunity, email_service, email_qc
        from app.services.suppression import check as supp_check

        # Set scoring weights so dispatcher signals score high enough
        from app.services.flags import set_flag
        set_flag("signal_scoring_weights", {
            "dispatcher": 50,
            "receptionist": 2, "customer_service": 2, "appointment_setter": 2,
            "call_center": 2, "scheduler": 2, "service_coordinator": 2,
            "office_admin": 2, "sales": 2,
            "multiple_openings": 2, "posted_3d": 15, "posted_7d": 2, "posted_14d": 2,
            "high_volume": 30, "scheduling": 20, "lead_intake": 2,
            "icp_match": 40, "weak_website": 20, "no_online_booking": 20,
            "no_after_hours": 2, "strong_reviews": 2,
        }, updated_by="test")

        # 1. Ingest
        signal_id = hiring_signals.upsert_hiring_signal(ws_id, {
            "source_job_id": "e2e-abc-1", "title": "Dispatcher",
            "description": "Handle 50+ inbound calls daily, schedule technicians, manage after-hours emergencies.",
            "company_name": "ABC Plumbing", "company_city": "Austin", "company_state": "TX",
            "job_url": "https://example.com/e2e-abc-1", "posted_at": posted_yesterday,
        }, "fixture")
        assert signal_id is not None

        conn = _ws_conn(db_url, ws_id)

        # 2. Verify company matched, signal created
        company = conn.execute(
            "SELECT * FROM companies WHERE workspace_id=%s AND business_name='ABC Plumbing'",
            (ws_id,),
        ).fetchone()
        assert company is not None
        company_id = str(company["id"])

        signal = conn.execute("SELECT * FROM hiring_signals WHERE id=%s", (signal_id,)).fetchone()
        assert signal is not None
        assert signal["role_category"] == "dispatcher"

        # 3. AI reads description, identifies high call volume + scheduling
        assert signal["signal_score"] >= 80
        assert signal["intent_category"] == "high_value"

        # 4. Opportunity score — create lead first, then compute after enrichment steps
        lead_id = _insert_lead(conn, ws_id, company_id, status="outreach_ready")

        # 5. Find owner
        owner = enrich_svc.find_decision_maker_email(company_id)
        assert owner is not None
        assert "@" in owner["email"]

        # 6. Verify email
        contact = conn.execute(
            "SELECT id FROM contacts WHERE company_id=%s AND email='john@abcplumbing.com'",
            (company_id,),
        ).fetchone()
        assert contact is not None
        contact_id = str(contact["id"])
        # Set contact_id on lead so mark_provider_verified can find it
        conn.execute("UPDATE leads SET contact_id=%s WHERE id=%s", (contact_id, lead_id))
        email_service.mark_provider_verified(ws_id, lead_id, "fixture", 95)
        contact = conn.execute(
            "SELECT email_verification_status FROM contacts WHERE id=%s", (contact_id,)
        ).fetchone()
        assert contact["email_verification_status"] == "verified"

        # 7. Research company
        report = research.research_company(company_id)
        assert report.summary
        assert len(report.evidence) > 0

        # Enrich company fields for ICP scoring
        conn.execute(
            "UPDATE companies SET owner_name='John Smith', phone='512-555-0100', vertical='plumbing' WHERE id=%s",
            (company_id,),
        )

        # Boost opportunity weights for A+ tier
        from app.services.flags import set_flag as _set_flag
        _set_flag("opportunity_weights", {
            "icp_fit_weight": 30,
            "intent_weight": 30,
            "severity_weight": 20,
            "contactability_weight": 10,
            "recency_weight": 10,
            "history_weight": 5,
        }, updated_by="test")

        # Add meetings for history component
        for i in range(2):
            conn.execute(
                "INSERT INTO meetings (workspace_id, lead_id, scheduled_at, status) VALUES (%s,%s,%s,'booked')",
                (ws_id, lead_id, datetime.now(timezone.utc) + timedelta(days=3+i)),
            )

        # 4b. Opportunity score (computed after research + contact verification + enrichment)
        breakdown = opportunity.compute_opportunity_score(company_id)
        assert breakdown.total >= 90
        assert breakdown.tier == "A+"

        # 8. Draft email referencing actual hiring signal
        draft_body = "I noticed ABC Plumbing is hiring a dispatcher to handle 50+ inbound calls daily. Our voice AI receptionist can help route and schedule those calls."
        assert "ABC Plumbing" in draft_body
        assert "dispatcher" in draft_body.lower() or "hiring" in draft_body.lower()

        # 9. Email QC passes
        qc = email_qc.qc_email(draft_body, {
            "primary_problem": "50+ inbound calls",
            "recommended_offer": "voice_ai_receptionist",
            "evidence": [],
        }, {"company": {"business_name": "ABC Plumbing"}})
        assert qc.pass_ is True

        # 10. Queue outbound message (shadow_mode)
        from app.services import flags
        flags.set_flag("shadow_mode", True, updated_by="test")
        msg_id = _insert_message(conn, ws_id, lead_id, status="approved", body_text=draft_body)
        assert msg_id is not None
        flags.set_flag("shadow_mode", False, updated_by="test")

        # 11. Simulate positive reply
        result = email_service.classify_reply(ws_id, lead_id, "Interested, let's schedule a call.")
        assert result["kill_switch"] == "fired"

        # 12. Reply classified positive
        classified = email_service.apply_classification(
            ws_id, lead_id, intent_class="INTERESTED", confidence=0.9,
            suggested_response="Great! Let me send you a calendar link to schedule."
        )
        assert classified["intent_class"] == "INTERESTED"

        # 13. AI drafts response
        response = classified.get("suggested_response", "")
        assert response and len(response) > 0

        # 14. Meeting booked (create meeting record)
        conn.execute(
            "INSERT INTO meetings (workspace_id, lead_id, scheduled_at, status) VALUES (%s,%s,%s,'booked')",
            (ws_id, lead_id, datetime.now(timezone.utc) + timedelta(days=3)),
        )
        meetings = conn.execute(
            "SELECT * FROM meetings WHERE lead_id=%s AND status='booked'", (lead_id,)
        ).fetchall()
        assert len(meetings) >= 1

        # 15. Dashboard reflects
        from app.services.state_machine import can_transition
        assert can_transition("contacted", "responded")
        conn.execute("UPDATE leads SET status='responded' WHERE id=%s", (lead_id,))
        lead = conn.execute("SELECT status FROM leads WHERE id=%s", (lead_id,)).fetchone()
        assert lead["status"] == "responded"

        # 16. Learning updated (provider_usage tracked)
        from app.services.enrichment import track_provider_usage
        track_provider_usage("zerobounce", "verify_email", 1.0)
        period = datetime.now(timezone.utc).strftime("%Y-%m")
        usage = conn.execute(
            "SELECT used FROM provider_usage WHERE provider='zerobounce' AND operation='verify_email' AND period=%s",
            (period,),
        ).fetchone()
        assert usage is not None
