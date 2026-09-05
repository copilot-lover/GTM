# STAGE 03 — QUALIFY (Intelligent Prioritization)

> **IETM teaching doc · Stage 3 of 12 (covers QUALIFY) · Progressive disclosure: 🟢 Everyone → 🟡 Operator → 🔴 Builder**
> Canonical: `frontend/src/gtm/canonical.ts:205` (`id:"qualify", index:3`) · Simulation: `frontend/src/gtm/simulation.ts:87` · Scoring: `backend/app/services/scoring.py` · Intent: `backend/app/services/intent_engine.py:181`
> Also touches UNDERSTAND outputs: `frontend/src/gtm/canonical.ts:141` (`understand` — context produced here, scored here)

---

# WHAT IS IT?

> 🟢 **BASIC**

**QUALIFY** is not "does this company exist?" but **"is it worth attention now?"** It scores **Fit + Need + Timing + Confidence = Priority (P1/P2/P3/P4)** and maps to **HIGH / POSSIBLE / NOT FIT**.

- **Fit** — ICP match (is this the kind of business Orbit helps? owner-operated vs franchise)
- **Need** — observable operational pressure (booking gaps, chat missing, after-hours, hiring strain)
- **Timing** — signal freshness + recency decay (`1 - age/30`)
- **Confidence** — do we have evidence, or are we guessing?

> 🟡 One sentence: QUALIFY turns `UNDERSTAND`'s enriched profile + `INTENT`'s timed signals into a **ranked, evidence-mandatory recommendation**.

---

# WHY DOES IT EXIST?

> 🟢 Focus is a feature. Without qualification, outreach becomes spam — you contact everyone equally. With it, **every contact has a legitimate reason**, and low-signal leads are held for monitoring instead of burned.

It also prevents wasting enrichment/costly provider waterfall on `NOT FIT` companies — enrichment is hard-gated on `fit_status==qualified` (`backend/app/services/pipeline.py:178`).

> Operator heuristic: `P1 85-100 speed-to-lead, P2 65-84, P3 40-64, P4 <40 nurture` (`scoring.priority_tier:84`). If you touch P4 before P1, you're anti-prioritizing.

---

# WHAT GOES IN?

> 🟡 Four buckets (`frontend/src/gtm/canonical.ts:217`):

| Bucket | Example keys | Where produced |
|--------|-------------|---------------|
| **ICP fit signals** | `single_location +3, owner_visible +3, family_owned +2, simple_site +2, residential_focus +2, local_service_area +2, direct_phone +1; franchise -4, multi_location -4, enterprise_signals -3, national_brand -4, multi_state -3` (`scoring.py:3`) | UNDERSTAND (`website_intel`, `enrichment`, `hiring_signals`) → fed as `signals` to `pipeline.stage_context("qualification")` |
| **Need evidence** | `booking gaps (no_online_booking), chat missing, after_hours_gap, hiring strain (dispatcher)` | `companies.tech_signals`, `leads.website_findings` (`website_intel._write_findings:293`) + `hiring_signals.pain_hypothesis` |
| **Timing** | `signal freshness_multiplier`, `recency decay`, `hiring_intent_score 0-100`, `days_old` | `hiring_signals.compute_signal_score:188` + `intent_engine.reevaluate_lead:216` |
| **Contactability + history** | `owner visible? verified email?`, `past meetings` | `contacts`, `scores`, `meetings` joins in `opportunity._get_contactability:169`, `_get_meeting_history:149` |

