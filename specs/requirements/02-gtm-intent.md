# GTM INTENT — Requirements

**Question:** WHAT IS HAPPENING WITH THIS BUSINESS?
**Flow:** OBSERVATION → SIGNAL → CONTEXT → INTERPRETATION → OPPORTUNITY HYPOTHESIS
**Distinguish:** FACT (observed posting URL, site CTA text) vs INFERENCE (hiring dispatcher → call pressure) vs OPPORTUNITY HYPOTHESIS (reasoned profile with confidence)
**Agent:** GTM_INTENT (spec §9.1 A11)
**Status:** IMPLEMENTED (`services/hiring_signals.py`, `services/intent_engine.py`, `services/website_intel.py`) — PLANNED gaps noted.

---

## 1. Purpose

Observe and interpret meaningful business changes — hiring, growth, expansion, website changes, advertising, operational signals, buying signals, timing signals — and translate a detected change into an opportunity hypothesis that GTM Leads + GTM Intent combine into `OPPORTUNITY → OUTREACH DECISION`.

---

## 2. Scope

- Hiring signal ingestion from pluggable job source adapters (JobsPipe, TheirStack, JSearch, FantasticJobs, Adzuna)
- Website intelligence (booking, chatbot, mobile, CTA, speed, after-hours, trust)
- Intent event model (continuous re-evaluation)
- Recency-decayed priority recomputation
- Signal expiry

Out of scope: sending (GATE owns); ICP qualification decision (LEADS owns).

---

## 3. Responsibilities (SHALL)

| ID | Requirement | Classification | Verification |
|----|-------------|----------------|--------------|
| INTENT-REQ-001 | The system SHALL distinguish observed business signals from inferred opportunities and never treat a single weak signal as sufficient high-confidence evidence. | IMPLEMENTED | `canonical.ts:qualify` decouples signal detection vs opportunity; `services/scoring.py:hiring_intent_score` weights + thresholds 50/70/90 |
| INTENT-REQ-002 | The system SHALL retain evidence supporting every interpreted signal (signal URL, payload, `evidence_refs`, `research_reports` citations). | IMPLEMENTED | `hiring_signals` `source_url`, `signals.payload`, `messages.evidence_refs`, `research_reports.evidence[].source_ref` |
| INTENT-REQ-003 | The system SHALL not treat a single weak signal as sufficient evidence for high-confidence outreach; require multiple corroborating signals or strong single high-intent signal + ICP match. | IMPLEMENTED | `scoring.hiring_intent_score:128` ICP +30 required for ≥90 to trigger; `intent_engine.reevaluate:256` P1 requires `score>=70 && freshest<=7` |
| INTENT-REQ-004 | The system SHALL provide downstream systems with structured intent information (role category, signal_score, freshness_multiplier, `signal_count`, `components.contributions[]` for Why panel). | IMPLEMENTED | `services/intent_engine.py:268` `scores` insert with `components.contributions[]`, `GET /api/gtm/leads/{id}/why` |
| INTENT-REQ-005 | The system SHALL score hiring intent per `HIRING_ROLE_BASE`/`HIRING_CONTEXT_ROLES` + context bonuses (after_hours +15, phone_heavy +15, scheduling +15, multiple_openings +10, recency +10) minus multi_location -10, normalized 0-100. | IMPLEMENTED | `services/scoring.py:113-145` |
| INTENT-REQ-006 | The system SHALL categorize hiring roles per taxonomy: very high (receptionist, front desk, CSR, dispatcher, appointment setter...), context-relevant (HVAC dispatcher...), and require job description reading (not just title) for intent scoring. | IMPLEMENTED | `services/hiring_signals.py:classify_role`, `detect_description_signals`, hiring posting ingestion `posted_at` |
| INTENT-REQ-007 | The system SHALL perform website audit producing `findings` (has_online_booking, has_chatbot, mobile_quality, cta_quality, after_hours_capture, trust_signals) + `pain_points[]` + `primary_pain`/`secondary_pain` with evidence quotes. | IMPLEMENTED | `services/website_intel.py`, `pipeline.AUDIT_SYSTEM:115` |
| INTENT-REQ-008 | The system SHALL support continuous intent re-evaluation: on `intent_events` arrival, recompute `leads.priority_score` via deterministic `base_icp*10 + contributions (recency-decayed)` + `signal_count` bonus {≥4:+10, ≥2:+5}. | IMPLEMENTED | `services/intent_engine.py:reevaluate_lead:181` recency `1 - age/30`, `MAX_SIGNAL_CONTRIBUTION=35` |
| INTENT-REQ-009 | The system SHALL decay signal contribution by recency `max(0, 1 - age_days/30)` and expire hiring signals after 60 days / general signals after 30 days. | PARTIALLY IMPLEMENTED | Recency decay implemented `intent_engine.py:216-232`; expiry via `hiring_signals.expires_at` check in `qa_service:167` — unprocessed 30d+ events still inserted but contribute 0 (contributions filtered but not deleted) — PLANNED purge job |
| INTENT-REQ-010 | The system SHALL emit and process `intent_events` via outbox `LISTEN orbit_events` and `job_queue enqueue gtm_intent_process` with idempotency `intent-process-{id}`. | IMPLEMENTED | `services/intent_engine.py:ingest_event:101` enqueue, `services/events.py:emit` |

