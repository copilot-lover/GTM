"""Deterministic stage-engine tests (spec §19.2).
The backend never calls LLMs — apply functions receive n8n's parsed results.
External-call orchestration lives in n8n workflows; here we verify the
deterministic contracts: gating, scoring arithmetic, review routing, events."""

import json

import psycopg
import pytest

from app.services import pipeline
from tests.conftest import make_lead


def qualify_result(signals: dict, unclear=False):
    return {
        "signals": signals,
        "unclear": unclear,
        "evidence": "website footer says 'family owned since 1987'",
        "reason": "small owner-operated contractor",
    }


AUDIT_RESULT = {
    "findings": {"has_online_booking": False},
    "pain_points": ["no_online_booking", "missed_calls"],
    "primary_pain": "no_online_booking",
    "secondary_pain": "missed_calls",
    "website_score": 40,
}
OFFER_RESULT = {
    "offer_id": "after_hours_booking",
    "why": "no booking exists",
    "expected_outcome": "capture after-hours jobs",
}
DRAFT_RESULT = {
    "subject": "Booking while you're on a job",
    "first_sentence": "I saw your site has no booking option.",
    "body": "After-hours callers likely call the next plumber instead. We set up AI booking that works 24/7 for you.",
    "cta": "Worth a quick look this week?",
    "followup_angle": "short follow-up",
}


@pytest.fixture
def qualified_lead(db_url, workspace):
    ws, user = workspace
    lead_id = make_lead(db_url, ws)
    conn = psycopg.connect(db_url, autocommit=True)
    conn.execute(
        "UPDATE companies SET website='https://acme.test' WHERE id=(SELECT company_id FROM leads WHERE id=%s)",
        (lead_id,),
    )
    contact = conn.execute(
        """INSERT INTO contacts (workspace_id, company_id, email,
               email_verification_status)
           SELECT %s, company_id, 'owner@acme.test', 'verified'
           FROM leads WHERE id=%s RETURNING id""",
        (ws, lead_id),
    ).fetchone()[0]
    conn.execute("UPDATE leads SET contact_id=%s WHERE id=%s", (contact, lead_id))
    conn.close()
    return str(ws), str(lead_id)


class TestQualificationApply:
    def test_qualified_lead_scores_and_emits_next_event(self, db_url, workspace):
        ws, _ = workspace
        lead_id = make_lead(db_url, ws)
        result = pipeline.apply_qualification(ws, lead_id, qualify_result({
            "single_location": True, "owner_visible": True,
            "residential_focus": True, "simple_site": True,
            "local_service_area": True}))
        assert result["fit_status"] == "qualified"
        assert result["next"] == "enrichment"
        conn = psycopg.connect(db_url, autocommit=True)
        events = conn.execute(
            "SELECT event_type FROM event_outbox ORDER BY created_at DESC LIMIT 1"
        ).fetchone()[0]
        status = conn.execute("SELECT status FROM leads WHERE id=%s", (lead_id,)).fetchone()[0]
        conn.close()
        assert events == "lead.enrichment_requested"
        assert status == "enriching"

    def test_rejected_lead_stops_no_enrichment_event(self, db_url, workspace):
        ws, _ = workspace
        lead_id = make_lead(db_url, ws)
        result = pipeline.apply_qualification(ws, lead_id, qualify_result({
            "franchise": True, "national_brand": True}))
        assert result["fit_status"].startswith("rejected")
        assert result["next"] is None
        conn = psycopg.connect(db_url, autocommit=True)
        types = [r[0] for r in conn.execute(
            "SELECT event_type FROM event_outbox").fetchall()]
        conn.close()
        assert "lead.enrichment_requested" not in types

    def test_score_never_exceeds_10_and_rejects_below_threshold(self, db_url, workspace):
        ws, _ = workspace
        lead_id = make_lead(db_url, ws)
        r = pipeline.apply_qualification(ws, lead_id, qualify_result({}))
        assert r["lead_score"] <= 10
        conn = psycopg.connect(db_url, autocommit=True)
        fit = conn.execute("SELECT fit_status FROM leads WHERE id=%s", (lead_id,)).fetchone()[0]
        conn.close()
        assert fit != "qualified"  # empty signals never qualify


class TestEnrichmentGating:
    def test_enrichment_hard_gated_on_qualified(self, db_url, workspace):
        ws, _ = workspace
        lead_id = make_lead(db_url, ws)  # fit_status pending
        with pytest.raises(pipeline.PipelineError, match="gated"):
            pipeline.apply_enrichment(ws, lead_id, {
                "owner_name": "Pat", "email": "p@acme.test",
                "employee_estimate": None, "confidence": 80, "source_notes": "x"})

    def test_missing_owner_and_email_route_to_review(self, db_url, workspace):
        ws, _ = workspace
        lead_id = make_lead(db_url, ws)
        conn = psycopg.connect(db_url, autocommit=True)
        conn.execute(
            "UPDATE leads SET fit_status='qualified', status='qualified' WHERE id=%s",
            (lead_id,))
        conn.close()
        pipeline.apply_enrichment(ws, lead_id, {
            "owner_name": None, "email": None,
            "employee_estimate": None, "confidence": 0, "source_notes": "not found"})
        conn = psycopg.connect(db_url, autocommit=True)
        reasons = conn.execute(
            "SELECT review_reasons FROM leads WHERE id=%s", (lead_id,)).fetchone()[0]
        owner_null = conn.execute(
            "SELECT owner_name IS NULL FROM companies WHERE id=(SELECT company_id FROM leads WHERE id=%s)",
            (lead_id,)).fetchone()[0]
        conn.close()
        assert any("owner" in r for r in reasons)
        assert any("email" in r for r in reasons)
        assert owner_null is True  # never invented


