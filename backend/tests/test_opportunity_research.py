"""Tests for WS-D: Opportunity Engine & Research."""

import json
import pytest

from app.providers.fixtures import FixtureLLM
from app.providers import registry
from app.services import website_intel, research, opportunity, email_qc, scoring
from tests.conftest import make_lead


@pytest.fixture
def setup_company(db_url, workspace):
    """Create a test company with hiring signals and website."""
    workspace_id, user_id = workspace
    import psycopg
    conn = psycopg.connect(db_url, autocommit=True)
    conn.row_factory = psycopg.rows.dict_row

    company = conn.execute(
        """INSERT INTO companies (workspace_id, business_name, website, city, state,
               vertical, employee_estimate, owner_name, phone, google_rating, review_count,
               tech_signals)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           RETURNING id""",
        (
            workspace_id, "Acme HVAC", "https://acmehvac.com", "Greensboro", "NC",
            "hvac", 12, "John Owner", "+13365550000", 4.7, 42,
            json.dumps({"servicetitan": True, "hubspot": True, "google_analytics": True}),
        ),
    ).fetchone()
    company_id = str(company["id"])

    # Add hiring signal
    conn.execute(
        """INSERT INTO hiring_signals (workspace_id, company_id, source, source_job_id,
               title, description, role_category, intent_category, pain_hypothesis,
               orbit_product_fit, confidence, signal_score, freshness_multiplier,
               expires_at, status, posted_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            workspace_id, company_id, "indeed", "job-123",
            "HVAC Dispatcher", "We need a dispatcher to handle high volume inbound calls and schedule appointments. After hours on-call required.",
            "dispatcher", "high_value",
            "High inbound call volume overwhelming staff. After-hours calls going unanswered. Manual scheduling consuming reception time.",
            "ai_receptionist, appointment_scheduling, after_hours_booking",
            0.9, 85, 1.0,
            "2099-01-01", "active", "2024-01-15",
        ),
    )

    # Add job posting
    conn.execute(
        """INSERT INTO job_postings (workspace_id, company_id, source, source_url,
               external_job_id, title, description_raw, location, posted_at,
               intent_score, intent_category, relevant_responsibilities,
               qualification_rationale, recommended_offer, confidence, status)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            workspace_id, company_id, "indeed", "https://indeed.com/job-123",
            "job-123", "HVAC Dispatcher", "Handle 50+ inbound calls daily, schedule service calls, after-hours on-call rotation.",
            "Greensboro, NC", "2024-01-15",
            90, "very_high", '["scheduling", "dispatch"]',
            "High volume dispatch role with scheduling duties", "ai_receptionist", 0.95, "qualified",
        ),
    )

    # Add lead
    lead = conn.execute(
        "INSERT INTO leads (workspace_id, company_id) VALUES (%s,%s) RETURNING id",
        (workspace_id, company_id),
    ).fetchone()
    lead_id = str(lead["id"])

    conn.close()
    return company_id, lead_id, workspace_id


@pytest.fixture
def fixture_llm():
    """Install fixture LLM with canned responses for research and QC."""
    scripts = {
        "company research analyst for Orbit": json.dumps({
            "summary": "Acme HVAC is a growing HVAC company in Greensboro, NC with 12 employees. Active hiring for dispatcher role indicates high call volume and scheduling pain.",
            "primary_problem": "High inbound call volume overwhelming staff, especially after-hours calls going unanswered",
            "reason_now": "Actively hiring dispatcher with after-hours requirements; using ServiceTitan but no AI receptionist",
            "recommended_offer": "ai_receptionist",
            "evidence": [
                {"claim": "Hiring for dispatcher role with high_value intent (score: 85)", "source_ref": "hiring_signal:...", "source_type": "hiring_signal"},
                {"claim": "Job posting mentions 50+ inbound calls daily and after-hours on-call", "source_ref": "job_posting:...", "source_type": "job_description"},
                {"claim": "Tech stack includes ServiceTitan and HubSpot", "source_ref": "tech_signals:...", "source_type": "tech_signal"},
                {"claim": "Google rating 4.7 with 42 reviews indicates strong reputation", "source_ref": "reviews:...", "source_type": "review"},
            ],
        }),
        "email quality gate for Orbit": json.dumps({
            "has_specific_observation": True,
            "observation_sentence": "Saw you're hiring a dispatcher to handle 50+ inbound calls daily.",
            "connects_to_problem": True,
            "problem": "call_volume",
            "pass": True,
            "failure_reasons": [],
        }),
    }
    llm = FixtureLLM(scripts=scripts)
    registry.override("llm", llm)
    yield llm
    registry.clear_overrides()


