# GTM LEADS — Requirements

**Question:** WHO SHOULD ORBIT PURSUE?
**Output conceptually:** TARGET + CONTACT + QUALIFICATION + PRIORITY + RATIONALE
**Agent:** GTM_LEADS (spec §9.1 A1-A7) — `app/agents/registry.py`
**Status:** IMPLEMENTED (scoring/enrichment/pipeline) with documented PLANNED gaps.

---

## 1. Purpose

Find businesses, understand businesses, identify contacts, match company/contact, qualify, prioritize, and prepare an opportunity — before any outreach is considered.

---

## 2. Scope

- Discovery (source adapters, normalization, dedupe SHA-256 + phone)
- Understanding (website audit, tech signals, review signals, size proxy)
- Contact identification (title-ranked waterfall, verification)
- Qualification (ICP fit 0-10 with evidence, threshold ≥6)
- Prioritization (0-100 → P1-P4)
- Opportunity preparation (research report + composite)

Explicitly NOT responsible for sending outbound messages (GATE/OUTBOUND owns send). Sending is owned by GATE + email_service + scheduler + sequences.

---

## 3. Responsibilities (SHALL)

| ID | Requirement | Classification | Verification |
|----|-------------|----------------|--------------|
| LEAD-REQ-001 | The system SHALL find candidate businesses from permitted sources via pluggable provider adapters | IMPLEMENTED | `app/providers/job_sources.py`, fixtures, test `test_hiring_signals.py` |
| LEAD-REQ-002 | The system SHALL normalize candidates to `{business_name, website, phone, city, state, source, source_url}` and preserve `source_url + collected_at` lineage per NFR-8 | IMPLEMENTED | `services/pipeline.py:_load_lead` lineage, `companies.source_url` |
| LEAD-REQ-003 | The system SHALL dedupe by `SHA-256(business_name|city|state)` (pipeline) and phone-normalized E.164 (dialer) and keep best record | IMPLEMENTED | `services/pipeline.py` + `routers/companies.py` dedupe |
| LEAD-REQ-004 | The system SHALL compute ICP fit `lead_score` 0-10 via deterministic weighted signals `ICP_SIGNAL_WEIGHTS` / `NEGATIVE_WEIGHTS` / `/1.8` | IMPLEMENTED | `services/scoring.py:icp_fit_score:39` arithmetic, tests |
| LEAD-REQ-005 | The system SHALL assign `fit_status` ∈ {qualified, borderline, rejected_too_large, rejected_not_relevant, rejected_unclear} with threshold `QUALIFY_THRESHOLD=6` | IMPLEMENTED | `services/scoring.py:fit_status_for:55` |
| LEAD-REQ-006 | The system SHALL retain evidence supporting every qualification decision and fail closed (unclear→false/unclear, not guess) | IMPLEMENTED | `pipeline.QUALIFY_SYSTEM:103` fail-closed, `lead.evidence` jsonb, QA `UNSUPPORTED_FACT` |
| LEAD-REQ-007 | The system SHALL gate enrichment on `fit_status == qualified` and never enrich rejected | IMPLEMENTED | `pipeline.stage_context:179` + `apply_enrichment:281` hard-gated, hard rule #1 |
| LEAD-REQ-008 | The system SHALL identify contacts via title ranking `Owner(1) > CEO/Founder(5) > GM(10) ...` and waterfall `apollo>hunter>clearbit` with quota reserve 20 | IMPLEMENTED | `services/enrichment.py:rank_title`, `enrich_company_waterfall`, `app/providers/email_finder.py` |
| LEAD-REQ-009 | The system SHALL verify contacts via local prechecks (`DISPOSABLE_DOMAINS` 22 + `SPAM_TRAP_KEYWORDS` + DNS MX) then provider `ZeroBounce>HunterVerify` before any send | IMPLEMENTED | `services/enrichment.py:_local_prechecks`, `providers/email_verification.py` |
| LEAD-REQ-010 | The system SHALL distinguish owner-operator confidence 0-100 from fit score per FR-5 and store in `companies.owner_operator_confidence` | IMPLEMENTED | `pipeline.apply_enrichment:307`, FR-5 |
| LEAD-REQ-011 | The system SHALL compute `priority_score` 0-100 as `0.4*intent +0.3*fit +0.2*contact_quality +0.1*history` and tiers P1 85-100 / P2 65-84 / P3 40-64 / P4 <40 | IMPLEMENTED | `services/scoring.py:priority_score:71` |
| LEAD-REQ-012 | The system SHALL maintain `contacts.email_verification_status` and require `verified` before GATE allows send (via `outbound_gate`) | IMPLEMENTED | `outbound_gate:130-134` `email_verified` check, `contacts` table |
| LEAD-REQ-013 | The system SHALL check suppression (global/email/phone/company), DNC, and duplicate before qualifying contact as usable | IMPLEMENTED | `services/suppression.py:check`, `enrichment.verify_email_waterfall` |
| LEAD-REQ-014 | The system SHALL produce for downstream: TARGET + CONTACT (verified) + QUALIFICATION (fit_status+score+evidence) + PRIORITY (P1-P4) + RATIONALE (why now) | IMPLEMENTED | `services/intent_engine.reevaluate_lead:248` contributions, `scores.components` |

