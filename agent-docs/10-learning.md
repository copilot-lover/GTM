# 10 — Learning (Outcome → Interpretation → Evidence → Future Adjustment)

## Role
Turn every outcome into appropriately conservative future adjustment. Distinguish OBSERVATION vs INTERPRETATION vs DECISION vs LEARNING. Phase 13.

## Service
**File:** `services/learning_loop.py:1`

### Dataclasses
```python
Observation:5  what:str, source:str, n:int=1
Interpretation:13 observation, meaning:str, evidence_strength ∈ weak|medium|strong
Learning:19 interpretation, adjustment:str, confidence ∈ low|medium|high, should_change:bool  # require high for auto-change
```

### Examples registry
`LEARNING_EXAMPLES:29` 6 canonical interpretations:
- high_reply_from_signal hiring dispatcher+HVAC → hiring signal valuable, strong
- low_qual_from_source Yelp → low fit, medium
- high_positive_from_role ops manager → strong decision-maker, strong
- high_interest_low_booking conversation→meeting needs fix, strong
- high_unsubscribe_from_angle angle X resonates poorly, medium
- poor_signal_performance signal Y not predictive, weak

### Conservative gating
`CONSERVATIVE_THRESHOLDS:38` `min_observations 10`, `min_strong 5`
`evaluate_learning:43`  
- if observations empty → None
- total = sum(n); if total <10 → should_change False, confidence low, adjustment "no change — collect more evidence", interpretation "insufficient evidence — small sample" weak (`learning_loop.py:47`).
- else by_source = Counter source, top_source, top_n → evidence strong if top_n≥5 else medium; confidence high if ≥5 else medium; should_change = top_n≥5; adjustment "consider weighting {top_source} higher in FIND targeting".

### Principles
`learning_principles:64` 9 strings:
- OBSERVATION is what happened (reply rate, booking rate)
- INTERPRETATION is what it means (why)
- DECISION is what to change (targeting/threshold)
- LEARNING is evidence for future, not instant rewrite
- Require N≥10 before changing thresholds
- Require strong n≥5 before auto-adjust
- One bad outcome never rewrites behavior — log, don't overfit
- Distinguish seasonal/regional variance from permanent shift
- Negative learning (suppress poor fits) equally valuable

## How it connects to GTM
- **FIND:** weighting dispatcher+HVAC higher after booking from that angle (`simulation.ts:232` LEARN: reinforce dispatcher+ads+weak_booking for HVAC; preserve weights in scores/provider_usage/agent_runs/audit_log).
- **QUALIFY:** calibration pending N — do NOT auto-rewrite threshold after single booking (`simulation.ts:232`).
- **Messaging:** dispatcher+booking variant promoted to template library manually.
- Per-source booking rate analytics (JSearch+HVAC 33% vs 12% baseline) shown in `simulation.ts:232`.
- Every outcome → better next TARGET/CONTACT/ANGLE/TIMING.

## What Component Owns vs Not
- **Owns:** interpretation taxonomy, conservative thresholds, observation→learning mapping.
- **Does NOT own:** actual weight updates (manual or future auto via flag), scoring arithmetic (scoring.py), intent re-evaluation (intent_engine), research (research.py). Learning loop is advisory; it does not write system_flags directly (should_change flag indicates readiness).

## Contracts Preserve
- Never auto-change on N<10 or non-strong evidence.
- Separate observation (what) from interpretation (why) from decision (what to change).
- Keep evidence per lead in `scores`, `hiring_signals.freshness_multiplier`, `activities`, `audit_log` for later aggregation — do not discard.
- Frontend simulation LEARN stage must cite prior steps evidence, not hallucinate cause (`canonical.ts:232` trace).

## Safe vs Dangerous
- Safe: add new LEARNING_EXAMPLES entry, adjust min_observations via flag, log observation without acting.
- Dangerous: auto-apply should_change true without human gate, reduce threshold to 2 and overfit seasonal blip, rewrite OFFER_CATALOG placement without evidence, infer causality from correlation without control.

## Before/After Modifying
- Before: read `services/learning_loop.py:43` + `frontend/src/gtm/canonical.ts: LC learn stage` + `frontend/src/gtm/simulation.ts:229` ABC HVAC learn step.
- After: Run `pytest` and simulation; verify evaluate_learning returns should_change False on N=3, True on N=12 with 6 from one source; check audit_log captures before/after; ensure dashboard analytics per-source booking rate reflects new data but thresholds unchanged.

## Examples
- **Positive:** 6 HVAC dispatcher leads, 33% booking rate vs 12% baseline → interpretation: dispatcher hiring is high-intent for HVAC (strong n6 ≥5) → decision: weight dispatcher signals higher for HVAC in next FIND batch; keep plumbing threshold separate.
- **Negative:** National franchise similarly profiled had rejected_too_large → downgrade national size at QUALIFY.
- **Anti-example:** One booked "AI receptionist" angle does NOT promote to default angle for all verticals — violates N≥10 rule; instead log and wait.

## Real file:line anchors
- Core: `services/learning_loop.py:43` evaluate_learning, `services/learning_loop.py:64` principles, `services/opportunity.py:390` EMV p_reply stub (PARTIALLY not wired), `frontend/src/gtm/simulation.ts:229` ABC HVAC LEARN step citing `frontend/src/gtm/canonical.ts:76` stages.

## Related
- Upstream: all GTM stages produce evidence (hiring_signals status, messages stage events, activities). 
- Downstream: future targeting weights affect FIND provider sampling; threshold tweaks affect QUALIFY fits; template library feeds DECIDE.

## PARTIALLY IMPLEMENTED gaps flagged
- No auto-application; manual promotion only (simulation says "manual").
- p_reply EMV static not learning from outcomes (`services/opportunity.py:390` pass stub) — learning loop not yet wired to EMV.
- No seasonal/regional variance detection yet; just principle listed.
