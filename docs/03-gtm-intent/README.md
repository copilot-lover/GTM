# GTM_BRAIN 2 — GTM_INTENT (Signals, Timing, Priority)

> **IETM teaching doc · Progressive disclosure: 🟢 Everyone → 🟡 Operator → 🔴 Builder**
> Brain: `frontend/src/gtm/canonical.ts:55` (`GtmBrain id="intent"`) · Engine: `backend/app/services/intent_engine.py:1` · Signals: `backend/app/services/hiring_signals.py:1` · Learning: `backend/app/services/learning_loop.py:1` · Canonical simulation: `frontend/src/gtm/simulation.ts:87`

---

# WHAT IS IT?

> 🟢 **BASIC**

**GTM_INTENT** is Brain 2: it answers **"Why care *now*?"**

If GTM_LEADS is *who is this*, GTM_INTENT is *what's happening, why should we act, and when*. It watches **what happened recently**, turns it into a **timed signal**, checks it against **context**, and decides **priority today** — then keeps recalculating as time passes.

```
OBSERVATION  →  SIGNAL  →  CONTEXT  →  INTERPRETATION  →  OPPORTUNITY
  what happened   normalized +      + what we know      = what it       = should we
  in the world    scored event       about this business   likely means    outreach now?
                  with freshness    (too large? owner-   (hiring → strain?
                  & expiry          operated? verified? ) booking → gap?)
```

> 🟡 This chain is the whole mental model. Confusing any link is how teams spam — a FACT ("posted dispatcher") becomes an INFERENCE ("they're overwhelmed") without evidence, or an INFERENCE becomes an OPPORTUNITY HYPOTHESIS ("needs AI receptionist") without contacting the right person.

**Required vocabulary (spec): OBSERVATION→SIGNAL→CONTEXT→INTERPRETATION→OPPORTUNITY and FACT vs INFERENCE vs OPPORTUNITY HYPOTHESIS — taught as the 5-noun chain in DEEPER DETAIL below and exercised via ABC HVAC example.**

---

# WHY DOES IT EXIST?

> 🟢 Three failures without it:

1. **Stale outreach** — a 29-day-old hiring signal scores like a fresh one → you pitch someone who already hired.
2. **Noisy targeting** — hiring a *careers page designer* scores like hiring a *dispatcher* → you waste sends.
3. **Conflated priorities** — one 0-100 score mixed across "is this ICP?" + "is timing good?" → you can't explain why you chose this lead now.

GTM_INTENT exists to fix all three with **deterministic arithmetic + recency decay**, auditable per-lead.

---

# WHAT GOES IN?

> 🟡 Two ingestion surfaces, one scoring engine:

| Input | Type | File | Weight / Window |
|-------|------|------|-----------------|
| **hiring_signals** rows | Signal (already scored 0-100) | `hiring_signals.py:188` `compute_signal_score()` → `upsert_hiring_signal:315` | freshness 1.0→0.05 by `FRESHNESS_MULTIPLIERS:69` (0-3d=1.0, 30d=0.1), `expires_at = posted_at+60d` (`hiring_signals.py:340`) |
| **intent_events** | Event (weighted, then decayed) | `intent_engine.py:19` `DEFAULT_EVENT_WEIGHTS` (`JOB_POSTED 35`, `EXPANSION 25`, etc.) + `register_event_type:38` | `EVENT_LOOKBACK_DAYS=30`, recency `1 - age/30` (`intent_engine.py:216`), processed via `FOR UPDATE SKIP LOCKED:121` |
| **company context** | Enrichment flag | `companies.tech_signals`, `number_of_locations`, `owner_name` | modulates intent: `icp_match +30`, `multiple_locations -10` (`scoring.py:113`) |
| **contactability** | Verification state | `contacts.email_verification_status=='verified'` | used in priority composition (`scoring.py:71`) |

> Inputs are facts; outputs are interpretations. Never invent a signal — if `intent_signals` unclear → false (`hiring_signals.detect_intent_signals:121` fail-closed).