---

## 4. Preconditions

- Lead `workspace_id` present; RLS scoping enforced via `state_machine.transition` workspace guard.
- Pipeline `stage_context` called with correct `workspace_id, lead_id, stage` tuple.

---

## 5. Inputs

- Public business signals (Maps, directories, hiring postings, website content, ads, reviews)
- Website HTML for `website_intel.py`
- Provider responses (Apollo, Hunter, Clearbit, ZeroBounce)

---

## 6. Functional requirements detail

### 6.1 Qualification

```
INTENT weights in scoring.py:ICP_SIGNAL_WEIGHTS
  single_location +3, owner_visible +3, family_owned +2, simple_site +2, residential_focus +2, local_service_area +2, direct_phone +1
  NEGATIVE: franchise -4, multi_location -4, careers_page -3, enterprise_signals -3, national_brand -4, multi_state -3
score = clamp(0, round(total/1.8), 10)
fit_status = rejected_too_large if enterprise/national | qualified if score>=6 | rejected_unclear if unclear | borderline if >=4 else rejected_not_relevant
```

### 6.2 Enrichment waterfall

Priority via `flags.get_flag("provider_priority")` default `apollo>hunter>clearbit`; skip when quota ≤20 unless `remaining_quota` treated as unlimited (0 → unlimited per `services/enrichment.py:42` — see drift).

---

## 7. Decision criteria (observable, not chain-of-thought)

- ICP fit strong when 3+ positive signals present and no negative franchise/enterprise flags.
- Owner visible when `<meta>` or about page contains owner name pattern.
- Simple site when tech_signals contains WordPress/static without enterprise CMS.
- Evidence text mandatory per hard rule #3; missing evidence → `rejected_unclear` or review queue.

---

## 8. Outputs

- `leads.lead_score` 0-10
- `leads.fit_status`
- `leads.priority_score` 0-100 + `scores.tier`
- `leads.evidence` jsonb with `icp_signals` detail + `agent_evidence` + `qualification_reason`
- `contacts` row with verification status + confidence
- `activities` timeline entry

---

## 9. State changes

- `new` → `enriching` or `rejected` via `apply_qualification:262`
- `enriching` → `qualified` via `apply_enrichment:314` (hard-gated)

---

## 10. Interfaces

| Consumer | Contract |
|----------|----------|
| GTM Intent | `companies.tech_signals`, `leads.website_findings` for signal interpretation |
| GTM Lifecycle | `leads.status` transition events emit `lead.enrichment_requested` → `lead.audit_requested` |
| Outbound Gate | `contacts.email_verification_status == verified` required |

---

## 11. Invariants

- Never invent owner/email/findings: `ENRICH_SYSTEM:108` strict verbatim, QA `UNSUPPORTED_FACT` critical.
- Enrichment only after qualification: dual guard `stage_context:179` + `apply_enrichment:281`.
- Offer-pain consistency: `pipeline.apply_offer:362` `PAIN_TO_OFFER[primary_pain] == offer_id` or `PipelineError`.

---

## 12. Failure conditions

| Condition | Handling |
|-----------|----------|
| No website | `_flag_review` + `PipelineError("no website")` route to human review queue |
| Invalid offer | `_flag_review` invalid offer + `PipelineError("invalid offer")` |
| Offer-pain mismatch | `PipelineError("offer-pain mismatch")` + review |
| Draft exceeds 75w / banned phrases / not 4 sentences | `PipelineError` + review |

---

## 13. Safety constraints

- Must never treat weak generic signals as high-confidence outreach basis.
- Generic contacts (`info@`, `contact@`) → HOLD, do not send; rule in `IDENTIFY` (`canonical.ts:identify.edgeCases`).
- Suppressed companies resettable only via explicit `suppression.revoke`, not silent.

---

## 14. Verification

- `backend/tests/test_scoring.py` — ICP arithmetic, threshold, priority tiers, hiring scores
- `backend/tests/test_hiring_signals.py` — keyword scoring as-if real vs LLM, contact persistence
- `backend/tests/test_pipeline_integration.py` — qualification → enrichment chain, offer-pain contract
- Manual: n8n context fetch `GET /api/pipeline/{lead}/context/{stage}` returns system+user+required_keys JSON

---

## 15. Traceability

| Requirement | Implementation | Test |
|-------------|---------------|------|
| LEAD-REQ-004 | `services/scoring.py:39-52` | `test_scoring.py` |
| LEAD-REQ-008 | `services/enrichment.py:rank_title` + `providers/email_finder.py` | `test_email_gates.py` |
| LEAD-REQ-011 | `services/scoring.py:71-81` | `test_scoring.py::priority_tier` |