def test_research_evidence_citations(setup_company, fixture_llm):
    """Test that research report includes evidence with claim+source_ref+source_type."""
    company_id, _, _ = setup_company
    report = research.research_company(company_id)

    assert report.summary
    assert report.primary_problem
    assert report.reason_now
    assert report.recommended_offer
    assert isinstance(report.evidence, list)
    assert len(report.evidence) > 0

    for ev in report.evidence:
        assert "claim" in ev and ev["claim"]
        assert "source_ref" in ev and ev["source_ref"]
        assert "source_type" in ev and ev["source_type"] in research.RESEARCH_EVIDENCE_TYPES


def test_qc_gate_catches_generic(setup_company, db_url):
    """Test that generic email fails QC (no specific observation)."""
    company_id, lead_id, _ = setup_company

    generic_email = "Hi [Name], we help businesses like yours with AI receptionist solutions. We specialize in helping companies improve their customer service. Let's schedule a call."

    import psycopg
    conn = psycopg.connect(db_url, autocommit=True)
    conn.row_factory = psycopg.rows.dict_row
    company = conn.execute("SELECT * FROM companies WHERE id=%s", (company_id,)).fetchone()
    conn.close()

    lead_context = {"company": dict(company)}
    # Use deterministic QC (no LLM)
    registry.clear_overrides()
    result = email_qc.qc_email(generic_email, None, lead_context)

    assert result.pass_ is False
    assert "generic template language" in str(result.failure_reasons).lower() or not result.has_specific_observation


def test_qc_gate_passes_specific(setup_company, fixture_llm, db_url):
    """Test that specific email referencing hiring signal passes QC."""
    company_id, lead_id, _ = setup_company

    specific_email = "Hi John, saw you're hiring a dispatcher to handle 50+ inbound calls daily and manage after-hours on-call. Our AI receptionist handles overflow and after-hours so your team doesn't burn out. Worth a quick chat?"

    import psycopg
    conn = psycopg.connect(db_url, autocommit=True)
    conn.row_factory = psycopg.rows.dict_row
    company = conn.execute("SELECT * FROM companies WHERE id=%s", (company_id,)).fetchone()
    conn.close()

    # Need research report for this test
    report = research.research_company(company_id)

    lead_context = {"company": dict(company)}
    result = email_qc.qc_email(specific_email, {
        "primary_problem": report.primary_problem,
        "recommended_offer": report.recommended_offer,
        "evidence": report.evidence,
    }, lead_context)

    assert result.pass_ is True
    assert result.has_specific_observation is True
    assert "dispatcher" in result.observation_sentence.lower()


def test_opportunity_components_sum(setup_company, fixture_llm):
    """Test that opportunity score components sum to total."""
    company_id, _, _ = setup_company

    breakdown = opportunity.compute_opportunity_score(company_id)

    components = breakdown.components
    total = sum(components.values())
    assert breakdown.total == total
    assert 0 <= breakdown.total <= 100
    assert breakdown.tier in ("A+", "A", "B", "C", "D")
    assert breakdown.recommended_action in ("call_email_linkedin", "email_call", "email_sequence", "do_not_contact")


def test_tier_mapping(setup_company):
    """Test tier thresholds: 95->A+, 85->A, 70->B, 55->C, 40->D."""
    # We'll test by directly calling the internal tier logic
    # Since we can't easily control all components, verify the mapping constants
    assert opportunity.TIER_THRESHOLDS["A+"] == 90
    assert opportunity.TIER_THRESHOLDS["A"] == 80
    assert opportunity.TIER_THRESHOLDS["B"] == 65
    assert opportunity.TIER_THRESHOLDS["C"] == 50
    assert opportunity.TIER_THRESHOLDS["D"] == 0

    # Test action mapping
    assert opportunity.ACTION_MAPPING["A+"] == "call_email_linkedin"
    assert opportunity.ACTION_MAPPING["A"] == "call_email_linkedin"
    assert opportunity.ACTION_MAPPING["B"] == "email_call"
    assert opportunity.ACTION_MAPPING["C"] == "email_sequence"
    assert opportunity.ACTION_MAPPING["D"] == "do_not_contact"


def test_emv_calculation(setup_company, fixture_llm):
    """Test EMV = p_reply * p_meeting * value."""
    company_id, _, _ = setup_company

    emv = opportunity.compute_emv(company_id)

    expected = round(opportunity.DEFAULT_P_REPLY * opportunity.DEFAULT_P_MEETING * opportunity.DEFAULT_CUSTOMER_VALUE, 2)
    assert emv.emv == expected
    assert emv.p_positive_reply == opportunity.DEFAULT_P_REPLY
    assert emv.p_meeting == opportunity.DEFAULT_P_MEETING
    assert emv.est_customer_value == opportunity.DEFAULT_CUSTOMER_VALUE


