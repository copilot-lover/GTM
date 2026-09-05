# TRACEABILITY — Requirement → Implementation → Test → Human → Agent → Diagram

> A requirement without implementation is visible as PLANNED. An implementation without documented behavior is flagged UNDOCUMENTED. Generated from `canonical.ts:76` + `services/*` + `backend/tests/*` on 2026-08-31.

| Requirement | Implementation | Test | Human doc | Agent doc | Mermaid |
|-------------|----------------|------|-----------|-----------|---------|
| LEAD-REQ-004 ICP 0-10 | `services/scoring.py:39-52` | `tests/test_scoring.py` | `docs/05-qualification/README.md` QUALIFY | `agent-docs/06-qualification.md` | `docs/18-mermaid 2,3` |
| LEAD-REQ-008 identify waterfall | `services/enrichment.py:rank_title:251 + verify_email_waterfall` | `tests/test_email_gates.py` | `docs/06-contact-discovery` IDENTIFY | `agent-docs/04-gtm-leads` | 2 |
| INTENT-REQ-005 hiring score | `services/scoring.py:113-145` | `tests/test_hiring_signals.py` | `docs/03-gtm-intent` + `05-qualification` | `agent-docs/05-gtm-intent` | 3 |
| INTENT-REQ-008 reevaluate | `services/intent_engine.py:181` recency decay | `tests/test_gtm_acceptance invalid signal` | `docs/03-gtm-intent` | `agent-docs/05-gtm-intent` | 2+6 |
| OPP-REQ-002 composite 6 | `services/opportunity.py:238` + `research.py:330` | `tests/test_gtm_acceptance` | `docs/07-opportunity` | `agent-docs/07-opportunity` | 9 |
| GATE-REQ-001 13 checks | `services/outbound_gate.py:96` | `tests/test_email_gates.py` + `test_gtm_acceptance` compliance | `docs/08-outbound` GATE | `agent-docs/08-outbound` | 4+5 |
| GATE-REQ-004 stage authorized | `services/gtm_lifecycle.py:20` SEND_READY,SCHEDULED | `tests/test_gtm_acceptance` | `docs/08-outbound` | `agent-docs/08-outbound` | 4 |
| OUT-REQ-005 claim idempotency | `services/email_service.py:claim_for_send` | `tests/test_email_gates` suppressed atomic | `docs/08-outbound` OUTREACH | `agent-docs/08-outbound` | 8 |
| OUT-REQ-009 kill switch | `services/email_service.py:kill_switch` | `tests/test_gtm_acceptance durable reply` | `docs/08-outbound` + `09-conversation` | `agent-docs/09-conversation` | 8 |
| RESP-REQ-001 classify 13 | `services/sequences.py:classify_reply` + `n8n/reply-classification.json` | manual simulation | `docs/09-conversation` | `agent-docs/09-conversation` | 8 |
| STATE-REQ-001 lead FSM | `services/state_machine.py:6` TRANSITIONS | `tests/test_pipeline_integration` state | `docs/12-state-machine` | `agent-docs/03-state-machine` | 3 |
| GTM-STATE-001 message FSM | `services/gtm_lifecycle.py:31` TRANSITIONS | `tests/test_gtm_acceptance` §24 | `docs/12-state-machine` | `agent-docs/03-state-machine` | 4 |
| FR-10 human approval | `routers/outreach.py:approvals` + `services/email_service.approve` | `tests/test_email_gates` | `docs/08-outbound` | `agent-docs/08-outbound` | 5 |

## Gaps

| Requirement | Gap | Status |
|-------------|-----|--------|
| `intent_engine._has_tier_a` reads `scores.tier` but never written | tier always NULL, P2 promotion dead | CONFLICTING — flagged in `canonical.ts:qualify.whatCanGoWrong` |
| `research_reports` unbounded per company (no dedupe) | only latest read `_get_latest_research` | UNDOCUMENTED drift |
| `provider_available` always True stub | gives false confidence | PARTIALLY — docs flag stub |
| `FixtureCalendar` never overridden (FR-30) | BOOK not fully integrated | PLANNED |
| Two qualification paths `pipeline.apply_qualification` vs `routers/leads.score_lead` | different exits `enriching` vs `qualified` | CONFLICTING |

## How to maintain

On code change: update row, rerun `scripts/verify-trace.sh` (see `specs/verification/README.md`). On doc change: regenerate mermaid from `canonical.ts` export `GTM_STAGE_IDS` to avoid CODE≠DOCS≠DIAGRAM drift.
