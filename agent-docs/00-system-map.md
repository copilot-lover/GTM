# 00 — System Map (Orbit GTM OS)

## Role
GTM OS that turns raw public signals → understood business → qualified prospect → verified contact → evidence-backed offer → human-approved send → behavior-reactive sequence → booking → learning. 11 stages + 2 brains + 7 principles. Canonical definition: `frontend/src/gtm/canonical.ts:76`.

## Purpose
Single orchestrated pipeline: FIND → UNDERSTAND → QUALIFY → IDENTIFY → OPPORTUNITY → DECIDE → GATE → OUTREACH → RESPONSE → CONVERSE → BOOK → LEARN. Prevents spam via deterministic gates and human approval. Simulation reference: `frontend/src/gtm/simulation.ts:46` (ABC HVAC).

## You May
- Read `frontend/src/gtm/canonical.ts:10` for stage IDs, `frontend/src/gtm/simulation.ts:46` for prospect walkthrough.
- Traverse backend via `backend/app/services/` and `backend/app/agents/registry.py:13` (agent boundaries).
- Modify one component at a time, preserving contracts (see 01-global-rules).
- Add tests under `backend/tests/` using `tests/conftest.py:23` fixtures.

## You Must Not
- Direct-write `leads.status` or `messages.gtm_stage` bypassing state machines (`services/state_machine.py:40`, `services/gtm_lifecycle.py:59`).
- Invent contacts/emails/findings without source evidence (`services/pipeline.py:212` fail-closed).
- Bypass `services/outbound_gate.py:96` can_send or `services/email_service.py:125` claim_for_send gates.
- Call LLM from backend (`services/pipeline.py:1` layer boundary: backend deterministic only; LLMs via n8n).

## Input / Output / State Contracts
- **Input:** `GET /api/pipeline/{lead_id}/context/{stage}` → `{system, user, required_keys}` (`services/pipeline.py:165`). n8n runs Scrapling + LLM, then `POST /api/pipeline/{lead_id}/apply/{stage}` with parsed JSON.
- **Output:** Validated lead/message mutations + `event_outbox` event + `activities` row (`services/pipeline.py:66`, `services/events.py`).
- **State:** Lead FSM via `services/state_machine.py:6` TRANSITIONS; message FSM via `services/gtm_lifecycle.py:31` TRANSITIONS. Optimistic guarded updates (`WHERE status=%s` + `RETURNING id`).

## Invariants
- Every state change through single choke point; raises 409/InvalidTransition on illegal hop.
- `do_not_call` reachable from any non-terminal (`services/state_machine.py:29`). Terminal = empty set (`services/state_machine.py:33`), `services/gtm_lifecycle.py:45` SENT/SUPPRESSED/EXPIRED/CANCELLED.
- Evidence mandatory for QUALIFY (`services/pipeline.py:224` icp_fit_score + `scores` row).
- Offer→pain consistency: `services/pipeline.py:362` PAIN_TO_OFFER.
- Draft QA: <75 words, 4 sentences, no BANNED_PHRASES (`services/pipeline.py:377`).

## Dependencies
- DB: Postgres via `app/db.py:17` pool (psycopg_pool, dict_row). Migrations `db/migrations/0002_core_schema.sql:1` + `0008_gtm_agents.sql:11`.
- Providers: `app/providers/job_sources.py`, `app/providers/base.py` Registry + fixtures; CircuitBreaker+retry.
- Frontend canonical: `frontend/src/gtm/canonical.ts:76` GTM_STAGES source of truth; backend `app/routers/gtm.py:243` mirrors for API.

## Valid States (summary)
- Lead FSM 17 valid statuses (`services/state_machine.py:6` TRANSITIONS + `state_machine.py:33` TERMINAL). Message FSM 17 stages (`services/gtm_lifecycle.py:12` STAGES, `0008_gtm_agents.sql:15` CHECK). Only transitions listed are valid; all else 409.

## Safe vs Dangerous Changes
- Safe: tune config flags, add monitoring to `services/observability.py:1`, adjust frontend canonical display.
- Dangerous: adding new lead/message status without migration + test_state_machine update, bypassing transition() guards, merging the two FSMs.

## Pitfalls (preview)
- Dual queues `messages` vs `outbound_messages` divergent (see 08-outbound).
- Dual qualification paths `pipeline.apply_qualification` vs `leads.score_lead`.
- `contacts` tri-state vs `email_verification_status` conflation.

## Before Modifying
1. Read `frontend/src/gtm/canonical.ts:76` + relevant service (see Related).
2. Check `services/state_machine.py:36` can_transition and `services/gtm_lifecycle.py:53` can_transition.
3. Add/verify tests (`tests/test_state_machine.py:6`, `tests/test_gtm_acceptance.py:112`).
4. Preserve fail-closed behavior; add review_reasons on rejection (`services/pipeline.py:76`).

## After Modifying
- Run `pytest backend/tests` (see 11-testing). Assert stage history via `services/gtm_lifecycle.py:111` stage_history.
- Verify outbound gate still blocks (`services/outbound_gate.py:96`).
- Confirm simulation panel in frontend still renders from canonical.

## Related Components
| Stage | Backend owner | Trace |
|-------|---------------|-------|
| FIND | `providers/job_sources.py`, `services/pipeline.py` | `canonical.ts:135` |
| UNDERSTAND | `services/website_intel.py:222`, `services/enrichment.py:144`, `services/hiring_signals.py:87` | `canonical.ts:199` |
| QUALIFY | `services/scoring.py:39`, `services/intent_engine.py:181` | `canonical.ts:263` |
| IDENTIFY | `services/enrichment.py:194` | `canonical.ts:329` |
| OPPORTUNITY | `services/research.py:330`, `services/opportunity.py:238` | `canonical.ts:393` |
| DECIDE | `services/pipeline.py:384`, `services/qa_service.py:177` | `canonical.ts:456` |
| GATE | `services/outbound_gate.py:96`, `services/gtm_lifecycle.py:20` | `canonical.ts:521` |
| OUTREACH | `services/email_service.py:125`, `services/scheduler.py:397`, `services/sequences.py:35` | `canonical.ts:588` |

## Examples
- ABC HVAC happy path: `frontend/src/gtm/simulation.ts:46` profile + `simulation.ts:65` steps (FIND new → UNDERSTAND enriching → QUALIFY qualified P1 → IDENTIFY verified → OPPORTUNITY tier A → DECIDE draft → GATE SEND_READY → OUTREACH SENT → RESPONSE QUESTION → BOOK).
- Guarded transition example: `services/state_machine.py:40` transition() checks can_transition then UPDATE ... WHERE status=%s RETURNING id; stale returns False.
- Message lifecycle enrollment: `services/pipeline.py:432` gtm_lifecycle.transition_message NULL→QA_PENDING on draft create.
