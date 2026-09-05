# 07 — Opportunity (Research + Opportunity Service)

## Role
Bridge from who/what to why now — synthesize business understanding + signals + decision maker into evidence-backed hypothesis and scored opportunity with locked offer. Services: `services/research.py:330` + `services/opportunity.py:238`.

## Research Service
**File:** `services/research.py:330` `research_company(company_id) → ResearchReport`

### Assemble Evidence
`_assemble_evidence(company_id, workspace_id):52` collects:
- Active hiring_signals (`research.py:57` ORDER BY signal_score DESC) → source_ref `hiring_signal:{id}`, type hiring_signal, content title/role/intent/pain/fit/score/desc[:2000]
- Qualified job_postings nurture/qualified (`research.py:82`) → job_description, title/intent/rationale/responsibilities
- Company business_data 8 fields (`research.py:114` business_name, vertical, city/state, employee_estimate, number_of_locations, owner_name, google_rating, review_count)
- Website_findings (`research.py:127`) and tech_signals (`research.py:136`) if present, reviews rating/count (`research.py:145`).

### LLM Call
`_call_llm_research:181` → `_build_user_prompt:159` formats `Company: name vertical city state website` + `EVIDENCE: [i] source_ref (type): json[:1500]`. System: `RESEARCH_SYSTEM_PROMPT:20` requires JSON {summary, primary_problem, reason_now, recommended_offer, evidence[] with claim/source_ref/source_type}. Uses strong tier (`LLMProvider complete model_tier="strong":190`). On missing LLM or exception → `_fallback_research:207` deterministic: primary_problem "High inbound call volume...", recommend from hiring_signal orbit_product_fit split comma.

### QC Gate
`_validate_research_report:258` checks per evidence: claim non-empty, source_ref exists in assembled, source_type ∈ RESEARCH_EVIDENCE_TYPES (`research.py:30` 6 types), keyword heuristic `claim_words len>3 ∈ source_content lower else hallucination:285`. Returns (passed, failures).

`_repair_research_report:292` once if fails, re-prompts with `Previous report failed: failures + evidence sources` via strong tier; on LLM missing returns original.

`validate_research_report:370` public wrapper re-assembles evidence for external use.

### Persist
After QC (including one repair attempt, still logs error if fails `research.py:352`), INSERT research_reports (`research.py:355` workspace_id, company_id, summary, primary_problem, reason_now, recommended_offer, evidence jsonb, model_used). **No dedupe** — every call inserts new row; `_get_latest_research` reads latest only (`opportunity.py:110`). Storage drift PARTIALLY.

**Owns:** evidence convergence + citations + LLM hypothesis + QC fail-closed.
**Not:** scoring composite (opportunity.py), contact finding (enrichment), send gate.

**Missing-data:** no company → ValueError; no LLM → fallback generic violates fail-closed "never guess" if used downstream (canonical `canonical.ts:382` flag). Invalid source_ref → validation fails but still written.

## Opportunity Service
**File:** `services/opportunity.py:238` `compute_opportunity_score(company_id) → OpportunityBreakdown`

### 6 Components (total 0-100)
Weights `DEFAULT_OPPORTUNITY_WEIGHTS:23` override via `system_flags opportunity_weights:103`
- icp_fit 25 = icp_fit_score normalized/10*25 (`opportunity.py:267`)
- intent 30 = top active hiring_signal score *0.3 capped 30 if high/medium value else 0 (`opportunity.py:273`)
- severity 20 = `_compute_severity:200` keyword scan primary_problem: critical/severe/crisis→20, struggling/missed/unanswered→12, could improve/optimize→5, else offer in ai_receptionist etc→12 else 5 (`opportunity.py:204`). From research report.
- contactability 10 = `_get_contactability:169` verified email?10 : owner 5 + phone 3 capped 10
- recency 10 = `_compute_recency:219` max freshness_multiplier*10 among active signals (`opportunity.py:225`)
- history 5 = `_compute_history:229` min(5, meetings*1.5+past_customers*3) via `meetings` and `opportunities won` (`opportunity.py:149`).

