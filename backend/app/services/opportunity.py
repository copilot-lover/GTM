"""Opportunity Scoring Service — WS-D: composite opportunity score + EMV.

Computes opportunity_score from multiple components, writes to scores table.
Computes EMV (Expected Meeting Value) from reply/meeting rates and customer value.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

import psycopg.rows

import app.db as db
from app.providers import ProviderUnavailable, get
from app.providers.base import LLMProvider
from app.services import scoring
from app.services.flags import get_flag

log = logging.getLogger(__name__)

# Default weights from spec — can be overridden via system_flags 'opportunity_weights'
DEFAULT_OPPORTUNITY_WEIGHTS = {
    "icp_fit_weight": 25,      # normalized icp_fit_score (0-10) * 25 = max 25
    "intent_weight": 30,       # hiring signal_score * 0.3 = max 30
    "severity_weight": 20,     # problem severity 0-20
    "contactability_weight": 10,  # max 10
    "recency_weight": 10,      # freshness_multiplier * 10 = max 10
    "history_weight": 5,       # min(5, past_meetings*1.5 + past_customers*3) = max 5
}

SEVERITY_MAPPING = {
    "high": 20,
    "medium": 12,
    "low": 5,
    "none": 0,
}

TIER_THRESHOLDS = {
    "A+": 90,
    "A": 80,
    "B": 65,
    "C": 50,
    "D": 0,
}

ACTION_MAPPING = {
    "A+": "call_email_linkedin",
    "A": "call_email_linkedin",
    "B": "email_call",
    "C": "email_sequence",
    "D": "do_not_contact",
}

SIGNAL_TYPE_TO_OFFER = {
    "dispatcher": ["voice_ai_receptionist", "appointment_scheduling"],
    "receptionist": ["ai_receptionist"],
    "customer_service": ["ai_phone_receptionist", "website_conversion"],
    "appointment_setter": ["lead_qualification", "appointment_scheduling"],
    "call_center": ["ai_phone_receptionist", "missed_call_recovery"],
    "scheduler": ["appointment_scheduling"],
    "service_coordinator": ["follow_up_automation", "appointment_scheduling"],
    "office_admin": ["ai_receptionist", "follow_up_automation"],
    "sales": ["lead_qualification", "appointment_scheduling"],
}

PAIN_TO_OFFER = {
    "call_volume": "ai_receptionist",
    "after_hours": "after_hours_booking",
    "scheduling": "appointment_scheduling",
    "lead_qualification": "lead_qualification",
    "website_conversion": "website_conversion",
    "follow_up": "follow_up_automation",
    "reviews": "review_generation",
    "missed_calls": "missed_call_recovery",
}

DEFAULT_P_REPLY = 0.05
DEFAULT_P_MEETING = 0.30
DEFAULT_CUSTOMER_VALUE = 297  # MRR estimate


@dataclass
class OpportunityBreakdown:
    total: int
    tier: str
    components: dict
    recommended_action: str
    recommended_pitch: str
    primary_problem: str
    reason_now: str


@dataclass
class EMVResult:
    emv: float
    p_positive_reply: float
    p_meeting: float
    est_customer_value: float


def _get_opportunity_weights() -> dict[str, float]:
    """Load weights from system_flags, fallback to defaults."""
    flag = get_flag("opportunity_weights")
    if flag and isinstance(flag, dict):
        return {**DEFAULT_OPPORTUNITY_WEIGHTS, **flag}
    return DEFAULT_OPPORTUNITY_WEIGHTS


def _get_latest_research(company_id: str) -> dict | None:
    """Get the most recent research report for a company."""
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        return conn.execute(
            """SELECT * FROM research_reports
               WHERE company_id=%s ORDER BY created_at DESC LIMIT 1""",
            (company_id,),
        ).fetchone()


def _get_active_hiring_signals(company_id: str, workspace_id: str) -> list[dict]:
    """Get active hiring signals for a company."""
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        return conn.execute(
            """SELECT * FROM hiring_signals
               WHERE company_id=%s AND workspace_id=%s AND status='active'
               ORDER BY signal_score DESC""",
            (company_id, workspace_id),
        ).fetchall()


def _get_company(company_id: str) -> dict | None:
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        return conn.execute("SELECT * FROM companies WHERE id=%s", (company_id,)).fetchone()


def _get_lead_for_company(company_id: str) -> dict | None:
    """Get the primary lead for a company."""
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        return conn.execute(
            "SELECT * FROM leads WHERE company_id=%s ORDER BY created_at DESC LIMIT 1",
            (company_id,),
        ).fetchone()


def _get_meeting_history(lead_id: str) -> tuple[int, int]:
    """Get past meetings count and past customers count for a lead."""
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        meetings = conn.execute(
            """SELECT COUNT(*) as cnt FROM meetings
               WHERE lead_id=%s AND status IN ('held','booked')""",
            (lead_id,),
        ).fetchone()
        # Past customers: opportunities won for this lead's company
        past_customers = conn.execute(
            """SELECT COUNT(*) as cnt FROM opportunities o
               JOIN leads l ON l.id = o.lead_id
               WHERE l.company_id = (SELECT company_id FROM leads WHERE id=%s)
               AND o.stage = 'won'""",
            (lead_id,),
        ).fetchone()
    return int(meetings["cnt"] or 0), int(past_customers["cnt"] or 0)


def _get_contactability(company_id: str, lead_id: str | None) -> int:
    """Calculate contactability score 0-10."""
    score = 0
    company = _get_company(company_id)

    # Has verified email (check contacts)
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        verified_email = conn.execute(
            """SELECT 1 FROM contacts
               WHERE company_id=%s AND email_verification_status='verified' LIMIT 1""",
            (company_id,),
        ).fetchone()
    if verified_email:
        score += 10
        return min(10, score)  # Max 10, verified email is strongest signal

    # Has owner name
    if company and company.get("owner_name"):
        score += 5

    # Has phone
    if company and company.get("phone"):
        score += 3

    # Has LinkedIn (placeholder - would need enrichment)
    # For now, skip LinkedIn check

    return min(10, score)


def _compute_severity(report: dict | None) -> int:
    """Extract problem severity from research report."""
    if not report:
        return 0
    primary_problem = (report.get("primary_problem") or "").lower()
    # Heuristic: check for severity keywords
    if any(k in primary_problem for k in ["critical", "severe", "overwhelming", "crisis", "emergency", "losing"]):
        return SEVERITY_MAPPING["high"]
    if any(k in primary_problem for k in ["struggling", "difficult", "challenging", "behind", "missed", "unanswered"]):
        return SEVERITY_MAPPING["medium"]
    if any(k in primary_problem for k in ["could improve", "optimize", "better", "efficient", "automate"]):
        return SEVERITY_MAPPING["low"]
    # Default based on recommended offer urgency
    offer = report.get("recommended_offer", "")
    if offer in ("ai_receptionist", "missed_call_recovery", "after_hours_booking"):
        return SEVERITY_MAPPING["medium"]
    return SEVERITY_MAPPING["low"]


def _compute_recency(company_id: str, workspace_id: str) -> float:
    """Compute recency component from signal freshness."""
    signals = _get_active_hiring_signals(company_id, workspace_id)
    if not signals:
        return 0.0
    # Use the highest freshness_multiplier from active signals
    max_freshness = max(float(s.get("freshness_multiplier", 0)) for s in signals)
    return round(max_freshness * 10, 1)


def _compute_history(lead_id: str | None) -> int:
    """Compute history component from meetings and past customers."""
    if not lead_id:
        return 0
    meetings, past_customers = _get_meeting_history(lead_id)
    score = min(5, round(meetings * 1.5 + past_customers * 3))
    return score


def compute_opportunity_score(company_id: str) -> OpportunityBreakdown:
    """Main entry: compute opportunity score for a company, write to scores table."""
    company = _get_company(company_id)
    if not company:
        raise ValueError(f"Company {company_id} not found")

    workspace_id = str(company["workspace_id"])
    lead = _get_lead_for_company(company_id)
    lead_id = str(lead["id"]) if lead else None

    weights = _get_opportunity_weights()

    # 1. ICP Fit (from scoring.icp_fit_score, normalized 0-10 * 25)
    icp_signals = {
        "single_location": (company.get("number_of_locations") or 1) == 1,
        "owner_visible": bool(company.get("owner_name")),
        "family_owned": False,  # Would need enrichment
        "simple_site": True,  # Placeholder
        "residential_focus": company.get("vertical") in ("hvac", "plumbing", "electrical", "roofing"),
        "local_service_area": True,
        "direct_phone": bool(company.get("phone")),
        "franchise": False,
        "multi_location": (company.get("number_of_locations") or 1) > 1,
        "careers_page": False,
        "enterprise_signals": False,
        "national_brand": False,
        "multi_state": False,
    }
    icp_fit_raw, _ = scoring.icp_fit_score(icp_signals)
    icp_fit_component = round((icp_fit_raw / 10) * weights["icp_fit_weight"])

    # 2. Intent (hiring signal score * 0.3, max 30)
    signals = _get_active_hiring_signals(company_id, workspace_id)
    intent_component = 0
    if signals:
        top_signal = signals[0]
        signal_score = top_signal.get("signal_score", 0)
        intent_category = top_signal.get("intent_category", "")
        if intent_category in ("high_value", "medium_value"):
            intent_component = round(signal_score * 0.3)
        intent_component = min(weights["intent_weight"], intent_component)

    # 3. Severity (from research report)
    research = _get_latest_research(company_id)
    severity_component = _compute_severity(research)
    severity_component = min(weights["severity_weight"], severity_component)

    # 4. Contactability (0-10)
    contactability_component = _get_contactability(company_id, lead_id)
    contactability_component = min(weights["contactability_weight"], contactability_component)

    # 5. Recency (freshness * 10, max 10)
    recency_component = _compute_recency(company_id, workspace_id)
    recency_component = min(weights["recency_weight"], recency_component)

    # 6. History (min 5, meetings*1.5 + customers*3)
    history_component = _compute_history(lead_id)
    history_component = min(weights["history_weight"], history_component)

    # Total
    total = (
        icp_fit_component + intent_component + severity_component +
        contactability_component + recency_component + history_component
    )
    total = max(0, min(100, total))

    # Tier
    tier = "D"
    for t, threshold in TIER_THRESHOLDS.items():
        if total >= threshold:
            tier = t
            break

    # Recommended action
    recommended_action = ACTION_MAPPING.get(tier, "do_not_contact")

    # Recommended pitch
    recommended_pitch = "ai_receptionist"
    if research:
        recommended_pitch = research.get("recommended_offer") or "ai_receptionist"
        # Fallback to PAIN_TO_OFFER mapping
        if recommended_pitch == "ai_receptionist":
            problem = (research.get("primary_problem") or "").lower()
            for pain_key, offer in PAIN_TO_OFFER.items():
                if pain_key in problem:
                    recommended_pitch = offer
                    break

    # Override with signal-based offer routing (§16)
    if signals:
        top = signals[0]
        if top.get("intent_category") in ("high_value", "medium_value"):
            role_cat = top.get("role_category", "")
            signal_offers = SIGNAL_TYPE_TO_OFFER.get(role_cat, [])
            if signal_offers:
                recommended_pitch = signal_offers[0]

    primary_problem = research.get("primary_problem", "") if research else ""
    reason_now = research.get("reason_now", "") if research else ""

    breakdown = OpportunityBreakdown(
        total=total,
        tier=tier,
        components={
            "icp_fit": icp_fit_component,
            "intent": intent_component,
            "severity": severity_component,
            "contactability": contactability_component,
            "recency": recency_component,
            "history": history_component,
        },
        recommended_action=recommended_action,
        recommended_pitch=recommended_pitch,
        primary_problem=primary_problem,
        reason_now=reason_now,
    )

    # Write to scores table
    _write_opportunity_score(lead_id, workspace_id, breakdown)

    return breakdown


def _write_opportunity_score(lead_id: str | None, workspace_id: str, breakdown: OpportunityBreakdown) -> None:
    if not lead_id:
        return
    with db.get_pool().connection() as conn:
        conn.execute(
            """INSERT INTO scores (workspace_id, lead_id, score_type, score, components,
                   tier, recommended_action, recommended_pitch, primary_problem, reason_now)
               VALUES (%s,%s,'opportunity',%s,%s,%s,%s,%s,%s,%s)""",
            (
                workspace_id, lead_id, breakdown.total,
                json.dumps(breakdown.components),
                breakdown.tier, breakdown.recommended_action,
                breakdown.recommended_pitch, breakdown.primary_problem,
                breakdown.reason_now,
            ),
        )


def compute_emv(company_id: str) -> EMVResult:
    """Compute Expected Meeting Value for a company."""
    company = _get_company(company_id)
    if not company:
        raise ValueError(f"Company {company_id} not found")

    workspace_id = str(company["workspace_id"])
    lead = _get_lead_for_company(company_id)
    lead_id = str(lead["id"]) if lead else None

    # p_positive_reply: from historical learning or default
    p_reply = DEFAULT_P_REPLY
    if lead_id:
        with db.get_pool().connection() as conn:
            conn.row_factory = psycopg.rows.dict_row
            # Could compute from email_events reply rates for this workspace
            # For now use default
            pass

    # p_meeting: default
    p_meeting = DEFAULT_P_MEETING

    # est_customer_value: from opportunities avg MRR or default
    est_value = DEFAULT_CUSTOMER_VALUE
    if lead_id:
        with db.get_pool().connection() as conn:
            conn.row_factory = psycopg.rows.dict_row
            avg_mrr = conn.execute(
                """SELECT AVG(value_mrr) as avg_mrr FROM opportunities o
                   JOIN leads l ON l.id = o.lead_id
                   WHERE l.company_id = (SELECT company_id FROM leads WHERE id=%s)
                   AND o.value_mrr IS NOT NULL""",
                (lead_id,),
            ).fetchone()
        if avg_mrr and avg_mrr["avg_mrr"]:
            est_value = float(avg_mrr["avg_mrr"])

    emv = round(p_reply * p_meeting * est_value, 2)

    result = EMVResult(
        emv=emv,
        p_positive_reply=p_reply,
        p_meeting=p_meeting,
        est_customer_value=est_value,
    )

    # Write EMV score
    if lead_id:
        with db.get_pool().connection() as conn:
            conn.execute(
                """INSERT INTO scores (workspace_id, lead_id, score_type, score, components)
                   VALUES (%s,%s,'emv',%s,%s)""",
                (
                    workspace_id, lead_id,
                    int(emv * 100),  # Store as basis points for integer score
                    json.dumps({
                        "p_positive_reply": p_reply,
                        "p_meeting": p_meeting,
                        "est_customer_value": est_value,
                        "emv_usd": emv,
                    }),
                ),
            )

    return result