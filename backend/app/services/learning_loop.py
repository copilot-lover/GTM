"""
Learning Loop — outcome → interpretation → evidence → future adjustment (Phase 13).
Distinguishes: OBSERVATION vs INTERPRETATION vs DECISION vs LEARNING.
Evidence-based, appropriately conservative — does not rewrite behavior on one bad outcome.
"""

from dataclasses import dataclass
from collections import Counter

@dataclass
class Observation:
    what: str
    source: str
    n: int = 1

@dataclass
class Interpretation:
    observation: Observation
    meaning: str
    evidence_strength: str  # weak|medium|strong

@dataclass
class Learning:
    interpretation: Interpretation
    adjustment: str
    confidence: str  # low|medium|high — require high for auto-change
    should_change: bool

LEARNING_EXAMPLES = {
    "high_reply_from_signal": Interpretation(Observation("high reply", "hiring dispatcher + HVAC"), "hiring signal valuable for ICP", "strong"),
    "low_qual_from_source": Interpretation(Observation("low qual", "Yelp source"), "Yelp source low fit for ICP", "medium"),
    "high_positive_from_role": Interpretation(Observation("high positive", "ops manager role"), "ops manager strong decision-maker", "strong"),
    "high_interest_low_booking": Interpretation(Observation("interest but no booking", "conversation→meeting"), "conversation→meeting needs fix", "strong"),
    "high_unsubscribe_from_angle": Interpretation(Observation("high unsubscribe", "angle X"), "angle X resonates poorly or audience wrong", "medium"),
    "poor_signal_performance": Interpretation(Observation("poor performance", "signal Y"), "signal Y not predictive for this vertical", "weak"),
}

CONSERVATIVE_THRESHOLDS = {
    "min_observations": 10,
    "min_strong": 5,
}

def evaluate_learning(observations: list[Observation]) -> Learning | None:
    if not observations:
        return None
    total = sum(o.n for o in observations)
    if total < CONSERVATIVE_THRESHOLDS["min_observations"]:
        return Learning(
            Interpretation(observations[0], "insufficient evidence — small sample", "weak"),
            "no change — collect more evidence",
            "low",
            should_change=False,
        )
    # Example: count by source
    by_source = Counter(o.source for o in observations)
    top_source, top_n = by_source.most_common(1)[0]
    return Learning(
        Interpretation(Observation("aggregate", top_source, top_n), f"{top_source} shows pattern over {total} obs", "strong" if top_n >= CONSERVATIVE_THRESHOLDS["min_strong"] else "medium"),
        f"consider weighting {top_source} higher in FIND targeting",
        "high" if top_n >= CONSERVATIVE_THRESHOLDS["min_strong"] else "medium",
        should_change=top_n >= CONSERVATIVE_THRESHOLDS["min_strong"],
    )

def learning_principles() -> list[str]:
    return [
        "OBSERVATION is what happened (reply rate, booking rate)",
        "INTERPRETATION is what it means (why it happened)",
        "DECISION is what to change (adjust targeting/threshold)",
        "LEARNING is evidence for future, not instant rewrite",
        "Require N≥10 observations before changing thresholds",
        "Require strong evidence (n≥5 for source/angle) before auto-adjust",
        "One bad outcome never rewrites system behavior — log, don't overfit",
        "Distinguish seasonal/regional variance from permanent shift",
        "Negative learning (suppress poor fits) equally valuable as positive chasing",
    ]