Total sum clamped 0-100 (`opportunity.py:302`). Tier via `TIER_THRESHOLDS:39` A+90 A80 B65 C50 D0 first match descending loop (`opportunity.py:304`). Action `ACTION_MAPPING:47` A+→call_email_linkedin etc.

### Pitch Selection
- Start `recommended_pitch = research.recommended_offer` or ai_receptionist (`opportunity.py:316`).
- Fallback PAIN_TO_OFFER (`opportunity.py:67` 8 keys) scanning problem lower for pain substring (`opportunity.py:321`).
- Override with signal-based `SIGNAL_TYPE_TO_OFFER:55` per role_category if high/medium value (`opportunity.py:327`).

### Persistence
`_write_opportunity_score:361` INSERT scores (workspace_id, lead_id, score_type opportunity, score total, components json, tier, recommended_action, pitch, primary_problem, reason_now). Requires lead_id from `_get_lead_for_company:139` (latest lead for company) — if none, score not written (return early `opportunity.py:362`).

### EMV
`compute_emv:379` `EMV = p_reply * p_meeting * est_customer_value` defaults `DEFAULT_P_REPLY 0.05` `P_MEETING 0.30` `CUSTOMER_VALUE 297 MRR` (`opportunity.py:78`). p_meeting/value query opportunities avg value_mrr, but p_reply stub still 0.05 (`opportunity.py:390` todo pass). Stores scores emv as int(emv*100) basis points (`opportunity.py:433`) static $4.45 until learning loop plugged PARTIALLY.

### Circular & Cap Pitfalls
- Severity scans primary_problem text which research LLM invented from signals → loop severity→opportunity→research (canonical `canonical.ts:381`).
- Contactability caps 10 with verified early return 10, but wrapper `min(weight, contactability)` uses weight10 → binary not weighted (`canonical.ts:381`).
- p_reply static → EMV not learning.

## Contracts Preserve
- Research evidence[] must have claim+source_ref+source_type ∈ 6; every claim traces to assembled evidence (QC).
- Opportunity must map pain→offer via PAIN_TO_OFFER existence; mismatch flagged downstream but here locked.
- Scores table tier/pitch must stay consistent with research (do not diverge).

## Safe vs Dangerous
- Safe: tune DEFAULT_OPPORTUNITY_WEIGHTS via flag, add tech pattern to website intel, extend SEVERITY keywords.
- Dangerous: remove QC repair loop, change tier thresholds without updating action mapping, bypass _write_opportunity_score transaction, make research dedupe delete old reports.

## Safe vs Dangerous (opportunity)
- Safe: adjust opportunity_weights via flag, extend SEVERITY keywords, add new pain→offer hint.
- Dangerous: skip QC _validate_research_report, delete old research_reports dedupe, change EMV defaults without learning plug.

## What Must Be Tested After Modification
- `pytest tests/test_opportunity_research.py -v`; exercise `research_company` + `validate_research_report` + `compute_opportunity_score` → tier + scores row; check `GET /gtm/leads/{id}/why`.

## Before/After
- Before: read `services/research.py:52` + `services/opportunity.py:238` + `services/website_intel.py:222`.
- After: `pytest tests/test_opportunity_research.py -v`; call `research_company` on fixture company, assert report.evidence non-empty, validate via `validate_research_report`; call `compute_opportunity_score`, assert tier within A+/D and scores row created; check `GET /gtm/leads/{id}/why` reflects contributions.

## Examples
- ABC HVAC: hiring dispatcher high_value, website no chatbot, research fallback pain "High inbound..." → severity medium 12 + icp 20 + intent 25 + contact 10 + recency 10 + history 0 =77 → tier B (but simulation says 85 A due to different weights/stack) see `simulation.ts:125` composite breakdown and `opportunity.py:338` breakdown.
- Fallback research: `_fallback_research:207` cites first hiring_signal pain_hypothesis and orbit_product_fit.

## Related
- Upstream: website_intel provides tech_signals, hiring_signals provides signals.
- Downstream: pipeline DECIDE reads opportunity.recommended_offer + primary_problem; outbound gate checks contactability; qa_service validates research via `run_research_qa:376`.
