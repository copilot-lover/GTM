# OUTREACH — Requirements

**Behavior:** INITIAL_MESSAGE → WAIT → OBSERVE → FOLLOW-UP → OBSERVE → NEXT DECISION (conditional, behavior-reactive sequence)
**Status:** IMPLEMENTED via `services/email_service.py` + `services/scheduler.py` + `services/sequences.py`

---

## 1. Purpose

Controlled, deterministic, behavior-dependent outreach — not a blast. Behavior branches: no response | positive reply | question | objection | unsubscribe | wrong person | later | ready to book | OOO | unclear.

---

## 2. Responsibilities

| ID | Requirement | Classification |
|----|-------------|----------------|
| OUT-REQ-001 | System SHALL produce `PROBLEM + SERVICE + CONTACT + CONTEXT + SIGNAL = OUTREACH ANGLE` (not name-mail-merge) | IMPLEMENTED `pipeline.create_draft_message` + `canonical.ts:decide` |
| OUT-REQ-002 | System SHALL enforce message strategy per `PERSONALIZE_SYSTEM` Hermes 4-sentence (Fact, Inference, Offer, Question), <75 words, one CTA, evidence opener | IMPLEMENTED `pipeline.apply_draft:384`, `qa_service:216-226` |
| OUT-REQ-003 | System SHALL validate drafts deterministically (word_count, banned_phrases, sentence_count) before approval queue | IMPLEMENTED both `pipeline` + `qa_service` |
| OUT-REQ-004 | System SHALL route drafts to human approval queue (dashboard + Telegram) and never auto-send in hybrid mode | IMPLEMENTED `routers/outreach.py:approvals`, `services/email_service.py:approve` |
| OUT-REQ-005 | System SHALL claim messages atomically with idempotency keys and enforce GATE before send | IMPLEMENTED `email_service.claim_for_send` idempotency |
| OUT-REQ-006 | System SHALL schedule follow-ups `day 0/3/7/14` style with angle rotation, breakup honored, stop-on-reply | PARTIALLY IMPLEMENTED `services/sequences.py:schedule_followups` — breakup logic PLANNED |
| OUT-REQ-007 | System SHALL assign mailboxes via health-multiplied capacity, lowest sent/effective ratio, `next_available_slot` business hours + jitter | IMPLEMENTED `services/scheduler.py:assign_mailboxes` |
| OUT-REQ-008 | System SHALL enforce follow-up mailbox binding (`originating_mailbox_id` matches original) | IMPLEMENTED `outbound_gate:219-232` |
| OUT-REQ-009 | System SHALL execute kill switch on any inbound reply: pause automation, delete `session_leads`, cancel queued `outbound_messages`, alert operator, purge call queues | IMPLEMENTED `services/email_service.py:kill_switch` + `sequences` |
| OUT-REQ-010 | System SHALL log observations (delivered/open/click/reply/bounce/complaint via `email_events`) and state wait vs cancelled | IMPLEMENTED `routers/outreach.py:apply/send-result` |

---

## 3. Booking via outreach

Hand-off to CONVERSE/BOOK when `classify_reply` → `READY TO BOOK` or confirmed `INTERESTED` with appropriate timing.

---

## 4. Invariants

- Draft never sent without approval; even scheduled follow-ups currently create `approved` without approval-mode check in some paths (drift: needs hybrid/autonomous mode check).
- No fallback mailbox on `HELD` due to unavailable original → alert, no silent fallback (tested `test_gtm_acceptance`).

---

## 5. Verification

- `tests/test_email_gates.py`, `tests/test_scheduler_outreach.py`, `tests/test_gtm_acceptance.py:TestFollowupMailboxBinding`