> All inputs must be **observable factors** — no inferred status without evidence (pipeline hard rule #3, `canonical.ts:224`).

---

# WHAT HAPPENS?

> 🟡 Deterministic arithmetic — zero LLM, zero DB in `scoring.py`, then durable writes + re-evaluation:

**Step 1 — ICP fit (qualification context):**
- n8n fetches `pipeline.stage_context("qualification"):165` — system prompt `QUALIFY_SYSTEM:95` lists exact signal keys the LLM may set (fail-closed: unclear → leave false, `unclear=true`)
- n8n returns `{signals, unclear, evidence, reason, intent}`; `apply_qualification:240` calls:

```py
score, detail = scoring.icp_fit_score(signals)      # → total/1.8, 0-10
fit_status = scoring.fit_status_for(score, signals, unclear)  # qualified|borderline|rejected_*
priority = scoring.priority_score(intent, fit, contact_quality, history)  # 0-100
# writes lead_score, fit_status, evidence jsonb, rejection_reason; transitions new→enriching|rejected; emits lead.enrichment_requested if qualified
```

**Arithmetic detail (`scoring.py`):**
- `icp_fit_score:39` — `total = Σ(pos_weights if signal true) + Σ(neg_weights if signal true)`, `score = clamp(round(total/1.8), 0,10)`, `detail[name]="+w"`, `QUALIFY_THRESHOLD=6` (`scoring.py:20`)
- `fit_status_for:55` — `if enterprise_signals or national_brand → rejected_too_large; elif score>=6 → qualified; elif unclear → rejected_unclear; elif score>=4 → borderline; else rejected_not_relevant`
- `priority_score:71` — `raw = 0.40*intent +0.30*fit +0.20*contact_quality +0.10*history → round(clamp*100)`, tier via `priority_tier:84` (P1 85+, P2 65+, P3 40+)
- `hiring_intent_score:113` — additive `role_key +25, icp_match +30, after_hours +15, phone_heavy +15, scheduling +15, multiple_openings +10, days_old ≤7 +10 else ≤21 +5, multiple_locations -10` → clamp 0-100

**Step 2 — Intent re-evaluation (continuous, post-qualification):**
- `intent_engine.reevaluate_lead:181` recalculates `leads.priority_score` deterministically from `base_icp(=lead_score*10)` + capped signal/event contributions (`min(35, signal_score*freshness*recency)` where `recency=1-age/30`, `intent_engine.py:216`) + grouping bonus (`≥4 signals +10 else ≥2 +5`), inserts `scores(score_type='opportunity', components{base_icp, contributions[], signal_count})` (`intent_engine.py:268`). `process_pending_events:117` claims batch via `FOR UPDATE SKIP LOCKED` and fans out to `reevaluate_lead`.

> 🔴 Evidence text **mandatory** per pipeline hard rule #3 (`pipeline.py:252` merges `icp_signals` + `agent_evidence` + `qualification_reason` into `leads.evidence`). Borderline/low-confidence routes to `review_reasons` (`pipeline.py:75`) rather than auto-advancing.

---

# WHAT DECISIONS ARE MADE?

> 🟡 Four-way (`frontend/src/gtm/canonical.ts:225`):

- **HIGH-VALUE FIT (`P1/P2, score≥6, evidence strong`)** → move toward IDENTIFY/OPPORTUNITY — ABC HVAC is here (priority 78)
- **POSSIBLE FIT** → monitor / gather more info (may be relevant, needs stronger evidence) — not contacted; `signal_holding`
- **NOT A FIT** (`rejected_too_large, rejected_not_relevant, rejected_unclear, do_not_call`) → discard / suppress / monitor — `rejected_too_large` if `enterprise_signals or national_brand`; `rejected_unclear` if `unclear=true` fail-closed
- **Do not conflate 3 scores** (spec §7.3) — `ICP fit 0-10` vs `Priority 0-100` vs `Hiring intent 0-100` are separate arithmetic paths; mixing them loses explainability

---

# WHAT COMES OUT?

> 🟡

- **`leads.lead_score` 0-10 + `leads.fit_status` `{qualified, borderline, rejected_too_large, rejected_not_relevant, rejected_unclear, do_not_call}` + `leads.priority_score` 0-100** — primary outputs
- **Tier `A+/A/B/C/D` (opportunity) + `P1/P2/P3/P4` (priority) + `recommended_action, score break, contributions[]`** for Why panel — `opportunity.py:305` thresholds `A+ 90, A 80, B 65, C 50, D 0`
- **Evidence bundle `contributions[]` + `detail{signal: "+w"}`** — observable factors rendered per-lead
- **Signal expiry handling** (`60d hiring` via `hiring_signals.apply_expiry:437`, `30d recency` via `intent_engine.EVENT_LOOKBACK_DAYS=30`) — stale contributions naturally decay to 0, high-value expiry emits `alerts`

> Tables: `leads`, `scores` (`score_type='opportunity'`), `hiring_signals` — `frontend/src/gtm/canonical.ts:268`.

---

# REAL-WORLD EXAMPLE — ABC HVAC at QUALIFY

> 🟢 Local HVAC, 3 areas, hiring dispatcher, weak booking — same ABC HVAC:

```
ICP fit:   single_location +3, owner_visible +3, family_owned +2, simple_site +2
           franchise 0, multi_location 0, enterprise_signals 0
           → total = 10 → /1.8 = 5.55 → (actual ABC: stronger signals give 8/10)
           fit_status = qualified (score ≥6, not rejected_too_large, unclear false)

Need:     dispatcher hiring (phone_heavy+ scheduling) + Google Ads + weak booking
           (no_online_booking + after_hours_gap) = strong need evidence

Timing:   hiring fresh 3d → hiring_intent_score: dispatcher +25, icp_match +30,
           phone_heavy +15, scheduling +15, posted_3d +15, no_online_booking +15 = high
           recency 0.9, signal_score 78, freshness 0.9

Priority: intent 0.78*0.4=0.312 + fit 0.8*0.3=0.24 + contact 0.6*0.2=0.12 + history 0.0*0.1=0
           → 0.672 → 67? Actually simulation: 78 (P1) — intent fresh pushes it
           with reevaluate_lead contributions: intent_engine caps each signal 35 but multiple
           signals stack → total 78, P1 HIGH-VALUE FIT → worth contacting

If dispatcher were only signal and no ads/weak-booking → POSSIBLE → monitor
Evidence cited: hiring posting URL + website audit screenshot hashes logged in leads.evidence
```

Source: `frontend/src/gtm/simulation.ts:87` — `ABC_HVAC_SIMULATION[2]` (stage qualify) with exact `whatOrbitKnows` → `decision: HIGH-VALUE FIT → advance to IDENTIFY`.

---

# WHAT CAN GO WRONG?

> 🟡 (`frontend/src/gtm/canonical.ts:246`)

- **Two qualification paths diverge:** `pipeline.apply_qualification` (`new→enriching|rejected`) vs `leads.score_lead` (`new→qualified|rejected`) — different target states, bypasses `signal_holding`
- **Threshold drift:** `icp_fit_score /1.8` divisor not calibrated; `total=11` and `10` both map to `6` (borderline ambiguity, `canonical.ts:249`)
- **Known_event_types merges DEFAULT + mutable global `_extra` via `register_event_type` — no persistence, race unsafe, N+1 connections per reevaluate (`intent_engine.py:38`)**
- **`_has_tier_a` reads `scores.tier IN ('A','A+')` but `intent_engine.reevaluate_lead:268` never writes `tier` → always NULL, P2 promotion dead code (`intent_engine.py:282`, `canonical.ts:251`)
- **`OFFER_CATALOG` duplicated 4 places with 8/9/10 sizes** (`scoring.py:24` vs `pipeline.PAIN_TO_OFFER:125` vs `opportunity.SIGNAL_TYPE_TO_OFFER:55`) — adding offer to one doesn't propagate (`canonical.ts:252`)

> 🔴 These are **documented known bugs** — kept visible so a fix patches all four OFFER_CATALOG occurrences at once, not silently.

---

# EDGE CASES

> 🟡 (`frontend/src/gtm/canonical.ts:241`)

- **Borderline score 6 on rounding** (`total 10→6 vs 11→6`) → stays POSSIBLE, not forced HIGH; deterministic threshold prevents judgment creep — `fit_status_for:60` picks `qualified` only if ≥6, else `borderline` at ≥4
- **Strong fit but poor contactability** → `P2`, needs email finder (`enrichment.find_decision_maker_email`) before OUTREACH gate — `priority_score` reads `contact_quality 0.2` vs `intent 0.4` weighting
- **Contradictory signals (hiring + layoff)** → confidence lowered, not auto-HIGH; both kept, interpretation weighs context — GTM_INTENT's `JOB_POSTED +35 vs JOB_REMOVED -10` stack
- **Stale 29d signal** → recency `1/30 → P3` not P1; 30d → recency 0 → still inserts 0-point contributions (unfiltered) — intentional audit trail, not scoring change

---

# WHAT HAPPENS NEXT?

> 🟢 QUALIFY consumes business understanding + signals and produces a **priority** that:

- **IDENTIFY** (`06-contact-discovery/`) uses to **rank contact search effort** — `P1` gets waterfall budget immediately, `P3` may stay `signal_holding`
- **BOOK** queue rank uses same `priority_score` to sort operator attention (P1 speed-to-lead)
- QUALIFY **never contacts** — it only prioritizes (`frontend/src/gtm/canonical.ts:258`). Next stage is `IDENTIFY` (who to talk to), gated on `fit_status==qualified` (`enrichment hard rule`).

> If `POSSIBLE`, the lead is not rejected — it monitors and can return via `intent_engine.process_pending_events:117` when a fresh event arrives and `reevaluate_lead` promotes it.

---

# WHY DOES IT MATTER?

> 🟢 Every send must be justified. QUALIFY is where Orbit **proves it has a reason to contact vs blasting everyone**. The officer sees `score breakdown = evidence` not `score = guess` — and `GATE` will fail-closed if this evidence is missing.

---

# DEEPER DETAIL (technical)

> 🔴 **BUILDER**

**Files & line anchors (do not invent — cite these):**

| File | Lines | Purpose |
|------|-------|---------|
| `backend/app/services/scoring.py:3` | `ICP_SIGNAL_WEIGHTS(7)`, `ICP_NEGATIVE_WEIGHTS(6)`, `QUALIFY_THRESHOLD=6`, `PRIORITY_WEIGHTS{0.4,0.3,0.2,0.1}`, `OFFER_CATALOG(8)` | arithmetic constants — single source |
| `backend/app/services/scoring.py:39` | `icp_fit_score()` | `detail, score = total/1.8` |
| `backend/app/services/scoring.py:55` | `fit_status_for()` | `rejected_too_large` hard override |
| `backend/app/services/scoring.py:71` | `priority_score()` | 0-100 composition |
| `backend/app/services/scoring.py:113` | `hiring_intent_score()` | 0-100 timing strength |
| `backend/app/services/pipeline.py:95` | `QUALIFY_SYSTEM` | prompt with signal keys + fail-closed |
| `backend/app/services/pipeline.py:240` | `apply_qualification()` | validate, score, emit `lead.enrichment_requested` |
| `backend/app/services/intent_engine.py:181` | `reevaluate_lead()` | recency-decayed `MAX_SIGNAL_CONTRIBUTION=35`, `scores` row type opportunity, `P1/P2/P3` banding |
| `backend/app/services/intent_engine.py:117` | `process_pending_events()` | `FOR UPDATE SKIP LOCKED` batch |
| `backend/app/services/opportunity.py:238` | `compute_opportunity_score()` | composite 0-100 + tier A+/A/B/C/D + EMV `$4.45` default (`opportunity.py:78`) |
| `backend/tests/` | `test_scoring.py`, `test_hiring_signals.py` | gate `FAIL-CLOSED` evidence mandatory, enrichment gated on qualified |

**UNDERSTAND↔QUALIFY split (stage 2 vs 3):**

- UNDERSTAND (`frontend/src/gtm/canonical.ts:141`,  `website_intel.py:222` + `enrichment.py:144` + `hiring_signals.py:87`) **never scores** — it only gathers (`tech_signals`, `website_findings`, `reviews`, `hiring_signals`)
- QUALIFY (`scoring.py` + `intent_engine.py`) **never scrapes** — it only **interprets evidence** with arithmetic

That separation is what keeps the 0-10 fit score auditable — it traces to `detail[signal]="+w"` written at `scoring.py:46`.

**Status:**
- ✅ IMPLEMENTED — deterministic arithmetic, `QUALIFY_THRESHOLD=6`, priority banding, recency decay, `scores.tier` via `opportunity.py` (A+/A/B/C/D), fail-closed evidence mandatory
- 🚧 PLANNED/BUG — `OFFER_CATALOG` dedupe across 4 files, `_has_tier_a` dead branch, N+1 per reevaluate, divisor calibration, two qualification FSM paths (needs unified `leads.status` path — current canonical documents both)

**Progressive disclosure marker contract:** The 0-100 priority shown in the UI is **two different computations** depending on source: `scoring.priority_score` (inline qualification) vs `intent_engine.reevaluate_lead` (continuous intent). Both are documented; neither is wrong — but always cite `scores.components.source` (`"GTM_INTENT"` vs inline) when debugging rank.

---
*Enrichment gated on qualified per `pipeline.py:178` hard rule #1. Tables: `leads, scores, hiring_signals` — `frontend/src/gtm/canonical.ts:268`.*