---

## 4. Preconditions

- `companies` record exists (resolved via posting → company/domain/website/phone)
- `workspace_id` present; `intent_events.workspace_id` indexes.

---

## 5. Inputs

- Job postings `{source, source_url, external_job_id, title, description_raw, posted_at}`
- Website homepage content (HTML) via `POST /api/scrape`
- Operational signals: `JOB_POSTED:35, JOB_UPDATED:15, JOB_REMOVED:-10, NEW_LOCATION:25, EXPANSION:25, HEADCOUNT_CHANGE:15, WEBSITE_CHANGE:10, TECHNOLOGY_CHANGE:10, LEADERSHIP_CHANGE:10, NEW_REVIEW_PATTERN:10, CONTACT_CHANGE:10`

---

## 6. Decision criteria

- `hiring_category(score): >=90 very_high→immediate`, `70-89 high`, `50-69 medium`, `<50 low` (ignore)
- `_has_tier_a` promotes to P2 — but currently dead code (see drift: `intent_engine:282` reads `scores.tier IN ('A','A+')` but `reevaluate` never writes `tier`)
- `freshest_age <=7` required for P1 with total ≥70

---

## 7. Outputs

- `hiring_signals` rows with `role_category`, `signal_score` 0-100, `freshness_multiplier`, `expires_at` (~60d)
- `intent_events` rows + `lead_reevaluate` `scores` opportunity row with `components.contributions[]`
- `leads.priority_score` updated

---

## 8. State changes

- Lead priority tier band `P1/P2/P3` derived, not persisted as `priority_tier` column but computed via `scoring.priority_tier` + `intent_engine:256`
- `hiring_signals.status` active→expired on age (PLANNED background check)

---

## 9. Interfaces

| Downstream | Contract |
|------------|----------|
| GTM Leads (QUALIFY) | `hiring_signals.signal_score` + `freshness_multiplier` feed `scoring.intent` component |
| Opportunity | `research_reports` + `website_findings.findings` + `hiring_signals` assembled in `research.py:_assemble_evidence` |
| Why panel | `GET /api/gtm/leads/{id}/why` aggregates `scores.components.contributions[]` + live `hiring_signals` |

---

## 10. Invariants

- Observation ≠ Inference ≠ Opportunity: a `JOB_POSTED` event is not outreach until interpreted + qualified + gated.
- Never invent owner/email/findings: `pipeline:108` enrichment + `website_intel` evidence quotes.
- Signal quality must be conservative: `hiring_signals.signal_score` 0-100 for display capped, `MAX_SIGNAL_CONTRIBUTION=35` per signal prevents single-signal dominance.

---

## 11. Failure conditions

| Condition | Handling |
|-----------|----------|
| Expired/invalid signal cited in draft evidence | `qa_service._check_signal_refs:147` critical `WRONG_SIGNAL`, blocks `QA_PENDING→QA_FAILED` |
| Stale research (>30d) | `qa_service.run_research_qa:404` warning `MISSING_EVIDENCE` stale |
| Unknown event_type | `intent_engine.ingest_event:70` `ValueError("unknown event_type")` |

---

## 12. Safety constraints

- No anti-bot/CAPTCHA/login bypass; only permitted APIs/feeds/compliant collection per §8.7.
- Store `source_url + timestamp` per posting + per contact lineage (NFR-8).

---

## 13. Verification

- `backend/tests/test_hiring_signals.py` — keyword scoring as-if real, intent detection
- `backend/tests/test_gtm_acceptance.py` — invalid signal invalidated, reprioritized, no signal-based send
- Manual: `POST /api/hiring-intent/ingest` + `POST /api/gtm/leads/{id}/reevaluate` → inspect `scores.components`

---

## 14. Traceability

| Requirement | Implementation |
|-------------|---------------|
| INTENT-REQ-005 | `services/scoring.py:113-145` |
| INTENT-REQ-008 | `services/intent_engine.py:181-279` `process_pending_events` + `reevaluate_lead` |
