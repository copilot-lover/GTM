# 06 — Qualification (Scoring Arithmetic, Priority Tiers, Re-evaluate)

## Role
QUALIFY decides is this worth attention now? Pure deterministic arithmetic, zero DB except via pipeline/intent_engine wrappers. Sources `services/scoring.py:1` (three separate scores never conflated per canonical.ts:214 whyExists) + `services/intent_engine.py:181` reevaluate.

## Scoring Arithmetic
### 1. ICP Fit Score 0-10
**File:** `services/scoring.py:39` `icp_fit_score(signals: dict) → (score, detail)`
```python
ICP_SIGNAL_WEIGHTS:3 = single_location 3, owner_visible 3, family_owned 2, simple_site 2, residential_focus 2, local_service_area 2, direct_phone 1  # total +15
ICP_NEGATIVE_WEIGHTS:12 = franchise -4, multi_location -4, careers_page -3, enterprise -3, national -4, multi_state -3
total = sum(positive if signals.get(k)) + sum(negative)
score = max(0, min(10, round(total/1.8)))  # divisor calibration PARTIALLY — 10 and 11 both →6
detail = {k: "+w" or "-w"} per active signal
```
- Divisor 1.8 maps theoretical max 15 → 8.3, negatives pull to 0. Edge: total 10→6 borderline, 11→6 same (threshold ambiguity `frontend/src/gtm/canonical.ts:244`).
- Test: `tests/test_scoring.py:11` perfect small → ≥8; `tests/test_scoring.py:21` franchise+national →0.

### 2. fit_status
**File:** `services/scoring.py:55` `fit_status_for(score, signals, unclear) → str`
```
if signals_too_large(enterprise or national): → "rejected_too_large"  (line 67)
elif score >= QUALIFY_THRESHOLD 6: → "qualified"
elif unclear: → "rejected_unclear"
elif score >=4: → "borderline"
else: → "rejected_not_relevant"
```
- Used in `pipeline.apply_qualification:243` with `scoring.fit_status_for(score, signals, bool(unclear))`.
- Contract: qualified→enriching else rejected stops chain (`pipeline.py:266` no next).

