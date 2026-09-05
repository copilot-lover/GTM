# STAGE 05 — BUILD OPPORTUNITY (Research → Profile → Angle)

> **IETM teaching doc · Stage 5 of 12 · Progressive disclosure: 🟢 Everyone → 🟡 Operator → 🔴 Builder**
> Canonical: `frontend/src/gtm/canonical.ts:336` (`id:"opportunity", index:5`) · Simulation: `frontend/src/gtm/simulation.ts:114` · Research: `backend/app/services/research.py:330` · Opportunity: `backend/app/services/opportunity.py:238`

---

# WHAT IS IT?

> 🟢 **BASIC**

**OPPORTUNITY** combines everything learned into a **reasoned, evidence-based hypothesis — not a facts dump**. It's the single structured profile that answers:

*Who is it? What's happening? What problem probably exists? Why is it relevant to Orbit? Why now? What's the strongest angle? Who should we talk to? What's the evidence? What should we NOT assume?*

> 🟡 The opportunity profile is **the bridge from research to action** — the only place downstream stages (`DECIDE`, `GATE`, `OUTREACH`, even `BOOK`'s handoff packet) are allowed to cite as their source of truth.

---

# WHY DOES IT EXIST?

> 🟢 Without convergence, outreach is generic. "Hey HVAC owner, learn about AI?" is a generic pitch lobbed at anyone with a license. With a profile, **every message has a reason to exist** and every handoff gives a salesperson *context for a relevant first call, not a cold one* (`canonical.ts:347`).

Evidence without a hypothesis is a data dump. A hypothesis without evidence is a guess. This stage **forces them together with citations**.

---

# WHAT GOES IN?

> 🟡 Three buckets converged (`frontend/src/gtm/canonical.ts:348`):

| Bucket | Fields | Produced by |
|--------|--------|-------------|
| **Company + person** | `business_name, city, state, vertical, owner_name, phone, verified email`, `owner_operator_confidence` | `FIND` → `UNDERSTAND` → `IDENTIFY` |
| **Business signals** | `website_findings` (booking gaps, chat missing, after_hours), `tech_signals` (servicetitan etc.), `google_rating/review_count`, `hiring_signals.pain_hypothesis` | `website_intel.py:222`, `hiring_signals.py:342` |
| **Timing + confidence** | `signal_score, freshness_multiplier, intent_category, priority_score, tier`, `previous interactions` | `hiring_signals.py:188`, `intent_engine.py:181`, `opportunity.py:238` |
| **Orbit catalog** | 8 offers `ai_receptionist, ai_phone_receptionist, voice_ai_receptionist, missed_call_recovery, after_hours_booking, lead_qualification, web_lead_handling, website_conversion…` (`scoring.py:24`) | Catalog is the constrained vocabulary `RESEARCH` must pick from |

> 🟢 All inputs arrive as **observed facts with source_refs** — not claims. Claims are what this stage produces and must back with citations.

---

# WHAT HAPPENS?

> 🟡 Two steps — research, then coalesce into an opportunity score:

**Step 1 — Research (`research.py:330`):**
1. `_assemble_evidence(company_id, workspace_id):52` collects:
   - `hiring_signals` (active, `ORDER BY signal_score DESC`)
   - `job_postings` (`qualified|nurture, ORDER BY intent_score DESC`)
   - `companies` business data (`business_name, vertical, city…`)
   - `companies.website_findings` (source_type `website`)
   - `companies.tech_signals` (source_type `tech_signal`)
   - Reviews (`google_rating, review_count`) as `review`
2. `_call_llm_research:181` forms `RESEARCH_SYSTEM_PROMPT:20` ("MUST have {claim, source_ref, source_type in hiring_signal|job_description|website|tech_signal|review|business_data} — NO INVENTED FACTS"), builds `company + evidence[]` user prompt (`_build_user_prompt:159`), calls `LLMProvider.complete(..., model_tier="strong")` (`providers/base.py`), parses `ResearchReport(summary, primary_problem, reason_now, recommended_offer, evidence[], model_used)`.
3. `_validate_research_report:258` checks: `claim non-empty, source_ref ∈ assembled, source_type ∈ RESEARCH_EVIDENCE_TYPES, claim keywords ∈ source text` (heuristic), records `failures[]`.
4. If failures → `_repair_research_report:292` re-prompts LLM once with failures + evidence sources → re-validate; if still failing → `log.error` but still writes (with failures recorded).
5. Writes `research_reports(workspace_id, company_id, summary, primary_problem, reason_now, recommended_offer, evidence jsonb, model_used)` (`research.py:355`) — **one row per call, no dedupe** (`canonical.ts:375`).
6. Fallback if no LLM: `_fallback_research:207` ([deterministic fallback is generic](#what-can-go-wrong)).

**Step 2 — Opportunity score (`opportunity.py:238` `compute_opportunity_score`):**
Assembles 6 components (weights from `opportunity_weights` flag or `DEFAULT_OPPORTUNITY_WEIGHTS:23`):

| Component | Max | How derived |
|-----------|-----|-------------|
| `icp_fit` | 25 | `(icp_fit_score 0-10 /10 * icp_fit_weight)` via `scoring.icp_fit_score` derived from `companies.number_of_locations==1` etc. (`opportunity.py:250`) |
| `intent` | 30 | `signal_score *0.3` if `intent_category high|medium` (`opportunity.py:274`) |
| `severity` | 20 | heuristic scan of `research.primary_problem` text for keywords (`opportunity._compute_severity:200` — critical/severe→high, missed/unanswered→medium, optimize→low) |
| `contactability` | 10 | verified email →10 else owner+5/phone+3 (`opportunity._get_contactability:169`, cap 10) |
| `recency` | 10 | max `freshness_multiplier*10` across active signals (`opportunity._compute_recency:219`) |
| `history` | 5 | `min(5, meetings*1.5 + customers*3)` (`opportunity._compute_history:229`) |

`total = sum(6) clamped 0-100 → tier A+ 90, A 80, B 65, C 50, D 0` (`opportunity.TIER_THRESHOLDS:39` → `ACTION_MAPPING:47` `A+:call_email_linkedin` ... `D:do_not_contact`), plus `recommended_pitch` by `research.recommended_offer` → `PAIN_TO_OFFER:67` fallback → `SIGNAL_TYPE_TO_OFFER:55` override on high/medium signals (dispatcher→voice_ai_receptionist first), plus `compute_emv:379` (`DEFAULT_P_REPLY 0.05 * DEFAULT_P_MEETING 0.30 * DEFAULT_CUSTOMER_VALUE 297 → $4.45` basis, `opportunity.py:78`).

Writes `scores(…, score_type='opportunity', tier, recommended_action, recommended_pitch, primary_problem, reason_now)` + `scores(score_type='emv')` (`opportunity.py:361,426`).

> 🔴 `PAIN_TO_OFFER` hard rule #4 (`pipeline.apply_offer:361`): `expected = PAIN_TO_OFFER[primary_pain]` must equal `offer_id` or `PipelineError("offer-pain mismatch")` + review flag. **Link is deterministic**, not LLM choice.

---

# WHAT DECISIONS ARE MADE?

> 🟡 (`frontend/src/gtm/canonical.ts:355`)

- **Is the hypothesis credible and evidence-backed?** → else mark `low confidence`, `GATE` will `HOLD` (compliance check + `qa_service.run_research_qa:376` for stale evidence)
- **What is the strongest angle vs alternatives?** → pick one angle, note secondaries for follow-up (angle rotation list `["short follow-up different angle", "case-study", "breakup"]` in `email_service.schedule_followups:319`)
- **What should we avoid assuming?** → explicitly list `avoid_assumptions` (`ServiceTitan unknown, volume proxy not fact` for ABC HVAC) to prevent hallucination later
- **Link offer → pain deterministically:** must address recorded `primary/secondary pain` or contract error (`pipeline.PAIN_TO_OFFER:125` mapping 6 keys vs `opportunity.PAIN_TO_OFFER:67` 8 keys — both must align on ABC HVAC's `scheduling pressure → ai_receptionist`)

---

# WHAT COMES OUT?

> 🟡 Single decision packet consumed by every downstream stage:

- **Opportunity profile (structured hypothesis):** `research_reports(summary, primary_problem, reason_now, recommended_offer, evidence[{claim,source_ref,source_type}])` + `scores(tier, score, EMV, components, recommended_action, recommended_pitch)` + `Evidence bundle that DECIDE will cite verbatim` (`canonical.ts:365`)
- **Confidence + angle strength** — `evidence[]` length + `severity_component` signal
- **Avoid-assumptions list** — fixed text guardrails for draft generation
- **Offer locked to pain** — contract-checked; failure persists `qa_runs.failed_rules` for review

> Read path downstream: `research._get_latest_research:110` reads `ORDER BY created_at DESC LIMIT 1` (only latest counts — earlier rows are orphaned storage).

---

# REAL-WORLD EXAMPLE — ABC HVAC at OPPORTUNITY

> 🟢 Local HVAC, 3 areas, hiring dispatcher, weak booking:

**Business:** Growing HVAC, 3 areas, hiring dispatcher, active ads, weak booking (no chatbot, slow form).
**Likely issue:** inbound demand creating scheduling/response pressure.
**Angle:** Capture/qualify leads, reduce manual handling (AI receptionist + booking automation).
**Decision maker:** Owner — Maria Chen (from IDENTIFY).
**Confidence medium-high. Reason now:** hiring + ads = active investment + strain.

> That narrative is exactly what `frontend/src/gtm/simulation.ts:114` produces under `stage:"opportunity"`:

```
Inputs: Company + decision maker + signals + website observations
Signal chain: hiring dispatcher (fresh) + active ads + weak booking →
  likely missed calls + scheduling bottleneck
Confidence medium-high, angle strength high

Research synthesis:
  business_data: ABC HVAC, 6-10 employees, Greensboro NC, hvac vertical
  website: no chatbot, booking gap, after_hours_gap
  hiring_signal: dispatcher phone_heavy+scheduling, score 78, intent medium_value
  → research_report: primary_problem="scheduling pressure",
     reason_now="hiring + ads = active investment + strain",
     recommended_offer="ai_receptionist", evidence citations (posting URL, site audit)
Opportunity 6-component:
  icp_fit 8/10 →20pts, intent 78*0.3=23→25pts cap, severity keyword "booking/scheduling"→15pts,
  contactability verified→10pts, recency fresh 0.9→9pts, history 0 meetings→0pts
  = 79-85 → tier A (simulation shows 85), EMV $4.45 default p 0.05*0.30*297
  PAIN_TO_OFFER: scheduling pressure → AI receptionist (deterministic)
  avoid_assumptions: ServiceTitan unknown, volume proxy not fact (don't claim 50, cite "posting says 50+")
Evidence: posting URL, website_findings (mobile 62, no chatbot), ad observation
Offer: AI receptionist (matches primary pain 'missed-call pressure')
```

> Downstream pointer: `DECIDE` will open with that posting URL citation, `GATE` will judge its credibility, `BOOK` will include that packet in the `meeting.handoff briefing`.

---

# WHAT CAN GO WRONG?

> 🟡 (`frontend/src/gtm/canonical.ts:377`)

- **Circular:** `severity` heuristic keyword-scans `primary_problem` text which itself came from research → research→severity→score→research loop (no loop guard)
- **Contactability caps at 10** but wrapper `min(weight=10, contactability)` uses weight 10 → effectively binary, not weighted (`opportunity.py:286` — `min(10,10)` path)
- **`p_reply` always default 0.05** (history query passes but reply rate not computed) (`opportunity.compute_emv:389` `pass`) → `EMV` static `$4.45` — not learning from outcomes
- **`_validate` keyword overlap >3 chars false-flags paraphrased claim as hallucination** (`research._validate_research_report:285` — `matches==0` heuristic overstrict); `_fallback_research` generic "High inbound call volume…" violates fail-closed if LLM down (`research.py:209`)
- **Research→opportunity order not enforced by event** — manual; `website_intel→research` also manual, can score before research ready (no event lock)

---

# EDGE CASES

> 🟡 (`frontend/src/gtm/canonical.ts:371`)

- **Low confidence** → profile marked needs more evidence, outbound `GATE` will `HOLD` (not send) (`canonical.ts:372` — `opportunity confidence` reflected in `severity`/`intent` low → tier `C/D→do_not_contact`)
- **Contradictory evidence (strong hiring but website says closed Sundays)** → profile notes uncertainty, avoids assumption, suggests 'ask about capacity' angle (encoded in `primary_problem` nuance + `avoid_assumptions`)
- **Missing contact** → profile exists (observed pain is still real) but outreach blocked at gate with `'no verified contact'` (`outbound_gate.can_send:130` `email_verified` false → `allowed=false`)
- **Repeated research calls** → unbounded `research_reports` rows orphaned, only latest used (`research._get_latest_research:110`) — storage drift (`canonical.ts:375` known issue)

---

# WHAT HAPPENS NEXT?

> 🟢 OPPORTUNITY is the **bridge**: IDENTIFY says *who*, UNDERSTAND+QUALIFY say *worth contacting*, OPPORTUNITY synthesizes into a **single hypothesis that DECIDE turns into a message angle** (`frontend/src/gtm/canonical.ts:384`):

> Every downstream stage (**DECIDE**, **GATE**, **OUTREACH**, **BOOK**) reads this **decision packet** — it is the only artifact permitted as a source for outbound claims.

---

# WHY DOES IT MATTER?

> 🟢 Without convergence, downstream has nothing to cite. The salesperson gets **context to have a relevant first call, not a cold one** (`canonical.ts:389`). With a profile, every draft opens with evidence ("noticed you're hiring a dispatcher while promoting new areas") not generic fluff — that's why `qa_service.run_copy_qa:198` (`GENERIC_COPY` check) fails generic openers.

---

# DEEPER DETAIL (technical)

> 🔴 **BUILDER**

**Modules:**
- `backend/app/services/research.py:52` `_assemble_evidence()` — 6 source_types
- `backend/app/services/research.py:181` `_call_llm_research()` — strong tier LLM, system prompt with `RESEARCH_EVIDENCE_TYPES=6:30`
- `backend/app/services/research.py:258` `_validate_research_report()` — claim→evidence coverage + one repair (`research.py:292`)
- `backend/app/services/research.py:207` `_fallback_research()` — deterministic fallback (generic, known violate-fail-closed — flagged)
- `backend/app/services/research.py:330` `research_company()` — no dedupe per call
- `backend/app/services/opportunity.py:23` `DEFAULT_OPPORTUNITY_WEIGHTS` (25+30+20+10+10+5=100), `55` `SIGNAL_TYPE_TO_OFFER` (dispatcher→voice_ai_receptionist first), `67` `PAIN_TO_OFFER`, `238` `compute_opportunity_score()`, `379` `compute_emv()`
- `backend/app/services/scoring.py:24` `OFFER_CATALOG` (8) — catalog shared but duplicated
- Tables: `research_reports`, `scores`, `companies` — `frontend/src/gtm/canonical.ts:398`
- Agent: `GTM_RESEARCH` (not in scheduler registry — manual, `canonical.ts:398`)
- LLM tier: strong (`LLM_STRONG_MODEL` or first in `providers chain`) — `research.py:190`

**Evidence contract:**
- `RESEARCH_SYSTEM_PROMPT:20` — `{claim, source_ref, source_type}` where `source_type ∈ (hiring_signal, job_description, website, tech_signal, review, business_data)`; every claim must trace to a `source_ref` from `_assemble_evidence` — violated `source_ref` → `MISSING_EVIDENCE` critical (`qa_service.run_research_qa:413`)
- `research evidence[]` on `ResearchReport` must quote observed content, not hallucinated — QC gate `_claim_is_covered` false-positive if evidence snippet short (`qa_service._claim_is_covered:130` `text.lower() in lowered`)

**Status:**
- ✅ IMPLEMENTED — evidence assembly, research with citations + one repair, 6-component opportunity score + EMV, tier mapping, offer-pain hard rule
- 🐛 KNOWN GAPS — circular severity, contactability binary weighting, static `p_reply` 0.05 / static EMV $4.45, `_fallback_research` generic violates fail-closed, `_validate` heuristic over-strict, research dedupe missing, research→opportunity order not event-enforced — all documented in `canonical.ts:377-382`
- 🚧 PLANNED — event-order guard `research_ready` signal to gate `compute_opportunity_score` until `research_reports` row exists; `scores.tier` wiring for `intent_engine._has_tier_a` dead branch

**Simulation source:** `frontend/src/gtm/simulation.ts:114` stage `opportunity` — `abc_hvac` research + 85/A + avoid_assumptions mapping is the runnable spec for this doc's example field.

---
*Trace: `app/services/research.py`, `app/services/opportunity.py`, `app/routers/opportunity.py` — `frontend/src/gtm/canonical.ts:336`.*
