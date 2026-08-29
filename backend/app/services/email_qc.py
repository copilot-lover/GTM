"""Email QC Gate — WS-D: AI Self-QC gate (spec §15, §45).

Validates that draft emails contain real business-specific observations
that connect to relevant Orbit problems. Returns pass/fail with reasons.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.providers import ProviderUnavailable, get
from app.providers.base import LLMProvider, LLMResponse

log = logging.getLogger(__name__)

QC_SYSTEM_PROMPT = (
    "You are an email quality gate for Orbit (AI receptionist agency). "
    "Given an email draft, research report, and lead context, determine: "
    "1) Does the email contain a REAL business-specific observation? Quote the exact sentence. "
    "2) Does it connect to a relevant Orbit problem (missed calls, after-hours, scheduling, "
    "lead qualification, website conversion, follow-up, reviews)? "
    "Return ONLY valid JSON: "
    "{has_specific_observation:bool, observation_sentence:string, "
    "connects_to_problem:bool, problem:string, pass:bool, failure_reasons:string[]}. "
    "Fail if: generic template language, no specific observation, observation not tied to Orbit problem, "
    "invented facts not in research report."
)

ORBIT_PROBLEMS = {
    "missed_calls", "after_hours", "scheduling", "lead_qualification",
    "website_conversion", "follow_up", "reviews", "call_volume",
    "dispatch", "receptionist", "staffing", "capacity"
}

@dataclass
class QCResult:
    has_specific_observation: bool
    observation_sentence: str
    connects_to_problem: bool
    problem: str
    pass_: bool
    failure_reasons: list[str]


def _get_llm() -> LLMProvider | None:
    try:
        return get("llm")
    except ProviderUnavailable:
        return None


def _build_qc_prompt(draft_body: str, research_report: dict, lead_context: dict) -> str:
    """Build the QC prompt with draft, research, and lead context."""
    research_summary = ""
    if research_report:
        research_summary = (
            f"Primary problem: {research_report.get('primary_problem', '')}\n"
            f"Reason now: {research_report.get('reason_now', '')}\n"
            f"Recommended offer: {research_report.get('recommended_offer', '')}\n"
            f"Evidence: {json.dumps(research_report.get('evidence', []))[:2000]}"
        )

    lead_summary = ""
    if lead_context:
        company = lead_context.get("company", {})
        lead_summary = (
            f"Business: {company.get('business_name', '')}\n"
            f"Vertical: {company.get('vertical', '')}\n"
            f"Location: {company.get('city', '')}, {company.get('state', '')}\n"
            f"Website: {company.get('website', '')}\n"
            f"Tech signals: {json.dumps(company.get('tech_signals', {}))}\n"
            f"Website findings: {json.dumps(company.get('website_findings', {}))[:1000]}"
        )

    return (
        f"EMAIL DRAFT:\n{draft_body}\n\n"
        f"RESEARCH REPORT:\n{research_summary}\n\n"
        f"LEAD CONTEXT:\n{lead_summary}\n\n"
        f"Analyze and return JSON."
    )


def _deterministic_qc(draft_body: str, research_report: dict, lead_context: dict) -> QCResult:
    """Deterministic fallback QC when LLM unavailable."""
    failure_reasons = []

    # Check for generic template language
    generic_phrases = [
        "we help businesses", "we help companies", "i noticed you",
        "i saw your website", "i came across", "reaching out",
        "i'd love to", "we specialize in", "our solution",
        "leading provider", "industry leader", "best in class"
    ]
    draft_lower = draft_body.lower()
    if any(p in draft_lower for p in generic_phrases):
        failure_reasons.append("contains generic template language")

    # Check for specific observation (heuristic: mentions business name, specific role, tech, hiring)
    has_specific = False
    observation_sentence = ""
    company = lead_context.get("company", {}) if lead_context else {}
    business_name = company.get("business_name", "").lower()

    sentences = [s.strip() for s in draft_body.replace("!", ".").replace("?", ".").split(".") if s.strip()]
    for sentence in sentences:
        sent_lower = sentence.lower()
        # Check for business-specific references
        if business_name and business_name in sent_lower:
            has_specific = True
            observation_sentence = sentence
            break
        # Check for hiring signal references
        if any(k in sent_lower for k in ["hiring", "job posting", "receptionist", "dispatcher", "role"]):
            has_specific = True
            observation_sentence = sentence
            break
        # Check for tech references
        tech_signals = company.get("tech_signals", {})
        active_tech = [k for k, v in tech_signals.items() if v]
        if any(t.replace("_", " ") in sent_lower for t in active_tech):
            has_specific = True
            observation_sentence = sentence
            break
        # Check for website findings
        wf = company.get("website_findings", {})
        if wf.get("booking_cta", {}).get("text") and wf["booking_cta"]["text"].lower() in sent_lower:
            has_specific = True
            observation_sentence = sentence
            break
        if wf.get("chat_widget") and wf["chat_widget"].lower() in sent_lower:
            has_specific = True
            observation_sentence = sentence
            break

    # Check connection to Orbit problem
    connects_to_problem = False
    problem = ""
    if research_report:
        primary_problem = (research_report.get("primary_problem") or "").lower()
        for orbit_prob in ORBIT_PROBLEMS:
            if orbit_prob in primary_problem and orbit_prob in draft_lower:
                connects_to_problem = True
                problem = orbit_prob
                break
        # Also check recommended offer
        offer = research_report.get("recommended_offer", "")
        if offer and offer.replace("_", " ") in draft_lower:
            connects_to_problem = True
            problem = offer

    pass_ = has_specific and connects_to_problem and not failure_reasons
    if not has_specific:
        failure_reasons.append("no specific business observation found")
    if not connects_to_problem:
        failure_reasons.append("does not connect to a relevant Orbit problem")

    return QCResult(
        has_specific_observation=has_specific,
        observation_sentence=observation_sentence,
        connects_to_problem=connects_to_problem,
        problem=problem,
        pass_=pass_,
        failure_reasons=failure_reasons,
    )


def qc_email(draft_body: str, research_report: dict | None, lead_context: dict | None) -> QCResult:
    """Main entry: QC an email draft against research and lead context."""
    llm = _get_llm()
    if not llm:
        return _deterministic_qc(draft_body, research_report or {}, lead_context or {})

    user_prompt = _build_qc_prompt(draft_body, research_report or {}, lead_context or {})

    try:
        resp: LLMResponse = llm.complete(QC_SYSTEM_PROMPT, user_prompt, model_tier="strong")
        import json as _json
        data = _json.loads(resp.content)

        return QCResult(
            has_specific_observation=data.get("has_specific_observation", False),
            observation_sentence=data.get("observation_sentence", ""),
            connects_to_problem=data.get("connects_to_problem", False),
            problem=data.get("problem", ""),
            pass_=data.get("pass", False),
            failure_reasons=data.get("failure_reasons", []),
        )
    except Exception as e:
        log.warning(f"LLM QC failed: {e}")
        return _deterministic_qc(draft_body, research_report or {}, lead_context or {})