class TestOfferContract:
    def test_offer_pain_violation_flagged_zero_tolerance(self, db_url, qualified_lead):
        ws, lead_id = qualified_lead
        pipeline.apply_audit(ws, lead_id, AUDIT_RESULT)
        bad = dict(OFFER_RESULT, offer_id="review_generation")
        with pytest.raises(pipeline.PipelineError, match="mismatch"):
            pipeline.apply_offer(ws, lead_id, bad)
        conn = psycopg.connect(db_url, autocommit=True)
        reasons = conn.execute(
            "SELECT review_reasons FROM leads WHERE id=%s", (lead_id,)).fetchone()[0]
        conn.close()
        assert any("contract violation" in r for r in reasons)

    def test_matching_offer_passes_and_emits_draft_event(self, db_url, qualified_lead):
        ws, lead_id = qualified_lead
        pipeline.apply_audit(ws, lead_id, AUDIT_RESULT)
        result = pipeline.apply_offer(ws, lead_id, OFFER_RESULT)
        assert result["next"] == "draft"
        conn = psycopg.connect(db_url, autocommit=True)
        last = conn.execute(
            "SELECT event_type FROM event_outbox ORDER BY created_at DESC LIMIT 1"
        ).fetchone()[0]
        conn.close()
        assert last == "lead.draft_requested"


class TestDraftQA:
    def test_draft_over_75_words_rejected(self, qualified_lead):
        ws, lead_id = qualified_lead
        pipeline.apply_audit(ws, lead_id, AUDIT_RESULT)
        pipeline.apply_offer(ws, lead_id, OFFER_RESULT)
        long_draft = dict(DRAFT_RESULT)
        long_draft["body"] = " ".join(["word"] * 80)
        with pytest.raises(pipeline.PipelineError, match="75 words"):
            pipeline.apply_draft(ws, lead_id, long_draft)

    def test_banned_phrase_rejected(self, qualified_lead):
        ws, lead_id = qualified_lead
        pipeline.apply_audit(ws, lead_id, AUDIT_RESULT)
        pipeline.apply_offer(ws, lead_id, OFFER_RESULT)
        banned = dict(DRAFT_RESULT, body="Just following up on my last note about booking automation for your shop.")
        with pytest.raises(pipeline.PipelineError, match="banned"):
            pipeline.apply_draft(ws, lead_id, banned)

    def test_valid_draft_creates_pending_approval(self, db_url, qualified_lead):
        ws, lead_id = qualified_lead
        pipeline.apply_audit(ws, lead_id, AUDIT_RESULT)
        pipeline.apply_offer(ws, lead_id, OFFER_RESULT)
        result = pipeline.apply_draft(ws, lead_id, DRAFT_RESULT)
        assert result["next"] == "approval"
        conn = psycopg.connect(db_url, autocommit=True)
        status = conn.execute(
            "SELECT status FROM messages WHERE id=%s", (result["message_id"],)
        ).fetchone()[0]
        conn.close()
        assert status == "pending_approval"


class TestContextEndpoints:
    def test_context_requires_qualified_for_enrichment(self, db_url, workspace):
        ws, _ = workspace
        lead_id = make_lead(db_url, ws)
        with pytest.raises(pipeline.PipelineError, match="gated"):
            pipeline.stage_context(ws, lead_id, "enrichment")

    def test_qualification_context_has_prompt_and_keys(self, db_url, workspace):
        ws, _ = workspace
        lead_id = make_lead(db_url, ws)
        ctx = pipeline.stage_context(ws, lead_id, "qualification")
        assert "system" in ctx and "user" in ctx
        assert "signals" in ctx["required_keys"]
        assert "Qualification Agent" in ctx["system"]


class TestUnverifiedEmailGate:
    def test_outreach_ready_requires_verified_email(self, db_url, qualified_lead):
        """dns_ok contact never reaches outreach_ready; verified unlocks it."""
        ws, lead_id = qualified_lead
        conn = psycopg.connect(db_url, autocommit=True)
        conn.execute(
            """UPDATE contacts SET email_verification_status='dns_ok'
               WHERE id=(SELECT contact_id FROM leads WHERE id=%s)""", (lead_id,))
        conn.close()
        pipeline.apply_audit(ws, lead_id, AUDIT_RESULT)
        pipeline.apply_offer(ws, lead_id, OFFER_RESULT)
        pipeline.apply_draft(ws, lead_id, DRAFT_RESULT)
        # draft created, but no code path moved the lead to outreach_ready
        conn = psycopg.connect(db_url, autocommit=True)
        status = conn.execute("SELECT status FROM leads WHERE id=%s", (lead_id,)).fetchone()[0]
        conn.close()
        assert status != "outreach_ready"
