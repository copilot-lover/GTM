# 03 — State Machines (Lead FSM + GTM Message FSM)

## Lead FSM
**File:** `services/state_machine.py:6` `TRANSITIONS`

```
new → {enriching, rejected}
enriching → {qualified, signal_holding, outreach_ready, rejected}
qualified → {signal_holding, outreach_ready, contacted, rejected, do_not_call}
signal_holding → {outreach_ready, qualified, archived, expired_rejected}
outreach_ready → {contacted, rejected, do_not_call}
contacted → {responded, contacted, unreachable, do_not_call, archived}
responded → {qualified_conversation, lost, archived}
qualified_conversation → {meeting_booked, lost}
meeting_booked → {meeting_held, meeting_booked, lost}
meeting_held → {proposal, won, lost}
proposal → {won, lost}
won → ∅
lost → {archived}
rejected → ∅
do_not_call → ∅
unreachable → {archived}
archived → ∅
+ do_not_call injected from any non-terminal (lines 29-31)
TERMINAL = won,rejected,do_not_call,archived (line 33)
```

### Valid entry/exit
- Entry only via `transition(conn, lead_id, workspace_id, current, target)` (`state_machine.py:40`) which calls `can_transition(current,target)` (`state_machine.py:36`) then `UPDATE leads SET status=%s WHERE id=%s AND workspace_id=%s AND status=%s RETURNING id`. Returns False on stale (optimistic), raises HTTPException 409 on illegal hop.
- Exit from `new` must go through `enriching` or `rejected` — never direct to `qualified` (enforced by TRANSITIONS; `pipeline.apply_qualification` respects `target = rejected if rejected else enriching` `pipeline.py:266`).
- `contacted` self-loop allowed (line 12) for multiple sends before reply; `meeting_booked` self-loop for reschedule.

### Prohibited transitions
- `new → won` (test asserts false `tests/test_state_machine.py:14`).
- `rejected → *`, `won → *`, `do_not_call → *`, `archived → *` (terminal).
- `enriching → won` without passing `qualified` → blocked.
- Must not add `do_not_call` egress from terminal (loop at 29-31 excludes won/rejected/do_not_call/archived).

### Missing-data behavior
- Enrichment hard-gated: `pipeline.apply_enrichment` raises if `fit_status != qualified` (`pipeline.py:281`). Missing owner/email → `review_reasons` appended (`pipeline.py:288`) but never invented (`enrichment.py:238` ON CONFLICT DO NOTHING; `pipeline.py:212` owner_name=None fail-closed).
- `pipeline.stage_context:178` enrichment raises `no website` and flags review if website null.
- `intent_engine.ingest_event:73` resolves lead from company if lead_id omitted; if both null, still inserts event with no lead (orphan, later resolved via `_resolve_lead_for_company`).

### Suppression / do_not_call
- `do_not_call` is hard compliance override from any non-terminal (`state_machine.py:29`). Triggered via `suppression.check` and reply `NOT_INTERESTED/UNSUBSCRIBE` (`services/email_service.py:453` add suppression) or manual call disposition `twilio_service.py:246` can_transition to do_not_call.
- Once `do_not_call`, `outbound_gate` blocks (`outbound_gate.py:105` bad_lead_statuses includes do_not_call) and `sequences.check_followup_cancellation` cancels (`sequences.py:100` includes do_not_call).

### Reply handling & kill switch
- Inbound → `email_service.classify_reply` (`email_service.py:413`) inserts `messages inbound status=replied`, fires `kill_switch` (`email_service.py:376`): attempts `leads status → responded` if can_transition, DELETE `session_leads` active, UPDATE `messages` approved/scheduled/pending_approval → rejected, INSERT `activities` KILL SWITCH, emit `reply.received`.
- Self-loop `contacted → contacted` does NOT fire kill switch; only `contacted → responded` does. If lead already `responded`, further replies keep status but cancellation still purges followups via `sequences.check_followup_cancellation:88` reply exists check.

### What must be tested after FSM change
- `tests/test_state_machine.py:6` happy_path + terminal + invalid raises 409 + optimistic guard.
- `tests/test_state_transitions_comprehensive.py` full matrix.
- `tests/test_pipeline.py:109` enrichment gating + `tests/test_gtm_acceptance.py:246` compliance failure cannot send.

