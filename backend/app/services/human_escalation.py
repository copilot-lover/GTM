"""
Human Escalation — Orbit knows when NOT to act autonomously.

Autonomy means: OBSERVE → REASON → DECIDE → ACT WHEN APPROPRIATE →
STOP WHEN APPROPRIATE → ESCALATE WHEN APPROPRIATE.

This module encodes escalation rules (Phase 10) — distinct from suppression
or QA. Even a high-confidence lead must escalate if context requires human judgment.
"""

from dataclasses import dataclass


@dataclass
class EscalationDecision:
    escalate: bool
    reason: str
    priority: str  # low|medium|high|critical
    suggested_action: str


# High-value / sensitive triggers that always require human
ESCALATION_KEYWORDS = {
    "legal", "lawyer", "attorney", "cease", "desist", "gdpr", "compliance",
    "contract", "msa", "sow", "negotiate", "discount", "pricing", "price",
    "lawsuit", "angry", "furious", "spam complaint", "unsubscribe", "report",
}

def should_escalate(
    *,
    intent: str,
    priority: str | None = None,
    confidence: float | None = None,
    text: str | None = None,
    has_pricing: bool = False,
    is_high_value: bool = False,
    _fit_status: str | None = None,
) -> EscalationDecision:
    lower = (text or "").lower()
    intent_u = (intent or "").upper()

    # Always escalate pricing — never auto-quote (spec FR-13)
    if has_pricing or "PRICE" in intent_u or "pricing" in lower:
        return EscalationDecision(True, "Pricing question — human must quote, never auto-answer", "high", "notify_human + draft for review")

    # Legal / angry / compliance
    if any(kw in lower for kw in ESCALATION_KEYWORDS):
        if any(w in lower for w in ("legal","lawyer","attorney","lawsuit","gdpr","cease")):
            return EscalationDecision(True, "Legal/compliance language — human required", "critical", "notify_human, do not auto-respond")
        if any(w in lower for w in ("angry","furious","spam","report")):
            return EscalationDecision(True, "Angry response — human de-escalation, suppress if needed", "high", "notify_human + consider suppression")

    # Human_required intent from reply classifier
    if intent_u == "HUMAN_REQUIRED":
        return EscalationDecision(True, "Reply classified HUMAN_REQUIRED — always human", "high", "notify_human")

    # P1 high value + complex → escalate for judgment
    if is_high_value and priority == "P1" and confidence is not None and confidence > 0.8:
        # Not always — only if negotiation-like
        if "negotiate" in lower or "contract" in lower:
            return EscalationDecision(True, "High-value P1 negotiation — human judgment", "high", "notify_human with packet")

    # Wrong person with referral → escalate to re-identify
    if "WRONG_PERSON" in intent_u or ("wrong person" in lower and "@" in lower):
        return EscalationDecision(True, "Wrong person with referral — human to re-identify correctly", "medium", "re-identify with referral, don't suppress domain")

    # Low confidence → escalate for additional evidence, not auto-act
    if confidence is not None and confidence < 0.4 and priority in ("P3","P4"):
        return EscalationDecision(True, "Low confidence — needs additional evidence before act", "medium", "hold for more signals, request human review")

    # High unsubscribe risk angle → pause, not escalate but suppress path
    if "unsubscribe" in lower or "remove me" in lower or intent_u == "UNSUBSCRIBE":
        return EscalationDecision(True, "Unsubscribe — human honors, adds suppression", "high", "suppress_and_close")

    return EscalationDecision(False, "No escalation trigger — autonomous handling appropriate", "low", "continue autonomous: observe→reason→act")


def autonomy_principles() -> list[str]:
    return [
        "OBSERVE — gather evidence before acting",
        "REASON — interpret signal → problem → opportunity with citations",
        "DECIDE — score, gate, and choose action deterministically where possible",
        "ACT WHEN APPROPRIATE — only on SEND_READY + approved + verified + not suppressed",
        "STOP WHEN APPROPRIATE — kill switch on reply/unsubscribe/bounce, hold on low confidence",
        "ESCALATE WHEN APPROPRIATE — pricing/legal/high-value/wrong_person/low confidence → human",
    ]
