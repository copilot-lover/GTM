# Invariants — Contracts that must never be broken

| ID | Invariant | Where enforced |
|----|-----------|----------------|
| INV-001 | Postgres is truth; n8n never owns message/lead state | `README.md: n8n holds NO business state` |
| INV-002 | No send without approval (FR-10) | `email_service.approve` → `claim_for_send` |
| INV-003 | Suppressed never sent | `outbound_gate.not_suppressed` + `suppression.check` |
| INV-004 | `leads.status` only via `state_machine.transition` | `state_machine.TRANSITIONS` |
| INV-005 | `messages.gtm_stage` only via `gtm_lifecycle.transition_message` | `gtm_lifecycle.TRANSITIONS` |
| INV-006 | Backend never calls LLM | `pipeline.stage_context` prompt only |
| INV-007 | Evidence mandatory | `pipeline.hard rule` + `qa_service.UNSUPPORTED_FACT` |
| INV-008 | Idempotency on external effects | `send_attempts`, `CallSid`, `session_leads` PK |
| INV-009 | `contacts.email_verification_status == verified` before send | `outbound_gate.email_verified` |
| INV-010 | `do_not_call` valid from any non-terminal immediately | `state_machine:29` override |
| INV-011 | Follow-up mailbox must match original | `outbound_gate.followup_mailbox_correct` |
| INV-012 | kill switch fires on any inbound reply on any channel | `email_service.kill_switch` + `sequences` |
