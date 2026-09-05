# STATE MACHINE — Canonical Model

**Truth source:** `services/state_machine.py:6` + `services/gtm_lifecycle.py:31`. Docs mirror code; if divergence, bug filed.

---

## 1. Lead state machine (single source of truth — all agents coordinate here)

No direct `leads.status` writes. Use `state_machine.transition(conn, lead_id, workspace_id, current, target)` optimistic guard (`UPDATE ... WHERE status=%s RETURNING id`).

### States (18)

`new, enriching, qualified, signal_holding, outreach_ready, contacted, responded, qualified_conversation, meeting_booked, meeting_held, proposal, won, lost, rejected, do_not_call, unreachable, archived, expired_rejected`

`TERMINAL` computed `services/state_machine.py:33` as `not nxt`.

### Entry / exit / prohibited

| State | Valid entry from | Valid exits to | Prohibited | Missing-data behavior |
|-------|------------------|----------------|------------|----------------------|
| new | creation | enriching, rejected, do_not_call | direct → qualified | N/A |
| enriching | new | qualified, signal_holding, outreach_ready, rejected, do_not_call | → contacted before qualified | no website → _flag_review + PipelineError |
| qualified | enriching | signal_holding, outreach_ready, contacted, rejected, do_not_call | → won before meeting | gated on fit_status==qualified |
| signal_holding | qualified/enriching | outreach_ready, qualified, archived, expired_rejected, do_not_call | → contacted without gate | waits for timing signal, expiry 60d |
| outreach_ready | signal_holding/qualified/enriching | contacted, rejected, do_not_call | → responded without contacted | requires verified contact + gate pass |
| contacted | outreach_ready/qualified | responded, contacted (re-send), unreachable, do_not_call, archived | → qualified_conversation without responded | follow-up mailbox must match original |
| responded | contacted | qualified_conversation, lost, archived | stay contacted | kill switch fires here (FR-12) |
| qualified_conversation | responded | meeting_booked, lost | → won | human judgment |
| meeting_booked | qualified_conversation | meeting_held, meeting_booked (reschedule self-loop), lost | → proposal | calendar provider fixture only |
| meeting_held | meeting_booked | proposal, won, lost | → contacted | |
| proposal | meeting_held | won, lost | → enriching | |
| won/lost | proposal/meeting_held/responded | lost→archived only, won terminal | win-back no path (PLANNED override) | |
| rejected/do_not_call/unreachable/archived/expired_rejected | varied | terminal (lost/unreachable→archived) | any non-do_not_call injection blocked for terminal | do_not_call valid from any non-terminal (lines 29-31 inject) |

### Compliance override

```python
for s, targets in TRANSITIONS.items():
    if s not in ("won","rejected","do_not_call","archived"):
        targets.add("do_not_call")  # line 31
```

Any lead can be suppressed immediately; enforced before send via `outbound_gate.lead_eligible`.

---

## 2. GTM message lifecycle FSM (structural send gate)

Managed rows: `messages.gtm_stage` TEXT CHECK `db/migrations/0008_gtm_agents.sql:15`. `NULL = legacy/unmanaged` invisible to machine, skips QA/compliance/stage checks per `outbound_gate.py:137`.

### States (17)

`DISCOVERED, QUALIFIED, INTENT_SCORED, RESEARCHED, COPY_GENERATED, QA_PENDING, QA_PASSED, COMPLIANCE_PENDING, SEND_READY, SCHEDULED, SENT, QA_FAILED, COMPLIANCE_FAILED, SUPPRESSED, HELD, EXPIRED, CANCELLED`

`AUTHORIZED_SEND_STAGES = (SEND_READY, SCHEDULED)` `services/gtm_lifecycle.py:20`.

### Transitions (authoritative)

```
DISCOVERED -> QUALIFIED -> INTENT_SCORED -> RESEARCHED -> COPY_GENERATED -> QA_PENDING
QA_PENDING -> {QA_PASSED, QA_FAILED, HELD, CANCELLED}
QA_FAILED -> {COPY_GENERATED, HELD, CANCELLED}
QA_PASSED -> {COMPLIANCE_PENDING, CANCELLED}
COMPLIANCE_PENDING -> {SEND_READY, COMPLIANCE_FAILED, SUPPRESSED, HELD, CANCELLED}
COMPLIANCE_FAILED -> {COPY_GENERATED, SUPPRESSED, HELD, CANCELLED}
SEND_READY -> {SCHEDULED, HELD, EXPIRED, SUPPRESSED, CANCELLED}
SCHEDULED -> {SENT, HELD, EXPIRED, SUPPRESSED, CANCELLED}
SENT,SUPPRESSED,EXPIRED,CANCELLED -> terminal
HELD -> {QA_PENDING, CANCELLED, EXPIRED}
```

Guard: `transition_message(workspace_id, message_id, to_stage, actor, reason, conn?, qa_run_id?)` raises `InvalidTransition` on unknown stage, illegal hop, concurrent `WHERE gtm_stage IS NOT DISTINCT FROM`, or missing message. Records `message_stage_events` per hop (actor/reason/qa_run_id).

### Retry loop

`qa_service.resubmit_copy` handles findings-driven regeneration until ceiling `gtm_copy_max_attempts` (default 3, `config.py:gtm_copy_max_attempts`) then `HELD`.

---

## 3. Drift / bugs

- Two qualification entry points diverge: `pipeline.apply_qualification:new→enriching|rejected` vs `routers/leads.score_lead:new→qualified|rejected` — `signal_holding` bypass possible.
- `intent_engine._has_tier_a` reads `scores.tier` but never written.
- `won` terminal prevents win-back — no operator override path.

---

## 4. How to modify safely

Read `agent-docs/03-state-machine.md` before touching. Preserve optimistic guard, terminal set computation, do_not_call injection. After change: run `backend/tests/test_state_machine` equivalent + `test_gtm_acceptance` §24 scenarios, verify `git diff` shows only intended edge added.
