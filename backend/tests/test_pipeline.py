"""Pipeline stage integration tests (spec §19.2) with monkeypatched LLM so
deterministic behavior is verified without external API keys."""

import json

import psycopg
import pytest

from app.services import pipeline
from tests.conftest import make_lead


def patch_llm(monkeypatch, responses: dict):
    """Replace llm.structured_complete with canned responses keyed by agent name."""
    def fake(agent_name: str, **kwargs):
        if agent_name not in responses:
            raise AssertionError(f"unexpected LLM call to {agent_name}")
        r = responses[agent_name]
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(pipeline.llm, "structured_complete", fake)


def qualify_response(signals: dict, unclear=False):
    return {
        "signals": signals,
        "unclear": unclear,
        "evidence": "website footer says 'family owned since 1987'",
        "reason": "small owner-operated contractor",
    }


AUDIT_RESPONSE = {
    "findings": {"has_online_booking": False},
    "pain_points": ["no_online_booking", "missed_calls"],
    "primary_pain": "no_online_booking",
    "secondary_pain": "missed_calls",
    "website_score": 40,
}
OFFER_RESPONSE = {
    "offer_id": "after_hours_booking",
    "why": "no booking exists",
    "expected_outcome": "capture after-hours jobs",
}
PERSONALIZE_RESPONSE = {
    "subject": "Booking while you're on a job",
    "first_sentence": "Your site has no online booking option.",
    "body": "After-hours callers likely go to the next plumber. We install an AI receptionist that books jobs 24/7.",
    "cta": "Worth a 10-minute look this week?",
    "followup_angle": "short follow-up",
}


@pytest.fixture
def qualified_env(db_url, workspace, monkeypatch):
    ws, user = workspace
    lead_id = make_lead(db_url, ws)
    conn = psycopg.connect(db_url, autocommit=True)
    conn.execute("UPDATE companies SET website='https://acme.test' WHERE id=(SELECT company_id FROM leads WHERE id=%s)", (lead_id,))
    contact = conn.execute(
        """INSERT INTO contacts (workspace_id, company_id, email,
               email_verification_status)
           SELECT %s, company_id, 'owner@acme.test', 'verified'
           FROM leads WHERE id=%s RETURNING id""",
        (ws, lead_id),
    ).fetchone()[0]
    conn.execute("UPDATE leads SET contact_id=%s WHERE id=%s", (contact, lead_id))
    # scrape fetch used by enrich/audit stages
    class FakeResponse:
        status, reason, body = 200, "OK", "<html>plumbing services</html>"
    monkeypatch.setattr(
        "app.services.scraping.scrape",
        lambda url, stealth=False: FakeResponse(),
    )
    conn.close()
    return str(ws), str(lead_id)


class TestPipelineGating:
    def test_rejected_lead_never_reaches_enrichment(self, db_url, workspace, monkeypatch):
        """Spec §19.2: no enrichment/audit/personalization for rejected lead."""
        ws, user = workspace
        lead_id = make_lead(db_url, ws)

        called = {"enrich": False}

        def spy_enrich(workspace_id, lead_id):
            called["enrich"] = True
            return {}

        patch_llm(monkeypatch, {
            "qualification_agent": qualify_response({"franchise": True}),
        })
        result = pipeline.run_pipeline(ws, lead_id)
        assert result["stages"].get("stage_qualify", {}).get("fit_status") in (
            "rejected_too_large", "rejected_not_relevant")
        assert "stage_enrich" not in result["stages"]
        assert not called["enrich"]
        conn = psycopg.connect(db_url, autocommit=True)
        runs = conn.execute(
            "SELECT count(*) FROM agent_runs WHERE workspace_id=%s", (ws,)
        ).fetchone()[0]
        assert runs == 0
        conn.close()

    def test_offer_pain_contract_violation_raises(self, db_url, qualified_env, monkeypatch):
        """Spec §19.2: pain-match violation raises an error — 0 tolerance."""
        ws, lead_id = qualified_env
        assert db_url
        bad_offer = dict(OFFER_RESPONSE, offer_id="review_generation")
        patch_llm(monkeypatch, {
            "qualification_agent": qualify_response({
                "single_location": True, "owner_visible": True,
                "residential_focus": True, "simple_site": True,
                "local_service_area": True}),
            "enrichment_agent": {
                "owner_name": "Pat", "email": None,
                "employee_estimate": None, "confidence": 80,
                "source_notes": "about page"},
            "website_audit_agent": AUDIT_RESPONSE,
            "offer_selection_agent": bad_offer,
        })
        result = pipeline.run_pipeline(ws, lead_id)
        # fail-closed: stage errors are contained, pipeline stops at offer stage
        assert result["stopped_at"] == "stage_offer"
        conn = psycopg.connect(db_url, autocommit=True)
        reasons = conn.execute(
            "SELECT review_reasons FROM leads WHERE id=%s", (lead_id,)
        ).fetchone()[0]
        conn.close()
        assert any("contract violation" in r for r in reasons)

    def test_missing_owner_and_email_route_to_review(self, db_url, workspace, monkeypatch):
        ws, user = workspace
        lead_id = make_lead(db_url, ws)
        conn = psycopg.connect(db_url, autocommit=True)
        conn.execute("UPDATE companies SET website='https://x.test' WHERE id=(SELECT company_id FROM leads WHERE id=%s)", (lead_id,))
        conn.execute("UPDATE leads SET fit_status='qualified', status='qualified' WHERE id=%s", (lead_id,))
        conn.close()

        class FakeResponse:
            status, reason, body = 200, "OK", "<html>plumbing</html>"
        monkeypatch.setattr(
            "app.services.scraping.scrape",
            lambda url, stealth=False: FakeResponse(),
        )
        patch_llm(monkeypatch, {
            "enrichment_agent": {
                "owner_name": None, "email": None,
                "employee_estimate": None, "confidence": 0,
                "source_notes": "not found anywhere"},
        })
        pipeline.stage_enrich(ws, lead_id)
        conn = psycopg.connect(db_url, autocommit=True)
        reasons = conn.execute(
            "SELECT review_reasons FROM leads WHERE id=%s", (lead_id,)
        ).fetchone()[0]
        score = conn.execute(
            "SELECT owner_name IS NULL FROM companies WHERE id=(SELECT company_id FROM leads WHERE id=%s)",
            (lead_id,),
        ).fetchone()[0]
        conn.close()
        reasons_list = reasons
        assert any("owner" in r for r in reasons_list)
        assert any("email" in r for r in reasons_list)
        assert score is True  # never invented a name


class TestFailClosed:
    def test_no_llm_config_routes_to_review_not_invention(self, db_url, workspace, monkeypatch):
        ws, user = workspace
        lead_id = make_lead(db_url, ws)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        import app.config as config
        config.get_settings.cache_clear()
        try:
            result = pipeline.run_pipeline(str(ws), str(lead_id))
        finally:
            config.get_settings.cache_clear()
        assert result["stopped_at"] == "stage_qualify"
        conn = psycopg.connect(db_url, autocommit=True)
        row = conn.execute(
            "SELECT review_reasons, evidence FROM leads WHERE id=%s", (lead_id,)
        ).fetchone()
        conn.close()
        assert any("blocked" in r for r in row[0])
        assert row[1].get("icp_signals") is None  # no fabricated scoring evidence
