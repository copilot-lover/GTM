# STATE MACHINES — Requirements

---

## 1. Lead state machine (`services/state_machine.py`)

Single coordination backbone. No direct `status` writes elsewhere.

### States

`new, enriching, qualified, signal_holding, outreach_ready, contacted, responded, qualified_conversation, meeting_booked, meeting_held, proposal, won, lost, rejected, do_not_call, unreachable, archived, expired_rejected`

### Transitions (authoritative, code)

```
new                 -> {enriching, rejected, do_not_call}
enriching           -> {qualified, signal_holding, outreach_ready, rejected, do_not_call}
qualified           -> {signal_holding, outreach_ready, contacted, rejected, do_not_call}
signal_holding      -> {outreach_ready, qualified, archived, expired_rejected, do_not_call}
outreach_ready      -> {contacted, rejected, do_not_call}
contacted           -> {responded, contacted, unreachable, do_not_call, archived}
responded           -> {qualified_conversation, lost, archived}
qualified_conversation -> {meeting_booked, lost, do_not_call (override)}
meeting_booked      -> {meeting_held, meeting_booked, lost, do_not_call}
meeting_held        -> {proposal, won, lost, do_not_call}
proposal            -> {won, lost, do_not_call}
won,lost,rejected,do_not_call,unreachable,archived,expired_rejected -> terminal (won/lost allow→archived, unreachable→archived)
+ do_not_call valid from any non-terminal (hard compliance override, lines 29-31)
TERMINAL = {s: not nxt} per line 33
```

### Guard

`transition(conn, lead_id, ws, current, target)` optimistic `UPDATE ... WHERE status=%s RETURNING id`; `409` on invalid.

### Requirements

| ID | Requirement |
|----|-------------|
| STATE-REQ-001 | SHALL enforce all transitions via `can_transition` + DB guard. IMPLEMENTED |
| STATE-REQ-002 | SHALL support `do_not_call` from any non-terminal as immediate compliance override. IMPLEMENTED |
| STATE-REQ-003 | SHALL treat missing-data as `rejected_unclear`/`signal_holding` not skip. IMPLEMENTED |

---

## 2. GTM message lifecycle FSM (`services/gtm_lifecycle.py`)

Every managed outbound walks `DISCOVERED → ... → SENT` via `transition_message`; legacy NULL invisible.

### States

`DISCOVERED, QUALIFIED, INTENT_SCORED, RESEARCHED, COPY_GENERATED, QA_PENDING, QA_PASSED, COMPLIANCE_PENDING, SEND_READY, SCHEDULED, SENT, QA_FAILED, COMPLIANCE_FAILED, SUPPRESSED, HELD, EXPIRED, CANCELLED`

### Transitions

```
DISCOVERED -> QUALIFIED -> INTENT_SCORED -> RESEARCHED -> COPY_GENERATED -> QA_PENDING -> {QA_PASSED, QA_FAILED, HELD, CANCELLED}
QA_FAILED -> {COPY_GENERATED, HELD, CANCELLED}
QA_PASSED -> {COMPLIANCE_PENDING, CANCELLED}
COMPLIANCE_PENDING -> {SEND_READY, COMPLIANCE_FAILED, SUPPRESSED, HELD, CANCELLED}
COMPLIANCE_FAILED -> {COPY_GENERATED, SUPPRESSED, HELD, CANCELLED}
SEND_READY -> {SCHEDULED, HELD, EXPIRED, SUPPRESSED, CANCELLED}
SCHEDULED -> {SENT, HELD, EXPIRED, SUPPRESSED, CANCELLED}
HELD -> {QA_PENDING, CANCELLED, EXPIRED}
SENT,SUPPRESSED,EXPIRED,CANCELLED -> terminal
AUTHORIZED_SEND_STAGES = (SEND_READY, SCHEDULED)
```

### Requirements

| ID | Requirement |
|----|-------------|
| GTM-STATE-001 | SHALL only allow sends from `AUTHORIZED_SEND_STAGES`. IMPLEMENTED `outbound_gate.py:154` |
| GTM-STATE-002 | SHALL record `message_stage_events` on every hop with actor/reason/qa_run_id. IMPLEMENTED |
| GTM-STATE-003 | SHALL support `_copy_max_attempts` retry loop → HELD on ceiling (spec §24). IMPLEMENTED `qa_service.resubmit_copy` |

---

## 3. Booking / proposal FSM

`meeting_booked` self-loop allows reschedule; `won` terminal prevents win-back (no reset path — documented PLANNED override needed).

---

## 4. Drift noted

- Two qualification paths diverge: `pipeline.apply_qualification:new→enriching|rejected` vs `routers/leads.score_lead:new→qualified|rejected` — different targets, `signal_holding` bypass possible (CONFLICTING).
- `intent_engine._has_tier_a` reads `scores.tier` but `reevaluate_lead` never writes `tier` → always null (UNIMPLEMENTED).
