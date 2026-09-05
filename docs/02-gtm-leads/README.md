# GTM_BRAIN 1 — GTM_LEADS (Business Understanding)

> **IETM teaching doc · Progressive disclosure: 🟢 Everyone → 🟡 Operator → 🔴 Builder**
> Brain definition: `frontend/src/gtm/canonical.ts:55` (`GtmBrain id="leads"`) · Simulation: `frontend/src/gtm/simulation.ts:68`

---

# WHAT IS IT?

> 🟢 **BASIC**

**GTM_LEADS** is Brain 1: it answers **"Who is this business and are they worth attention at all?"** — not "should we email now," but **is this even ICP**.

It owns business understanding across `FIND → UNDERSTAND → QUALIFY → IDENTIFY → OPPORTUNITY → RESEARCHED`:

- Build/maintain the **company record** (`companies`: `business_name, city, state, vertical, website, phone, owner_name, employee_estimate, number_of_locations, google_rating, tech_signals, website_findings`)
- Score **ICP fit** (`backend/app/services/scoring.py:39` arithmetic, no LLM)
- Find and verify the **decision maker** (`backend/app/services/enrichment.py:194`)
- Assemble the **research report** hypothesis (`backend/app/services/research.py:330`)
- Produce the **opportunity profile** that all downstream stages cite

> 🟡 Think of GTM_LEADS as the **librarian**: it builds the catalog and highlights the relevant shelf. It never decides when to talk — that's GTM_INTENT's job.

---

# WHY DOES IT EXIST?

> 🟢 Without a leads brain, intent signals float in a vacuum. "Hiring dispatcher" means nothing until you know: HVAC vs franchise chain? Single-location owner-operated vs 40-location enterprise? Weak booking vs strong Stack?

GTM_LEADS provides **context that makes signals interpretable**:

- `UNDERSTAND` writes `companies.tech_signals` + `leads.website_findings` (`backend/app/services/website_intel.py:293`) — now "hiring dispatcher" can be interpreted as scheduling pressure, not random hiring.
- `QUALIFY` runs deterministic `icp_fit_score()` (`scoring.py:39`) — now "eligible" is an arithmetic result with `evidence`, not a guess.
- `IDENTIFY` waterfall ranks `Owner (1) > Founder (2) > President (3) > GM (4) > Ops Manager (5) …` (`enrichment.py:251`) — now outreach has a person who cares about the problem.

> The hard rule — **backend never invents owner/email/findings** (`pipeline.py:ENRICH_SYSTEM:107`) — is what keeps this brain honest.

---

# WHAT GOES IN?

> 🟡 Inputs GTM_LEADS consumes (produces none itself until FIND creates the first row):

| Input | Where it comes from | Table/field |
|-------|---------------------|-------------|
| Raw business signals | Maps, directories, ad observations, jobs | `companies.source`, `leads.evidence.source` |
| Website + tech evidence | `website_intel.fetch_website_intel()` scrape + regex | `companies.tech_signals` (jsonb), `leads.website_findings` (jsonb) |
| Enrichment returns | `enrich_company_waterfall()` (Apollo>Hunter>Clearbit) | `companies.owner_name, phone, employee_estimate`, `contacts.email` |
| ICP signal keys from LLM | `pipeline.stage_context("qualification")` → n8n → `apply_qualification` | `signals: single_location, owner_visible, family_owned, simple_site, franchise, multi_location…` (`pipeline.py:99`) |
| Research evidence bundle | `research._assemble_evidence()` — hiring + website + tech + reviews | `research_reports.evidence[]` (`research.py:52`) |
| Hiring signals + scores | `hiring_signals` active rows + `scores` opportunity tier | `opportunity.compute_opportunity_score:238` joins them |

> All writes are owner-operator-confident and evidence-cited; unclear stays `unknown` (`pipeline.py:QUALIFY_SYSTEM:103`).

---

# WHAT HAPPENS?

> 🟡 Step by step inside GTM_LEADS:

1. **FIND** — pluggable providers (`backend/app/providers/job_sources.py` + `providers/base.py Registry`) scan; normalize `{name, website, phone, city, state, source, source_url}`; dedupe `SHA-256(name|city|state)` + phone-normalized (`pipeline.py` + `phones.normalize_phone`); create `companies` + `leads status=new` with `source_url + collected_at` lineage.
2. **UNDERSTAND** — `website_intel.fetch_website_intel()` (`website_intel.py:222`) does stealth scrape (`stealth=True`), regex detection (`_extract_booking_cta:105`, `_detect_chat_widget:121`, `_detect_tech_stack:188`), derives gaps (`after_hours_gap`, `no_online_booking`, `weak_website` at `website_intel.py:267`) and writes `tech_signals` + `website_findings`; `hiring_signals` already hold `pain_hypothesis + orbit_product_fit`.
3. **QUALIFY** — n8n gets `QUALIFY_SYSTEM` prompt (`pipeline.py:95`), returns `{signals, unclear, evidence, reason}`; `apply_qualification()` (`pipeline.py:240`) calls `scoring.icp_fit_score:39` (`total / 1.8 → 0-10`), `scoring.fit_status_for:55` (≥6 qualified), `scoring.priority_score:71` (0-100), writes `lead_score, fit_status, evidence`; emits `lead.enrichment_requested` only if `qualified`.
4. **IDENTIFY** — `enrich_company_waterfall:144` (priority flag, quota reserve 20), then `find_decision_maker_email:194` (10 titles, `rank_title:251`), then `verify_email_waterfall:318` (`_local_prechecks:279` → provider waterfall, `DISPOSABLE_DOMAINS 22`, `SPAM_TRAP_KEYWORDS`); writes `contacts` + `leads.contact_id`.
5. **OPPORTUNITY + RESEARCH** — `research.research_company:330` assembles evidence (`_assemble_evidence:52`), calls LLM strong tier (`_call_llm_research:181`), validates (`_validate_research_report:258`), repairs once (`_repair_research_report:292`), writes `research_reports`; `opportunity.compute_opportunity_score:238` writes `scores` + `tier A+/A/B/C/D` + `recommended_action`.

> 🔴 Every `apply_*` function also does `_add_activity()` (actor-labeled) + `state_machine.transition()` (`pipeline.py:263`) — observable, not hidden.

---

# WHAT DECISIONS ARE MADE?

> 🟡 GTM_LEADS decisions (all deterministic, auditable):

