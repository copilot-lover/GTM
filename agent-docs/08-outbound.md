# 08 — Outbound (Gate 13 Checks, GTM Lifecycle, Email Service, Scheduler, Sequences)

## Role
Turn approved, verified, evidence-backed drafts into delivered sends with pacing, health-aware capacity, and behavior-reactive cancellation. Gate is judgment before send; service is transport claim; scheduler is pacing; sequences is cadence.

## Outbound Gate (13 structural checks)
**File:** `services/outbound_gate.py:96` `can_send(workspace_id, message_id) → {allowed, reasons[], checks[13]}`

Checks (lines 104-232):
1. lead_eligible — lead_status not in rejected/do_not_call/archived/lost (`outbound_gate.py:105`)
2. contact_eligible — email present and not opt_out_flag (`outbound_gate.py:112`)
3. not_suppressed — `suppression.check` email/phone/company/global (`outbound_gate.py:121`) from `services/suppression.py:15`
4. email_verified — contacts.email_verification_status == verified (`outbound_gate.py:130`)
5. copy_qa_passed — legacy? true else latest qa_runs copy status passed (`outbound_gate.py:139` _latest_qa order created_at DESC LIMIT1 vs qa_service DESC id — divergence PARTIALLY)
6. compliance_passed — latest compliance qa passed (`outbound_gate.py:149`)
7. stage_authorized — gtm_stage ∈ AUTHORIZED_SEND_STAGES (SEND_READY,SCHEDULED) from `services/gtm_lifecycle.py:20`; legacy NULL skips both QA/stage (`outbound_gate.py:137`)
8. mailbox_healthy — mailboxes.health_state != paused (`outbound_gate.py:174`)
9. domain_healthy — sending_domains status == active if sd_id else false (`outbound_gate.py:178`)
10. within_sending_limits — sent_today < daily_send_limit, date-aware fallback today 0 (`outbound_gate.py:186`)
11. provider_available — always True stub (`outbound_gate.py:197`)
12. campaign_active — campaigns status active if campaign_id else true (`outbound_gate.py:202`)
13. sequence_state_ok — inbound reply after last outbound? false→hold (`outbound_gate.py:210` _lead_replied_after_last_outbound COALESCE MAX(sent_at) vs to_timestamp(0))
14. followup_mailbox_correct — follow-up mailbox must match original inbound's originating_mailbox_id (`outbound_gate.py:219` _original_mailbox)

Fail-closed: any check failed → allowed false + reasons detail strings (`outbound_gate.py:234`). Used by `email_service.claim_for_send:162` and `GET /outreach/messages/{id}/send-decision` (`routers/outreach.py`).

**What owns:** auditable decision, never transport.
**Not owns:** actual send or health scoring.

**Missing-data:** no message → allowed false reason message not found; no mailbox bound → mailbox/domain/within limits true (no bound path), but follow-up step>0 with original missing → false.

## GTM Lifecycle
**File:** `services/gtm_lifecycle.py:31` TRANSITIONS, `59` transition_message

- Stages `STAGES:12` 17 values + legacy NULL.
- `AUTHORIZED_SEND_STAGES:20` SEND_READY,SCHEDULED only claimable.
- `can_transition:53` allows None→any (initial enrollment).
- `transition_message:59` guarded optimistic `UPDATE messages SET gtm_stage=%s WHERE id=%s AND workspace_id=%s AND gtm_stage IS NOT DISTINCT FROM %s RETURNING id` + INSERT `message_stage_events:93` with actor/reason/qa_run_id. Raises InvalidTransition on unknown/illegal/concurrent/missing.
- stage_history `gtm_lifecycle.py:111` reads events ordered created_at,id.

Enrichment: `pipeline.create_draft_message:416` enrolls NULL→QA_PENDING; `qa_service.run_copy_qa:230` QA_PENDING→QA_PASSED/FAILED; `qa_service.run_compliance_qa:299` QA_PASSED→COMPLIANCE_PENDING→SEND_READY/FAILED; `email_service.approve:92` SEND_READY→SCHEDULED; `email_service.apply_send_result:220` SCHEDULED→SENT; `email_service.schedule_followups:345` followup → SEND_READY or HELD.

**Not owns:** lead FSM.

## Email Service (transport gate + lifecycle driver)
**File:** `services/email_service.py:1`

- `can_spam_signature:51` raises SendBlocked if ORBIT_PHYSICAL_ADDRESS empty (enforced).
- `approve:71` checks status ∈ pending_approval/drafted + gtm_stage ∈ QA_PASSED/SEND_READY else blocked; updates approved_by/at, transitions SEND_READY→SCHEDULED atomically, emits message.approved.
- `reject:108` cannot reject sent.
- `claim_for_send:125` gates+atomic claim:
  - Idempotency replay: if key exists and already provider_message_id → return cached sent (`email_service.py:130`).
  - UPDATE status approved→sending RETURNING; if not claimed raise not claimable (`email_service.py:141`).
  - SET idempotency_key if provided (`email_service.py:153`).
  - **Run gates while claimed:** outbound_gate.can_send → if blocked raise SendBlocked; then email/ opt_out / verified checks + suppression.check again (`email_service.py:160`) + CAN-SPAM append. On SendBlocked → _release_claim `sending→approved` (`email_service.py:187`).
  - Returns payload {message_id,to_email,subject,body_text+sig,from_email,from_name,idempotency_key} for n8n SMTP node (backend never talks SMTP per spec §10.3).