def test_website_intel_detects_techs(setup_company):
    """Test that website intel detects ServiceTitan from fixture HTML."""
    company_id, _, _ = setup_company

    # The company already has tech_signals in DB from setup
    # Test the detection logic directly
    html = '<script src="https://st.servicetitan.com/app.js"></script><script src="https://js.hsforms.net/forms.js"></script>'
    detected = website_intel._detect_tech_stack(html)

    assert detected["servicetitan"] is True
    assert detected["hubspot"] is True
    assert detected["google_analytics"] is False


def test_freshness_decay(setup_company, db_url):
    """Test that signal freshness_multiplier reduces recency component."""
    company_id, _, workspace_id = setup_company

    # Get the hiring signal and check freshness
    import psycopg
    conn = psycopg.connect(db_url, autocommit=True)
    conn.row_factory = psycopg.rows.dict_row
    signal = conn.execute(
        "SELECT freshness_multiplier FROM hiring_signals WHERE company_id=%s", (company_id,)
    ).fetchone()
    conn.close()

    freshness = float(signal["freshness_multiplier"])
    recency = opportunity._compute_recency(company_id, workspace_id)
    assert recency == round(freshness * 10, 1)
    assert recency <= 10


def test_icp_fit_scoring():
    """Test deterministic ICP fit scoring."""
    signals = {
        "single_location": True,
        "owner_visible": True,
        "family_owned": False,
        "simple_site": True,
        "residential_focus": True,
        "local_service_area": True,
        "direct_phone": True,
        "franchise": False,
        "multi_location": False,
        "careers_page": False,
        "enterprise_signals": False,
        "national_brand": False,
        "multi_state": False,
    }
    score, detail = scoring.icp_fit_score(signals)
    assert 0 <= score <= 10
    assert detail["single_location"] == "+3"
    assert detail["owner_visible"] == "+3"


def test_hiring_intent_scoring():
    """Test hiring intent scoring."""
    score = scoring.hiring_intent_score(
        role_key="dispatcher",
        icp_match=True,
        after_hours=True,
        phone_heavy=True,
        scheduling_duties=True,
        multiple_openings=False,
        days_old=5,
        multiple_locations=False,
    )
    # dispatcher(25) + icp_match(30) + after_hours(15) + phone_heavy(15) + scheduling(15) + posted_7d(5) = 105 -> clamped to 100
    assert score == 100


def test_severity_mapping():
    """Test problem severity mapping."""
    assert opportunity.SEVERITY_MAPPING["high"] == 20
    assert opportunity.SEVERITY_MAPPING["medium"] == 12
    assert opportunity.SEVERITY_MAPPING["low"] == 5
    assert opportunity.SEVERITY_MAPPING["none"] == 0


def test_pain_to_offer_mapping():
    """Test PAIN_TO_OFFER mapping."""
    assert opportunity.PAIN_TO_OFFER["call_volume"] == "ai_receptionist"
    assert opportunity.PAIN_TO_OFFER["after_hours"] == "after_hours_booking"
    assert opportunity.PAIN_TO_OFFER["scheduling"] == "appointment_scheduling"


def test_signal_type_offer_routing(setup_company, fixture_llm):
    """Dispatcher signal with high_value intent routes to voice_ai_receptionist."""
    company_id, _, _ = setup_company
    breakdown = opportunity.compute_opportunity_score(company_id)
    assert breakdown.recommended_pitch == "voice_ai_receptionist"


def test_website_intel_gaps():
    """No booking CTA in HTML → no_online_booking=True in derived findings."""
    # HTML with phone but no booking CTA and no after-hours messaging
    html = (
        '<html><head><meta name="viewport" content="width=device-width"></head>'
        '<body><a href="tel:+13365550000">Call Us</a></body></html>'
    )
    booking = website_intel._extract_booking_cta(html)
    phone = website_intel._extract_phone_visible(html)
    after_hours = website_intel._detect_after_hours_messaging(html)
    ssl_valid = True  # pretend https
    mobile = website_intel._check_mobile_viewport(html)

    findings = {
        "booking_cta": booking,
        "phone_visible": phone,
        "after_hours_messaging": after_hours,
        "ssl_valid": ssl_valid,
        "mobile_viewport_meta": mobile,
        "ttfb_ms": 500,
    }
    findings["after_hours_gap"] = bool(phone.get("text")) and not after_hours
    findings["no_online_booking"] = not bool(booking.get("text"))
    findings["weak_website"] = (
        not findings["ssl_valid"]
        or (findings.get("ttfb_ms", 0) or 0) > 3000
        or not findings["mobile_viewport_meta"]
    )

    assert findings["no_online_booking"] is True
    assert findings["after_hours_gap"] is True
    assert findings["weak_website"] is False