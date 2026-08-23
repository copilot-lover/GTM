"""Scoring engines (spec §7.3). Three separate scores — never conflated."""

ICP_SIGNAL_WEIGHTS = {
    "single_location": 3,
    "owner_visible": 3,
    "family_owned": 2,
    "simple_site": 2,
    "residential_focus": 2,
    "local_service_area": 2,
    "direct_phone": 1,
}
ICP_NEGATIVE_WEIGHTS = {
    "franchise": -4,
    "multi_location": -4,
    "careers_page": -3,
    "enterprise_signals": -3,
    "national_brand": -4,
    "multi_state": -3,
}
QUALIFY_THRESHOLD = 6

PRIORITY_WEIGHTS = {"intent": 0.40, "fit": 0.30, "contact_quality": 0.20, "history": 0.10}

OFFER_CATALOG = {
    "ai_receptionist",
    "missed_call_recovery",
    "after_hours_booking",
    "lead_qualification",
    "website_conversion",
    "follow_up_automation",
    "review_generation",
    "appointment_scheduling",
}


def icp_fit_score(signals: dict) -> tuple[int, dict]:
    """Returns (score 0-10, evidence dict). Deterministic arithmetic only."""
    detail: dict = {}
    total = 0
    for name, weight in ICP_SIGNAL_WEIGHTS.items():
        if signals.get(name):
            total += weight
            detail[name] = f"+{weight}"
    for name, weight in ICP_NEGATIVE_WEIGHTS.items():
        if signals.get(name):
            total += weight
            detail[name] = str(weight)
    score = max(0, min(10, round(total / 1.8)))
    return score, detail


def fit_status_for(score: int, signals: dict, unclear: bool) -> str:
    if signals_too_large(signals):
        return "rejected_too_large"
    if score >= QUALIFY_THRESHOLD:
        return "qualified"
    if unclear:
        return "rejected_unclear"
    if score >= 4:
        return "borderline"
    return "rejected_not_relevant"


def signals_too_large(signals: dict) -> bool:
    return bool(signals.get("enterprise_signals") or signals.get("national_brand"))


def priority_score(
    *, intent: float, fit: float, contact_quality: float, history: float
) -> int:
    """All inputs normalized 0-1. Returns 0-100."""
    raw = (
        PRIORITY_WEIGHTS["intent"] * intent
        + PRIORITY_WEIGHTS["fit"] * fit
        + PRIORITY_WEIGHTS["contact_quality"] * contact_quality
        + PRIORITY_WEIGHTS["history"] * history
    )
    return round(max(0.0, min(1.0, raw)) * 100)


def priority_tier(score: int) -> str:
    if score >= 85:
        return "P1"
    if score >= 65:
        return "P2"
    if score >= 40:
        return "P3"
    return "P4"


HIRING_ROLE_BASE = {
    "receptionist": 25,
    "front_desk_receptionist": 25,
    "customer_service_representative": 25,
    "call_center_representative": 25,
    "appointment_setter": 25,
    "service_coordinator": 25,
    "dispatcher": 25,
    "office_manager": 20,
}
HIRING_CONTEXT_ROLES = {
    "hvac_dispatcher": 25,
    "plumbing_dispatcher": 25,
    "hvac_csr": 25,
    "home_services_office_manager": 20,
    "home_services_receptionist": 25,
}


def hiring_intent_score(
    *,
    role_key: str | None,
    icp_match: bool,
    after_hours: bool,
    phone_heavy: bool,
    scheduling_duties: bool,
    multiple_openings: bool,
    days_old: int | None,
    multiple_locations: bool,
) -> int:
    """Additive intent scoring per spec §8.4; clamped to 0-100 for display."""
    score = 0
    if role_key in HIRING_ROLE_BASE or role_key in HIRING_CONTEXT_ROLES:
        score += HIRING_ROLE_BASE.get(role_key) or HIRING_CONTEXT_ROLES.get(role_key) or 25
    if icp_match:
        score += 30
    if after_hours:
        score += 15
    if phone_heavy:
        score += 15
    if scheduling_duties:
        score += 15
    if multiple_openings:
        score += 10
    if days_old is not None:
        if days_old <= 7:
            score += 10
        elif days_old <= 21:
            score += 5
    if multiple_locations:
        score -= 10
    return max(0, min(100, score))


def hiring_category(score: int) -> str:
    if score >= 90:
        return "very_high"
    if score >= 70:
        return "high"
    if score >= 50:
        return "medium"
    return "low"
