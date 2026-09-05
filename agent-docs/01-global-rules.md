# 01 — Global Rules (Invariants, Boundaries, Safe vs Dangerous)

## Global Invariants (never break)
1. **Single state-machine entry:** All `leads.status` via `services/state_machine.py:40` `transition()`; all `messages.gtm_stage` via `services/gtm_lifecycle.py:59` `transition_message()`. Direct `UPDATE leads SET status=` elsewhere is a bug.
2. **Fail-closed:** Missing/unclear evidence → borderline/rejected/HELD, never guess. `services/pipeline.py:212` owner_name=None fail-closed; `services/scoring.py:55` signals_too_large → rejected_too_large; `services/qa_service.py:52` failed→status failed.
3. **Determinism before LLM:** `services/scoring.py:39` arithmetic, `services/outbound_gate.py:96` 13 checks, `services/qa_service.py:177` QA are pure code. LLM only via n8n workflows (`services/pipeline.py:3` header).
4. **Human approval required:** `services/email_service.py:71` approve() checks pending_approval/drafted + QA_PASSED/SEND_READY; `services/email_service.py:142` claim_for_send requires approved. `services/scheduler.py:80` _needs_approval in hybrid.
5. **Hard suppression gate:** `services/suppression.py:15` check() enforced in `services/outbound_gate.py:120` and `services/email_service.py:175`; also `services/qa_service.py:263` compliance.
6. **Idempotency:** Lead/company dedupe `services/phones.py:25` dedupe_key + `pipeline.py` SHA-256; message dedupe `services/email_service.py:130` idempotency_key.
7. **Tenant isolation:** Every query scopes `workspace_id` (`services/state_machine.py:48`, `services/gtm_lifecycle.py:75`, `services/email_service.py:32`). `tests/conftest.py:23` isolated DB orbit_test.

## Boundaries (who owns what)

| Component | Owns | Does NOT own |
|-----------|------|--------------|
| `services/pipeline.py:30` | deterministic stage contexts + apply validators, state transitions, review routing | LLM calls, scraping, SMTP transport |
| `services/state_machine.py:6` | lead FSM `TRANSITIONS` + TERMINAL + can_transition | message lifecycle (see gtm_lifecycle) |
| `services/gtm_lifecycle.py:31` | message FSM `TRANSITIONS`, AUTHORIZED_SEND_STAGES, stage_history | lead status |
| `services/outbound_gate.py:96` | 13 structural send checks (return allowed/reasons/checks) | actual SMTP send |
| `services/email_service.py:125` | approve/reject/claim_for_send/apply_send_result/kill_switch/classify_reply, idempotency | QA decision (delegates to qa_service) |
| `services/scoring.py:39` | pure arithmetic: icp_fit_score, priority_score, hiring_intent_score, OFFER_CATALOG | DB writes (except intent_engine reuses) |
| `services/intent_engine.py:181` | reevaluate_lead, ingest_event, process_pending_events, recency decay | raw signal collection |
| `services/hiring_signals.py:87` | classify_role, detect_intent_signals, upsert_hiring_signal, dedupe_postings, expiry | scoring (delegates to scoring.py) |
| `services/website_intel.py:222` | scrape→parse→tech_signals/website_findings | hiring/intent |
| `services/enrichment.py:144` | waterfall (apollo>hunter>clearbit), find_decision_maker_email, verify_email_waterfall | message sending |
| `services/research.py:330` | assemble_evidence, call LLM strong tier, validate/repair, write research_reports | opportunity composite (opportunity.py) |
| `services/opportunity.py:238` | compute_opportunity_score 6 components, EMV, tier | research evidence assembly |
| `services/scheduler.py:397` | tick capacity/allocation/mailbox assign, business hours | lead FSM |
| `services/sequences.py:35` | on_initial_sent followup creation, cancellation, reply classify keyword | email transport |
| `services/suppression.py:15` | check/add/is_opted_out global hard gate | UI filtering |
| `services/qa_service.py:177` | run_copy_qa/run_compliance_qa/run_lead_qa/run_research_qa + findings | draft generation |
| `app/agents/registry.py:13` | AGENTS capabilities, assert_can_send, assert_not_self_approval | business logic |
| `frontend/src/gtm/canonical.ts:76` | 11-stage GTM + 2 brains + 7 principles source of truth | backend transitions |
| `frontend/src/gtm/simulation.ts:46` | ABC HVAC synthetic walkthrough | real DB |

## Safe vs Dangerous Changes
**Safe:**
- Tuning `services/scoring.py:20` QUALIFY_THRESHOLD or weights with test update (`tests/test_scoring.py:11`).
- Adding new `PAIN_TO_OFFER` mapping entry (`services/pipeline.py:125`) + updating `scoring.OFFER_CATALOG` (`services/scoring.py:24`) atomically across 4 duplicates (flag PARTIALLY).
- Adding new event_type via `services/intent_engine.py:38` register_event_type (but must persist if needed).
- Adjusting `services/scheduler.py:22` HEALTH_MULTIPLIER values.
- Adding BANNED_PHRASES (`services/pipeline.py:377`) with mirror update in `services/qa_service.py:212`.

**Dangerous (requires design review + tests):**
- Adding/changing TRANSITIONS in `state_machine.py:6` or `gtm_lifecycle.py:31` (breaks FSM, needs migration + test_state_machine).
- Bypassing `transition()`/`transition_message()` for direct UPDATE (creates orphan states, breaks audit).
- Changing `AUTHORIZED_SEND_STAGES` (`services/gtm_lifecycle.py:20`) or removing a check in `outbound_gate.py:96` (opens spam hole).
- Making backend call LLM directly (violates `services/pipeline.py:3` layer boundary; breaks n8n contract).
- Normalizing phone/email differently than `services/phones.py:9` or `services/enrichment.py:279` local_prechecks (creates duplicate/bypass).
- Altering `messages.status` vs `gtm_stage` dual columns without atomic constraint.

## Contracts Must Preserve
- `stage_context() → {system, user, required_keys}` and `apply_* → {next, ...}` plus `event_outbox` emit (`services/pipeline.py:84` _emit).
- `can_transition() → bool` + `transition() → bool|HTTPException 409` optimistic (`services/state_machine.py:36`).
- `gtm_lifecycle.can_transition(None→any)` but `transition_message` guarded with `IS NOT DISTINCT FROM` (`services/gtm_lifecycle.py:86`).
- `outbound_gate.can_send → {allowed, reasons[], checks[13]}` auditable (`services/outbound_gate.py:234`).
- `email_service.claim_for_send` idempotent replay via idempotency_key (`services/email_service.py:130`).

## Pitfalls flagged PARTIALLY IMPLEMENTED
- `OFFER_CATALOG` duplicated 4 places (scoring.py, pipeline.py, opportunity.py, canonical.ts) — drift risk.
- `finding_decision_maker` may insert contact but not link `leads.contact_id` (`services/enrichment.py:238` ON CONFLICT DO NOTHING without update).
- `intent_engine.reevaluate_lead` never writes `scores.tier` but `_has_tier_a` reads it (`services/intent_engine.py:282` dead code).

## What Must Be Tested After Modification
- `pytest tests/test_state_machine.py` for FSM.
- `pytest tests/test_gtm_acceptance.py` for QA/gate/re-evaluate/ followup paths.
- `pytest tests/test_pipeline.py` for stage gating + offer contract.
- `pytest tests/test_email_gates.py` + `tests/test_suppression.py` for safety.
- If scheduler/mailbox changed: `tests/test_scheduler_outreach.py`.