### 3. Priority Score 0-100 (P1-P4)
**File:** `services/scoring.py:71` `priority_score(intent, fit, contact_quality, history) → int`
```
PRIORITY_WEIGHTS:22 = intent 0.40, fit 0.30, contact_quality 0.20, history 0.10  (all 0-1 normalized)
raw = 0.4*intent +0.3*fit +0.2*contact +0.1*history
→ round(clamp 0-1 *100)
```
- Pipeline initial: `pipeline.apply_qualification:244` calls with intent min/max 0-1 parsed.intent default 0.3, fit score/10, contact_quality 0.6 if company_phone else 0.2, history 0.0.
- Intent engine composite: `intent_engine.reevaluate_lead:181` computes `total = base_icp(lead_score*10) + Σ signal/event contributions decayed + bonus 5/10` clamped 0-100 (different formula, intent-specific; both write to `leads.priority_score` but intent's includes recency).
- Tier: `priority_tier:84` ≥85 P1, ≥65 P2, ≥40 P3 else P4 (`scoring.py:84`) — speed-to-lead for P1, but intent_engine uses `≥70 fresh≤7 P1, ≥50 P2 else P3` (`intent_engine.py:256`) divergence PARTIALLY.

**Weights intent dominates:** `tests/test_scoring.py:54` high intent low fit > low intent high fit.

### 4. Hiring Intent Score 0-100
**File:** `services/scoring.py:113` `hiring_intent_score(role_key, icp_match, after_hours, phone_heavy, scheduling_duties, multiple_openings, days_old, multiple_locations) → int`
```
base role 20-25 (Hiring_ROLE_BASE:94) if key∈ROLES else 0
+ icp_match 30
+ after_hours 15 + phone_heavy 15 + scheduling_duties 15
+ multiple_openings 10
+ days_old ≤7 → +10, ≤21 → +5
- multiple_locations → -10
clamp 0-100; category very_high≥90, high≥70, medium≥50 else low (line 148)
```
- Used inside hiring_signals engine (different path) but shared logic for canonical interpretation.
- Test: `tests/test_scoring.py:61` receptionist+icp+fresh → ≥90 very_high; `tests/test_scoring.py:76` penal 10 for multi-location.

### 5. Opportunity Composite (see 07) vs here
- Opportunity `services/opportunity.py:23` 6 weights icp 25 + intent 30 + severity 20 + contact 10 + recency 10 + history 5 =100. Do not conflate with priority_score — canonical `canonical.ts:229` warns differentiate 3 scores: ICP 0-10 (is it ICP?), Priority 0-100 (what order?), Hiring intent 0-100 (how strong timing?).

## Priority Tiers & Remapping
- **Scoring tiers:** `scoring.priority_tier` P1/P2/P3/P4 thresholds 85/65/40 (`scoring.py:84`).
- **Intent tiers:** `intent_engine.reevaluate_lead` P1/P2/P3 thresholds 70/50 (`intent_engine.py:256`) plus freshness ≤7 required for P1.
- **Opportunity tiers:** `opportunity.py:39` A+90, A80, B65, C50, D0 with `ACTION_MAPPING:47` call_email_linkedin etc.
- **Pitfall:** _has_tier_a checks `scores.tier IN A/A+` but reevaluate never writes tier, so P2 promotion dead (`intent_engine.py:282`). Opportunity writes tier correctly (`opportunity.py:304`).

## Reevaluation Logic
**File:** `services/intent_engine.py:181`
- Triggered by `ingest_event` enqueue or `POST /gtm/leads/{id}/reevaluate` (`routers/gtm.py:221`) or scheduler `GTM_INTENT` 900s.
- Recency decay `recency = max(0, 1 - age_days/30)` (`intent_engine.py:50` _age_days). At 30d recency 0, but contribution 0 still appended (unfiltered) vs should exclude. 29d → 0.03.
- Contributions capped MAX_SIGNAL_CONTRIBUTION 35 each (`intent_engine.py:178`) while allowing stack to 100 clamp.
- Stores `scores.components.contributions[]` with label, points, evidence_ref, age_days for why-panel (`intent_engine.py:223`).
- Example fresh vs stale: `tests/test_gtm_acceptance.py:209` fresh pts≥30, stale ≤5, opportunity_score drops, P1 lost.

## What Component Owns
- `scoring.py` owns arithmetic pure functions, zero DB.
- `pipeline.py:240` owns qualification pipeline stage (scores + fit_status + events).
- `intent_engine.py` owns continuous re-score with decay and persistence.
- Frontend owns display tiers `canonical.ts:224`.

## Not Own
- Contact verification (enrichment), research (opportunity), send gate (outbound_gate).

## Contracts Preserve
- `icp_fit_score` divisor 1.8 and threshold 6 — changing shifts pipeline P1 volume; coordinated with tests.
- `priority_score` inputs normalized 0-1; do not pass raw 0-100.
- Evidence text mandatory per `pipeline.py:253` agent_evidence.
- Recency formula and MAX_SIGNAL cap must match tests expecting 29d→P3 not P1.

## Safe vs Dangerous
- Safe: weight tuning ±5%, threshold experiments with A/B via flag, add new ICP signal key with weight.
- Dangerous: changing divisor without recalibrating tests; merging priority and intent scores; removing clamp; adding tier write to reevaluate without backfill.

## What Must Be Tested After Modification
- `pytest tests/test_scoring.py tests/test_pipeline.py tests/test_gtm_acceptance.py::TestFreshHotSignalReprioritizes -v`; verify why-panel contributions and `GET /gtm/leads/{id}/why`.

## Before/After
- Before: read `services/scoring.py:39` + `tests/test_scoring.py:11` + `services/intent_engine.py:181`.
- After: `pytest tests/test_scoring.py tests/test_gtm_acceptance.py::TestFreshHotSignalReprioritizes -v`; check `GET /gtm/leads/{id}/why` contributions plausible.

## Examples
- ABC HVAC: signals single_location+owner_visible+family etc total 14 → round 7.7→8 → qualified. Priority: intent 0.78 fit 0.8 contact 0.6 history 0.5 → 0.4*0.78+0.3*0.8+0.2*0.6+0.1*0.5=0.78→78 P2 but intent fresh pushes P1 (intent_engine path). See `simulation.ts:98` breakdown.
- Borderline 10 pts →6 ambiguous; stays POSSIBLE not HIGH per `canonical.ts:244`.