## GTM Message FSM
**Files:** `services/gtm_lifecycle.py:31` TRANSITIONS, `services/gtm_lifecycle.py:20` AUTHORIZED_SEND_STAGES, `db/migrations/0008_gtm_agents.sql:13` gtm_stage NULL allowed.

```
DISCOVERED → QUALIFIED → INTENT_SCORED → RESEARCHED → COPY_GENERATED → QA_PENDING → QA_PASSED → COMPLIANCE_PENDING → SEND_READY → SCHEDULED → SENT
QA_PENDING → QA_FAILED → (COPY_GENERATED|HELD|CANCELLED)
QA_PASSED → COMPLIANCE_PENDING
COMPLIANCE_PENDING → COMPLIANCE_FAILED|SUPPRESSED|HELD|CANCELLED  (or SEND_READY)
SEND_READY → SCHEDULED|HELD|EXPIRED|SUPPRESSED|CANCELLED
SCHEDULED → SENT|HELD|EXPIRED|SUPPRESSED|CANCELLED
HELD → QA_PENDING|CANCELLED|EXPIRED
SENT/SUPPRESSED/EXPIRED/CANCELLED → ∅
AUTHORIZED_SEND_STAGES = SEND_READY, SCHEDULED (line 20)
FAILURE_STAGES = QA_FAILED,COMPLIANCE_FAILED,SUPPRESSED,HELD,EXPIRED,CANCELLED (line 22)
```

### Valid entry/exit
- Entry: `pipeline.create_draft_message` inserts `messages status=pending_approval` then `gtm_lifecycle.transition_message(ws,msg,"QA_PENDING")` (`pipeline.py:432`). First transition allows `from_stage IS NULL` via `can_transition(None, any)` (`gtm_lifecycle.py:54`). Enforced with `IS NOT DISTINCT FROM` optimistic (`gtm_lifecycle.py:86`).
- Exit to SENT only from SCHEDULED (`gtm_lifecycle.py:44`) via `email_service.apply_send_result` when `gtm_stage==SCHEDULED` → SENT (`email_service.py:220`).
- Legacy rows `gtm_stage IS NULL` skip QA/compliance/stage checks in `outbound_gate.py:137` (managed vs legacy).

### Prohibited
- `COPY_GENERATED → SENT` (test `tests/test_gtm_acceptance.py:408` invalid jump rejected).
- `QA_PENDING → SEND_READY` without passing QA_PASSED→COMPLIANCE_PENDING.
- `HELD → SENT` without re-queuing through QA_PENDING.

### Missing-data
- `run_copy_qa` expects `QA_PENDING` else QAError if stage not null and not QA_PENDING (`qa_service.py:237`).
- `run_compliance_qa` expects `QA_PASSED` or `COMPLIANCE_PENDING` else QAError (`qa_service.py:312`).
- Follow-up without mailbox → HELD (`email_service.py:348` no originating mailbox).

### Suppression / Reply
- `COMPLIANCE_FAILED` from compliance QA failed; `SUPPRESSED` from gate or compliance; `HELD` from mailbox mismatch, kill switch, or QA retry ceiling (`qa_service.py:438` max attempts exceeded).

### Tests
- `tests/test_gtm_acceptance.py:112` QA rejection→resubmit→pass; `246` compliance failure blocks; `288` followup mailbox held; `408` invalid stage jump; `425` claim blocked at unauthorized stage.

## Safe vs Dangerous
- Safe: add new allowed edge via flag + test, improve error message detail.
- Dangerous: remove terminal guard, allow direct status write, change AUTHORIZED_SEND_STAGES without updating gate + email_service.

## What Must Be Tested After Modification
- `pytest tests/test_state_machine.py tests/test_state_transitions_comprehensive.py tests/test_gtm_acceptance.py -k "stage or gate or transition"`; assert stage_history events and gate blocks unauthorized.

## Contracts must preserve
- Never bypass `can_transition` checks; never write `gtm_stage` directly except via `transition_message`.
- Stage history via `message_stage_events` (`gtm_lifecycle.py:111`) + `stage_history`.
- Outbound gate requires `AUTHORIZED_SEND_STAGES` + latest QA passed (`outbound_gate.py:154`).