---

# WHAT HAPPENS?

> 🟡 Two passes — classify, then re-rank, continuously:

**Pass 1 — Classify & score each raw posting (`hiring_signals.py:265`):**
1. `normalize_raw_posting()` (`hiring_signals.py:265`) → `classify_role()` (`hiring_signals.py:87` — LLM cheap tier → keyword `KEYWORD_ROLE_MAP:36` fallback) → `role_category` in 10 values (`ROLE_CATEGORIES:23` — dispatcher, receptionist, customer_service, etc.)
2. `detect_intent_signals()` (`hiring_signals.py:121` — LLM cheap → keyword fallback) → 7 booleans `{after_hours, phone_heavy, scheduling_duties, icp_match, high_volume, lead_intake, multiple_openings}`
3. `compute_signal_score()` (`hiring_signals.py:188` — additive weights from `DEFAULT_SIGNAL_WEIGHTS:48` — role base + intent + freshness `posted_3d/7d/14d` + company signals `no_online_booking, weak_website`) → `(signal_score 0-100, freshness_multiplier, intent_category)` (`high_value ≥80, medium ≥60, low ≥40, irrelevant`). Writes `hiring_signals` via `upsert_hiring_signal:315` (`ON CONFLICT workspace,source,source_job_id`).

**Pass 2 — Re-evaluate affected leads (`intent_engine.py:117→181`):**
1. `process_pending_events()` claims unprocessed `intent_events` batch (`FOR UPDATE SKIP LOCKED`), resolves `lead_id` from `company_id` by `priority_score DESC` (`intent_engine.py:73`)
2. Per lead, `reevaluate_lead()` (`intent_engine.py:181`) gathers `base_icp = lead_score*10`, active `hiring_signals` (`status='active'`), `intent_events` last 30d, computes per-signal `points = min(35, signal_score*freshness*recency)` capped at `MAX_SIGNAL_CONTRIBUTION=35` (`intent_engine.py:178`), per-event `points = weight * recency`, sums to `total = base_icp + Σpoints + (10 if ≥4 signals else 5 if ≥2)`, clamped 0-100, writes `leads.priority_score` + `scores(score_type='opportunity', components{base_icp, contributions[], signal_count})`.
3. Derives `priority` band: `P1 if total≥70 & freshest≤7d`, else `P2 if total≥50`, else `P3` (`intent_engine.py:256`).
4. `apply_expiry()` (`hiring_signals.py:437`) retires signals past `expires_at` or `posted_at+60d`, emitting alerts for high-value expired.

> 🔴 Scores **decay naturally** — at 0d recency 1.0, at 14d ~0.53, at 30d → 0 (`intent_engine.py:216`). Expired signals don't score (`status='active'` filter at `intent_engine.py:199`).

---

# WHAT DECISIONS ARE MADE?

> 🟡 GTM_INTENT decisions (deterministic, never LLM-judged):

- **Is this posting relevant?** → `role_category=='other'` + low intent →  `irrelevant`, not inserted as qualified (`intent_category` in `hiring_signals.py:253`).
- **How strong is timing?** → `hiring_intent_score()` (`scoring.py:113`) additive 0-100 — `role_key +25, icp_match +30, after_hours +15, phone_heavy +15, scheduling +15, multiple_openings +10, days_old ≤7 +10 else ≤21 +5, multiple_locations -10`. Keeps produce `PRIORITY_WEIGHTS` intent 0.40 vs fit 0.30.
- **What order should we work?** → `priority_score:71` (`0.4 intent +0.3 fit +0.2 contact_quality +0.1 history → 0-100 → P1 85-100 speed-to-lead, P2 65-84, P3 40-64, P4 <40 nurture`) vs `reevaluate_lead` priority bands (70/50) — two call paths produce slightly different bands; know which path you read (`canonical.ts:248` documents divergence).
- **Still relevant today?** → signal `freshness_multiplier:69` × `recency:216` — a 29d old signal contributes ~1 pt vs 33 at fresh for same `signal_score`.