- `apply_send_result:201` ok→ UPDATE sending→sent + activity + SCHEDULED→SENT; fail→ record_failure `send_attempts+1` → approved else failed after 3 (`email_service.py:239`).
- `record_failure:239` dead-letter after 3.
- `due_sends:252` poll approved with scheduled_send_at.
- `schedule_followups:289` creates next followup as approved(?) actually approved status (`email_service.py:332` status approved) with scheduled_send_at now+offset days, inherits mailbox via _resolve_original_mailbox (`email_service.py:266` bound else history else single ready mailbox), enrolls SEND_READY if mailbox else HELD (`email_service.py:345`). Cadence cd config `cadence_config offsets_days` (`email_service.py:308`) default [0,3,7,14].
- `kill_switch:376` (see 09) + `classify_reply:413` durable-first + `apply_classification:438` suppress on NOT_INTERESTED/UNSUBSCRIBE.
- VERIFY helpers `verify_email/_verify_email_local:488` syntax+DNS MX.

**Owns:** approval, claim atomicity, idempotency, suppression double-check, followup enrollment.
**Not owns:** QA decision, scoring.

**Pitfalls:** schedule_followups creates approved directly without approval mode check vs FR-10; claim UPDATE before gates creates race window where poll could double-claim; provider_available always True; within_sending_limits reset fallback masks stale sent_today_date elsewhere.

## Scheduler (capacity + pacing + assignment)
**File:** `services/scheduler.py:397` `tick()`

- `get_daily_capacity:104` per mailbox effective_limit = daily_send_limit * HEALTH_MULTIPLIER (`scheduler.py:22` healthy1.0 normal0.9 reduced0.6 restricted0.25 paused0.0); sent = sent_today if sent_today_date == today else 0; remaining max(0,effective-sent); domains aggregate domain_limit (600 default) (`scheduler.py:136`). **Bug** global_limit sums domain_limit per mailbox iteration double counts.
- `get_eligible_messages:164` SELECT outbound_messages status queued/scheduled eligible_at<=now shadow false deadline future ORDER priority,eligible_at.
- `campaign_allocation_filter:241` splits by kind initial/followup/other; caps initial Cap = max(min_new 50, total*40%), followup Cap = total*30% etc enforce via system_flags campaign_allocation.
- `assign_mailboxes:281` best mailbox lowest sent/effective ratio, skip health paused, domain_remaining, kill switches (`scheduler.py:35` pause_all/mailbox/domain/campaign). shadow? mark claimed shadow true else _needs_approval? pending_approval else scheduled with scheduled_slot_at via `next_available_slot:207` (business hours 08:30-16:30 + jitter 5-45m, next business day if beyond window, timezone per mailbox).
- `tick:397` capacity→eligible→allocation→assign returns assigned/deferred counts.

**Owns:** pacing, health-multiplied capacity, slot timing, allocation.
**Not owns:** message FSM (but updates outbound_messages status).

**Dual queue pitfall:** `outbound_messages` (scheduler/sequences) vs `messages` (outreach) split infra; two dashboards diverge (`frontend/src/gtm/canonical.ts:579` note).

## Sequences (followup FSM + reply classification)
**File:** `services/sequences.py:35`

- `on_initial_sent:35` creates outbound_messages followups from sequence_steps step_no>0, eligible = sent_at + offset business_days, deadline eligible+2d, kind followup priority2.
- `check_followup_cancellation:83` cancels queued/scheduled followups if inbound exists OR lead terminal (responded,qualified_conversation,meeting_booked,won,do_not_call etc) OR suppressed (reads suppression again). Called polling, not instant → minutes gap.
- `classify_reply:151` keyword ESCALATION_KEYWORDS 14 (legal/spam/human etc) → HUMAN_REQUIRED else INTERESTED; HUMAN_REQUIRED_CLASSES set.
- `create_human_task:159` inserts tasks row via leads workspace.

**Owns:** cadence creation/cancellation, keyword escalation.
**Not owns:** email transport.

## Contracts Preserve
- Only SEND_READY/SCHEDULED claimable; gate 13 checks auditable; claim_for_send must call gate before transport.
- Follow-up mailbox must equal original; scheduler must respect business hours and health multiplier.
- Idempotency key single-use; send_attempts 3→failed dead-letter.

## Safe vs Dangerous
- Safe: tune daily_send_limit 30, HEALTH_MULTIPLIER, cadence offsets, allocation pct via flags.
- Dangerous: add new gate check without updating outbound_gate tests, change AUTHORIZED_SEND_STAGES, remove mailbox mismatch check, make scheduler delete instead of defer.

## What Must Be Tested After Modification
- `pytest tests/test_email_gates.py tests/test_scheduler_outreach.py tests/test_gtm_acceptance.py -k Followup`; verify `message_stage_events` history via `services/gtm_lifecycle.py:111` and gate 13-check JSON; poll `due_sends` claim flow.

## Before/After
- Before: read `services/outbound_gate.py:96` + `gtm_lifecycle.py:31` + `email_service.py:125` + `scheduler.py:397` + `sequences.py:83`.
- After: `pytest tests/test_email_gates.py tests/test_scheduler_outreach.py tests/test_gtm_acceptance.py -k Followup`; verify `message_stage_events` history; poll `due_sends` and claim flow end-to-end.

## Examples
- Gate all-pass: P1 verified, not suppressed, QA passed, SEND_READY, mailbox a@test.dev healthy, domain active, 3/30 today, step0→allowed true. Wrong mailbox followup b≠a → followup_mailbox_correct false → HELD (`tests/test_gtm_acceptance.py:288`).
- Scheduler: 2 mailboxes healthy 30 limit, 60 eligible → allocation 40% initial 24 etc, assign lowest ratio slots jittered.
