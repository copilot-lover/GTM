# OUTBOUND DECISION GATE — Requirements

**Concept:** INTELLIGENCE → DECISION → ACTION. Gate prevents blind automation.
**Status:** IMPLEMENTED — 13 deterministic checks in `services/outbound_gate.py:can_send`.

---

## 1. Question answered

SHOULD ORBIT CONTACT THEM? (YES → SEND_READY | NO → HOLD/SUPPRESSED/HELD/EXPIRED)

---

## 2. Factors (checklist)

- ICP fit (lead_score, fit_status), confidence, need evidence, signal freshness
- Contact quality (verified, not opted_out), suppression (global/email/phone/company), DNC
- Signal quality, previous contact (sequence_state), duplicate, timing (recency), follow-up mailbox correctness
- Mailbox/domain health, sending limits, provider, campaign active, stage authorized

---

## 3. Responsibilities

| ID | Requirement | Classification | Implementation |
|----|-------------|----------------|----------------|
| GATE-REQ-001 | SHALL evaluate 13 checks and return `{allowed, reasons[], checks[]}` auditable | IMPLEMENTED | `outbound_gate.py:96-234` |
| GATE-REQ-002 | SHALL enforce `email_verification_status == verified` | IMPLEMENTED | `outbound_gate:130` |
| GATE-REQ-003 | SHALL require `copy_qa_passed == passed` and `compliance_passed == passed` for managed rows (gtm_stage NOT NULL) | IMPLEMENTED | `outbound_gate:144-153` + `qa_service` |
| GATE-REQ-004 | SHALL require `gtm_stage IN (SEND_READY, SCHEDULED)` per `AUTHORIZED_SEND_STAGES` | IMPLEMENTED | `outbound_gate:154` |
| GATE-REQ-005 | SHALL enforce `not_suppressed` via `suppression.check` and hard-lead-status + contact/opt-out blocks | IMPLEMENTED | `outbound_gate:120-128`, `qa_service:259-294` |
| GATE-REQ-006 | SHALL enforce mailbox health `health_state != paused`, domain `status==active`, and `sent_today < daily_send_limit` | IMPLEMENTED | `outbound_gate:174-191` |
| GATE-REQ-007 | SHALL enforce campaign active when `campaign_id` present | IMPLEMENTED | `outbound_gate:202-207` |
| GATE-REQ-008 | SHALL enforce `sequence_state_ok`: no inbound reply after last outbound when `sequence_step>0` | IMPLEMENTED | `outbound_gate:215-218` |
| GATE-REQ-009 | SHALL enforce `followup_mailbox_correct`: follow-ups must match original mailbox of sequence | IMPLEMENTED | `outbound_gate:219-232` |
| GATE-REQ-010 | SHALL be enforced in code (`claim_for_send` calls `can_send`) not just UI | IMPLEMENTED | `services/email_service.py:claim_for_send` |
| GATE-REQ-011 | SHALL expose `GET /api/outreach/messages/{id}/send-decision` for decision transparency | IMPLEMENTED | `routers/outreach.py` + `routers/gtm.py` why |
| GATE-REQ-012 | SHALL fail-closed: any check false → `allowed=false` with reasons persisted | IMPLEMENTED | `outbound_gate:234` reasons aggregation |
| GATE-REQ-013 | Legacy rows `gtm_stage IS NULL` SHALL skip QA/compliance/stage checks (unchanged pre-existing flows) | IMPLEMENTED | `outbound_gate:137-140` |

---

## 4. Checks list (13)

`lead_eligible`, `contact_eligible`, `not_suppressed`, `email_verified`, `copy_qa_passed`, `compliance_passed`, `stage_authorized`, `mailbox_healthy`, `domain_healthy`, `within_sending_limits`, `provider_available` (stub True), `campaign_active`, `sequence_state_ok`, `followup_mailbox_correct` (15 with sequence two).

---

## 5. State transitions caused

- `COMPLIANCE_PENDING` → `SEND_READY` (pass) | `COMPLIANCE_FAILED`/`SUPPRESSED`/`HELD` (fail) via `qa_service:305`
- `SEND_READY` → `SCHEDULED` → `SENT` via `email_service.claim_for_send`

---

## 6. Invariants

- `provider_available` always True currently — drift: stub, not real SMTP check.
- `within_sending_limits` race against `scheduler.get_daily_capacity` date rollover (same drift noted in security/performance passes).

---

## 7. Verification

- `backend/tests/test_email_gates.py` — rejected/unverified/blocked→cannot send
- `backend/tests/test_gtm_acceptance.py:TestComplianceFailureCannotSend`