> 🟢 All decisions are explainable: `components.contributions[]` per signal/event with `{label, points, evidence_ref, age_days}` (`intent_engine.py:223`) is exactly what the Why panel renders.

---

# WHAT COMES OUT?

> 🟡 Per-lead:

- **`leads.priority_score` (0-100)** + **`scores` row** (`score_type='opportunity'`, `components{base_icp, contributions, signal_count, computed_at}`) — updated on every fresh event (continuous re-evaluation, not one-time).
- **`priority` P1/P2/P3** band — drives scheduling (`P1` speed-to-lead, `BOOK` queue rank) and `scheduler._needs_approval()` (hybrid `A/A+` check via `scores.tier`).
- **Decay + expiry** — old signals contribute 0; past 60d status=`expired`; high-value expiry emits `alerts` warning.
- **Signal metadata** — `hiring_signals.pain_hypothesis, orbit_product_fit, confidence, intent_category, freshness_multiplier` — for `research._assemble_evidence:52` and `opportunity` severity linking.

> 🔴 Three scores, never conflated (`scoring.py` + `opportunity.py`):
> - **ICP fit 0-10** — is it ICP? (`scoring.icp_fit_score:39`)
> - **Priority 0-100** — what order? (`scoring.priority_score:71` + `intent_engine.reevaluate_lead:181`)
> - **Hiring intent 0-100** — how strong is timing? (`scoring.hiring_intent_score:113` + `hiring_signals.compute_signal_score:188`)

---

# REAL-WORLD EXAMPLE — ABC HVAC through GTM_INTENT

> 🟢 ABC HVAC numbers (from `simulation.ts:87-101`):

| Input | Value | Interpretation |
|-------|-------|---------------|
| Job title+desc | "Dispatcher — answer 50+ inbound calls/day, schedule service appointments, coordinate technicians" | `classify_role → dispatcher (confidence 0.92)`; `detect_intent_signals → {phone_heavy:true, scheduling_duties:true, icp_match:true (HVAC), after_hours:false, high_volume:true (50+), multiple_openings:false}` |
| `compute_signal_score` | role dispatcher base 35 + icp_match 30 + high_volume 20 + scheduling 15 + posted_3d 15 + no_online_booking 15 = before normalization high → `signal_score 78`, `freshness 0.9` (3d), `intent_category medium_value` | Medium-high intent, fresh |
| `reevaluate_lead` | `base_icp = 8*10 = 80`? Actually `lead_score 8 → base 80`; contributions: dispatcher hiring `min(35, 78*0.9*0.9≈63)` capped 35 → 31.5 raw? Simulation simplified: contributions total ~? `total 78` (`simulation.ts:98`) → `P1` (fresh ≤7d & ≥70). `contributions` emitted `[{label:"dispatcher hiring", points:31.5, evidence_ref:<signal_id>, age_days:3}]` | P1 HIGH-VALUE FIT — worth contacting now |
| After 29d no follow-up | `recency = 1 - 29/30 = 0.03` → contribution collapses ~1 pt → total drops to ~`base 40 + 1` → `P3` nurture | Decay does the demotion — no manual downgrade needed |
| After 61d | `hiring_signals.apply_expiry` → status=`expired`, alert warning (high-value), signal excluded from future reevaluations | Lifetime limited — prevents ghost leads |

---

# WHAT CAN GO WRONG?

> 🟡 From `canonical.ts` + inline `TODO`s:

- `known_event_types()` merges `DEFAULT + mutable global _extra via register_event_type` (`intent_engine.py:33`) — no persistence, race unsafe, `N+1` connections per `reevaluate`.
- `reevaluate_lead` still inserts 0-point contributions for 30d-old signals (unfiltered even when `recency=0`) — explainability panel shows clutter.
- `_has_tier_a` (`intent_engine.py:282`) reads `scores.tier` but `reevaluate_lead` never writes `tier` (writes only `score, components` at `intent_engine.py:268`) → always NULL, so `P2 if total≥50 or _has_tier_a` branch is dead code (`canonical.ts:251`).
- `hiring_signals.refresh_scores` (`hiring_signals.py:468`) has **partial refresh** bug: intent_signals hardcoded false → recomputed score wrong after company updates (`hiring_signals.py:486` comment).
- Two priority paths diverge: `scoring.priority_score` (0-100 via weights) vs `intent_engine.reevaluate_lead` (base+Σ contributions) — different `P` banding (`canonical.ts:248`).

> 🔴 Watch for: `provider fixtures fallback masks failure` — if all job sources return `[]`, `FIND` still reports 0 new without alerting (`canonical.ts:119`).

---

# EDGE CASES

> 🟡

- **Contradictory signals** (hiring + layoff `NEW_LOCATION` vs `JOB_REMOVED`) → both kept as contributions with opposite weights (`JOB_POSTED +35`, `JOB_REMOVED -10` — `intent_engine.py:19`), confidence lowered, not auto-HIGH.
- **Multiple signals on one company** → each capped at 35 but **stack** (`≥4 signals +10, ≥2 +5`) → strong multi-signal companies outrank single-signal ones.
- **Stale 29d signal** → recency 0.03 → still a contribution row but ~1 pt; 30d → 0 pts but still row (unfiltered). Intentionally, so audit trail shows why timing demoted it.
- **Strong fit but poor contactability** → `P2` not `P1`; `IDENTIFY` must solve before `OUTREACH` gate can pass (`outbound_gate.can_send:130` requires verified).
- **Expired hiring + fresh website change** → one decayed, one alive; intent stays medium (`intent_engine.py:256` branches on `freshest_age`).

---

# WHAT HAPPENS NEXT?

> 🟢 GTM_INTENT ranks the queue. Next:

- **05-qualification/** re-explains the *fit vs need vs timing* arithmetic operators read here should now feel mechanical, not mystical.
- **07-opportunity/** uses GTM_INTENT's signal timing + `pain_hypothesis` to lock the **angle** (`research` + `opportunity` pick one offer deterministically).
- **08-outbound/** watches `priority` + `freshest_age` via `scheduler.get_daily_capacity:104` business-hours slot to decide *when* Day 0 sends.
- **11-learning/** closes the loop: after `BOOK` or `lost`, `learning_loop.evaluate_learning:43` (`N≥10`, `strong ≥5`) decides whether to **weight this signal family higher in next FIND batch** vs. just log it.

---

# WHY DOES IT MATTER?

> 🟢 Timing is strategy. Without GTM_INTENT you contact every HVAC equally; with it you contact **this HVAC now** because a dispatcher hiring signal fresh at 3d plus weak booking collectively mean scheduling pressure *right now*, and you can prove it with `{label, points, evidence_ref, age_days}` in the Why panel. Decay then does the honest work of forgetting.

---

# DEEPER DETAIL (technical)

> 🔴 **BUILDER**

**Critical distinction — the five nouns (FACT vs INFERENCE vs OPPORTUNITY HYPOTHESIS — must teach in order):**

| Noun | Verbatim definition | Table | Example for ABC HVAC |
|------|---------------------|-------|----------------------|
| **FACT** | Verbatim truth you can cite | `job_postings.description` | "Job posting says 'answer 50+ inbound calls/day'" |
| **OBSERVATION** | Measured occurrence | `intent_events` row | `intent_events {event_type:'JOB_POSTED', observed_at:3d ago}` |
| **SIGNAL** | Normalized, scored, time-bound event | `hiring_signals` row | `hiring_signals {role_category:'dispatcher', signal_score:78, freshness:0.9, expires_at:+60d}` |
| **INFERENCE** | "What it likely means" given context | `hiring_signals.pain_hypothesis` + `research.primary_problem` | "Likely inbound demand creating scheduling pressure" (`simulation.ts:123`) |
| **OPPORTUNITY HYPOTHESIS** | Full GTM_LEADS+INTENT synthesis with evidence + angle | `research_reports + scores` + `opportunity.py:338` breakdown | "Growing HVAC, dispatch strain + weak booking → AI receptionist angle, Owner Maria, evidence citations, confidence medium-high, reason NOW: hiring+ads" |

> Never skip from FACT to OPPORTUNITY without passing through SIGNAL→CONTEXT→INTERPRETATION. That's how hallucination enters.

**Chain implementation:**

```
OBSERVATION (intent_events.ingest_event:58)
  ↓ workers poll FOR UPDATE SKIP LOCKED:121
SIGNAL (hiring_signals.normalize_raw_posting:265 → upsert_hiring_signal:315, scoring 188)
  ↓ resolution company_name|city|state + ON CONFLICT dedupe
CONTEXT (companies.tech_signals + website_findings + owner_operator_confidence injected into compute_signal_score:228)
  ↓
INTERPRETATION (hiring_signals.pain_hypothesis + orbit_product_fit  :342, research.research_company:330)
  ↓
OPPORTUNITY (opportunity.compute_opportunity_score:238 — 6 components, tier, EMV default $4.45 p=0.05)
```

**Arithmetic (pure, zero DB):**
- `scoring.icp_fit_score:39` — `detail[name]=+weight`, `score=round(total/1.8)` clamped 0-10, `QUALIFY_THRESHOLD=6`
- `scoring.priority_score:71` — `0.4*intent +0.3*fit +0.2*contact +0.1*history → 0-100`, `priority_tier:84` `P1≥85, P2≥65, P3≥40 else P4`
- `scoring.hiring_intent_score:113` — additive 0-100 with 8 clauses
- `hiring_signals.compute_signal_score:188` — `score += role_weight + Σ(intent_flags*weights) + freshness_bonus + Σ(company_flags)`, normalized by `max_theoretical` sum.
- `intent_engine.reevaluate_lead:181` — `points = min(35, signal_score*freshness*recency)` where `recency=1-age/30`, same for events by `weights[event_type]*recency`.

**Tables:**
- `hiring_signals(id, workspace_id, company_id, source, source_job_id, job_url, title, description, role_category, intent_category, pain_hypothesis, orbit_product_fit, confidence, signal_score, freshness_multiplier, expires_at, status, posted_at)` — active only scores (`intent_engine.py:199`)
- `intent_events(id, workspace_id, company_id, lead_id, signal_id, event_type, source, payload jsonb, occurred_at, processed bool, processed_at)`
- `scores(id, workspace_id, lead_id, score_type, score, components jsonb, tier, recommended_action, recommended_pitch, primary_problem, reason_now, computed_at)` — both `opportunity` and `emv` rows via `opportunity.py:361`

**Status:**
- ✅ IMPLEMENTED — classify→score→reevaluate→decay→expire→re-rank, continuously via `process_pending_events` pool `ai`.
- 🚧 PLANNED/BUG — `refresh_scores` partial (known bug comment `hiring_signals.py:498`), `_has_tier_a` dead branch, N+1 query per reevaluate, dual priority banding documented not yet unified, auto-reweight after N≥10 exists as thresholds but not wired.

**Progressive disclosure:** This doc is dual-purpose: teach the `OBSERVATION→OPPORTUNITY` chain to humans, and be the exact arithmetic reference builders verify against `scoring.py:39,71,113` + `intent_engine.py:181` + `hiring_signals.py:188`.

**Learning hook:** `learning_loop.py:43` enforces conservatism: `min_observations 10, min_strong 5` before `should_change=true`. GTM_INTENT feeds `Observation(what, source, n)` into it; `LEARN` stage decides to act.

---
*Trace: `app/services/hiring_signals.py`, `intent_engine.py`, `scoring.py`, `learning_loop.py`, `opportunity.py` — all deterministic. No LLM in scoring.*