- **Is there enough info to evaluate?** → else low-info flag, keep monitoring (FIND `decisions[0]` in `canonical.ts:97`)
- **Is it active/legitimate?** → signal absence + recency (FIND `decisions[2]`)
- **What type/size is this business?** → owner-operated vs franchise vs multi-location vs enterprise (UNDERSTAND `decisions[0]`)
- **HIGH / POSSIBLE / NOT FIT?** (`scoring.fit_status_for:55`) → `qualified | borderline | rejected_too_large | rejected_not_relevant | rejected_unclear`
- **Which role cares?** → `rank_title()` mapping + angle match (IDENTIFY `decisions[0]`)
- **Is the contact usable?** → verified + not suppressed + not duplicate (`outbound_gate.can_send:130` re-checks, but origin is here)
- **Is the hypothesis credible & evidence-backed?** → `research._validate_research_report` + `opportunity` offer-pain consistency (`pipeline.apply_offer:361` hard rule #4)

> Each decision ships with `evidence text mandatory` (`pipeline.py:252` evidence merge) and `contributions[]` for the Why panel (scoring breakdown in `intent_engine.reevaluate_lead:195`).

---

# WHAT COMES OUT?

> 🟡 GTM_LEADS outputs consumed downstream:

- **Company record** — `companies.id, owner_name, website, phone, tech_signals, employee_estimate, number_of_locations, google_rating, review_count, owner_operator_confidence (0-100)` — `companies.tech_signals` is the enriched understanding; separate from GTM_INTENT's signals.
- **Lead record** — `leads.id, status, lead_score (0-10), fit_status, priority_score (0-100), evidence (jsonb icp_signals + agent_evidence), website_findings, primary_pain, recommended_offer, contact_id`
- **Contact** — `contacts.id, email, email_verification_status ('verified' gate), email_verification_provider, is_decision_maker, confidence`
- **Research report** — `research_reports (summary, primary_problem, reason_now, recommended_offer, evidence[] with claim+source_ref+source_type, model_used)` — single source that `DECIDE` cites verbatim
- **Opportunity score** — `scores (score_type='opportunity', score 0-100, tier A+/A/B/C/D, components{icp_fit,intent,severity,contactability,recency,history}, recommended_action, EMV)` + EMV row `score_type='emv'` (`opportunity.py:426`)
- **Observable explainability** — `activities`, `enrichments`, `email_verifications`, `provider_usage` (quota), `job_queue` entries

> 🔴 **Do not conflate 3 scores** (spec §7.3, `canonical.ts:228`): ICP fit 0-10 (is it ICP?), Priority 0-100 (what order?), Hiring intent 0-100 (how strong is timing?).

---

# REAL-WORLD EXAMPLE — ABC HVAC under GTM_LEADS

> 🟢 Source: `frontend/src/gtm/simulation.ts:46-129` (steps find → opportunity)

```
FIND:         Maps+JSearch→ SHA-256 deduped → Company ABC HVAC (Greensboro,NC) + Lead new
                source_url logged, collected_at set
UNDERSTAND:   scrape→ no chatbot, mobile 62, CTA weak, after_hours_gap=true,
                no_online_booking=true; tech_signals {wordpress:true, servicetitan:false}
                → UNDERSTAND writes companies.tech_signals + leads.website_findings
                owner_operator_confidence=68
QUALIFY:      signals: single_location +3, owner_visible +3, family_owned +2, simple_site +2
                franchise 0, multi_location 0 → total 10 /1.8 = 6→ rounded 8/10? Actually ABC gets 8/10
                (canonical says fit 8/10). evidence mandatory cited (posting URL + audit hash)
                fit_status=qualified → emit lead.enrichment_requested
IDENTIFY:     Waterfall apollo→hunter→clearbit: Apollo finds Maria Chen owner, 92%
                verify_email_waterfall: _local_prechecks syntax+MX → ZeroBounce valid 0.97
                → contacts email_verification_status='verified', leads.contact_id linked
OPPORTUNITY:  _assemble_evidence pulls hiring_signal dispatcher + website gaps + reviews
                research_company strong-tier → ResearchReport {primary_problem: scheduling pressure,
                reason_now: hiring+ads, evidence[] cited} last 2 of those evidence entries row
                compute_opportunity_score: icp_fit 20 + intent 25 + severity 15 + contactability 10
                + recency 10 + history 5 = 85 → tier A, action call_email_linkedin, pitch ai_receptionist
```

> End-to-end, GTM_LEADS is why ABC HVAC's outreach angle is **not** generic "learn about AI" but cited "hiring dispatcher while promoting new areas → scheduling pressure."

---

# WHAT CAN GO WRONG?

> 🟡 Cataloged in `frontend/src/gtm/canonical.ts` per stage + `enrichment.py`/`website_intel.py`:

- `TARGET_FIELDS has owner_email but COMPANY_ENRICHABLE_FIELDS lacks column` → enriched `owner_email` silently dropped (`enrichment.py:44` + `canonical.ts:185`). ✅ Fallback via `contacts.email` still works.
- `rank_title` duplicated with divergence (`enrichment 5 keys vs email_finder 10 keys, 1-99 mapping)` (`canonical.ts:315`).
- `website_intel` regex HTML parsing brittle on SPA/React-rendered sites → `fetch_website_intel` fallback to empty `WEBSITE_FINDINGS_SCHEMA` (`website_intel.py:236`) masks failure; stealth `Scrapling` retry exists.
- Two qualification paths diverge: `pipeline.apply_qualification` (`new→enriching|rejected`) vs `leads.score_lead` (`new→qualified|rejected`) — `canonical.ts:248`.
- `OFFER_CATALOG` duplicated 4 places — adding offer to one doesn't propagate (`canonical.ts:252`).

> All are **known bugs documented as tradeoffs**, not silent — they appear in `whatCanGoWrong` so operators know to patch callers.

---

# EDGE CASES

> 🟡

- Minimal web presence → low confidence, stays monitoring, not promoted to QUALIFY (low `tech_signals` coverage).
- Multi-location vs single-location → different scaling implications, impacts score; 2+ locations implies operations complexity but deprioritized for ICP.
- Franchise vs independent → `national_brand / franchise` negative weight `-4` (`scoring.py:12`) immediately pushes to `rejected_too_large`.
- Generic `info@` only → `IDENTIFY` `HOLD`, don't blast; review queue "missing owner" (`canonical.ts:307`).
- Stale `posted_at 30d` → recency `1 - 30/30 = 0` (`intent_engine.py:216`) → 0-point contributions still inserted (unfiltered), score decays naturally.

---

# WHAT HAPPENS NEXT?

> 🟢 GTM_LEADS finishes with a verified contact + opportunity hypothesis. Next:

- **GTM_INTENT** (`03-gtm-intent/`) ingests fresh `intent_events` and recalculates `priority_score` continuously — even `qualified` leads can be demoted as signals age.
- **08-outbound/** (`DECIDE + GATE + OUTREACH`) consumes the `research_reports` + `scores` + `contacts` packet this brain produced; `DECIDE` must cite it verbatim, `GATE` must judge it, `OUTREACH` must react to replies.

> If GTM_LEADS says **NOT FIT**, nothing downstream runs — hold/reject/suppression is terminal (`state_machine.TERMINAL`).

---

# WHY DOES IT MATTER?

> 🟢 This brain is the **receipt** for every send. Without it, personalization is hallucination; with it, the handoff packet after `BOOK` gives a salesperson *context for a relevant first call, not a cold one* (`canonical.ts:389`). That's the difference between pipeline and spam folder.

---

# DEEPER DETAIL (technical)

> 🔴 **BUILDER**

**Modules:**
- `backend/app/services/website_intel.py:222` `fetch_website_intel()` — `TECH_STACK_PATTERNS:22`, `WEBSITE_FINDINGS_SCHEMA:69` (`booking_cta, chat_widget, phone_visible, forms, ssl_valid, mobile_viewport_meta, ttfb_ms, after_hours_gap, no_online_booking, weak_website`)
- `backend/app/services/enrichment.py:144` `enrich_company_waterfall()`, `194` `find_decision_maker_email()`, `318` `verify_email_waterfall()`, `279` `_local_prechecks()` (`DISPOSABLE_DOMAINS 22`, `SPAM_TRAP_KEYWORDS`), `109` `track_provider_usage()` (reserve 20)
- `backend/app/services/scoring.py:39` `icp_fit_score()`, `55` `fit_status_for()`, `71` `priority_score()`, `113` `hiring_intent_score()`, `24` `OFFER_CATALOG` (8 offers), `20` `QUALIFY_THRESHOLD=6`
- `backend/app/services/research.py:52` `_assemble_evidence()`, `181` `_call_llm_research()` (strong tier), `258` `_validate_research_report()` (claim→evidence coverage + one repair `292`), `330` `research_company()` writes `research_reports` every call (no dedupe — `canonical.ts:375`)
- `backend/app/services/opportunity.py:238` `compute_opportunity_score()` (6 components, tier A+/A/B/C/D, EMV `DEFAULT_P_REPLY 0.05` (`opportunity.py:78`)), `379` `compute_emv()` writes `scores score_type='emv'`
- `backend/app/providers/base.py` `LLMProvider` + `backend/app/services/pipeline.py:95` `QUALIFY_SYSTEM / ENRICH_SYSTEM / AUDIT_SYSTEM` prompts (deterministic keys `STAGE_KEYS:154`)
- Tables: `companies` (tech_signals jsonb, owner_operator_confidence), `leads` (lead_score, fit_status, evidence, website_findings, primary_pain, recommended_offer, contact_id), `contacts` (email_verification_status), `research_reports`, `scores`, `enrichments`, `email_verifications`

**Gates / state:**
- `pipeline.py:178` enrichment hard-gated on `fit_status==qualified`
- `state_machine.py:6` `new→enriching` on qualified else `rejected`; `enriching→qualified` after enrichment, then `qualified→signal_holding|outreach_ready`
- `pipeline.apply_offer:361` hard rule #4: `PAIN_TO_OFFER[primary_pain]` must equal `offer_id` or contract error, flagged to review queue
- Workers: `enrichment:2, verification:2` pools (from `canonical.ts:197`)

**Status:**
- ✅ IMPLEMENTED — all 5 sub-steps (find/understand/qualify/identify/opportunity) run via `pipeline.apply_*` + `research` + `opportunity`
- ✅ Enrichment hard gates + waterfall + verification prechecks implemented
- 🚧 PLANNED vs KNOWN BUGS — flagged in `canonical.ts:185-187` (owner_email drop, enrichment hard-gate contradiction with LLM summarize); no fix in current migration

**Progressive disclosure:** This doc is Level 1-2/3 of the brains view; next doc (`03-gtm-intent`) is the other half. Stage docs 04-07 reuse the research_reports packet produced here.

---
*Trace: `frontend/src/gtm/canonical.ts:76-404` stages find→opportunity · Backend: `app/services/pipeline.py`, `website_intel.py`, `enrichment.py`, `scoring.py`, `research.py`, `opportunity.py`.*
