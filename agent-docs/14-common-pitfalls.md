# 14 — Common Pitfalls (Top Mistakes: Why They Hurt, How to Avoid)

## 1. Bypassing state_machine / gtm_lifecycle
**Mistake:** `UPDATE leads SET status='qualified' WHERE id=%s` directly or `UPDATE messages SET gtm_stage='SEND_READY'` without `transition()`.
- **Why hurts:** Breaks optimistic guard (`services/state_machine.py:48` `WHERE status=%s RETURNING`), breaks audit `message_stage_events` (`services/gtm_lifecycle.py:93`), creates orphan state not in TRANSITIONS, breaks terminal invariants (`state_machine.py:33`), makes `can_send` stage check (`outbound_gate.py:154`) disagree with DB.
- **Correct:** `state_machine.transition(conn, lead_id, ws, current, target)` (`state_machine.py:40`) handling 409; `gtm_lifecycle.transition_message(ws, msg, to_stage, actor, reason, conn)` (`gtm_lifecycle.py:59`).
- **Test:** `tests/test_state_machine.py:31` guard returns False on stale, `tests/test_gtm_acceptance.py:412` invalid jump raises InvalidTransition.

## 2. Inventing contacts / emails / findings
**Mistake:** Constructing `owner_name` from business_name, synthesizing `info@business.com`, or `research fallback` generic "High inbound..." without source.
- **Why hurts:** Violates `services/pipeline.py:212` fail-closed `owner_name=None`, `services/enrichment.py:223` NEVER guess, triggers `qa_service` UNSUPPORTED_FACT (`qa_service.py:198`), wastes enrichment quota, hallucination QC fail (`research.py:258`).
- **Correct:** Return null/empty if not verbatim in content; insert with `ON CONFLICT DO NOTHING` and flag review (`pipeline.py:288` review_reasons "owner name not found").
- **Flag:** `enrichment.py:27` TARGET_FIELDS owner_email but `COMPANY_ENRICHABLE_FIELDS:44` lacks it → silent drop already PARTIALLY; don't add more invented fields.

## 3. Dual status columns (messages.status vs gtm_stage)
**Mistake:** Setting `status='approved'` without also transitioning `gtm_stage` to SCHEDULED, or vice versa, or assuming one implies other.
- **Why hurts:** `email_service.approve:71` checks both: status ∈ pending_approval/drafted AND gtm_stage ∈ QA_PASSED/SEND_READY (`email_service.py:82`). `outbound_gate` checks gtm_stage authorized (`outbound_gate.py:154`) while `claim_for_send` checks status approved (`email_service.py:142`). Mismatch → claim blocked with confusing reason.
- **Correct:** `approve()` does both atomically `UPDATE status + transition_message SEND_READY→SCHEDULED` in same connection (`email_service.py:92`), `schedule_followups` enrolls both SEND_READY/HELD and status approved (`email_service.py:345`).
- **Test:** `tests/test_gtm_acceptance.py:425` claim blocked at QA_PENDING both must align.

## 4. Conflating the three scores
**Mistake:** Using priority_score (0-100 order) as icp_fit_score (0-10 is it ICP?) or hiring_intent_score (0-100 how strong timing?).
- **Why hurts:** `frontend/src/gtm/canonical.ts:229` decisions require all three separately; mixing makes QUALIFY threshold `QUALIFY_THRESHOLD 6` (`scoring.py:20`) mis-fire, P1/P2 bands (`scoring.priority_tier:84` vs `intent_engine:256`) diverge.
- **Correct:** `icp_fit_score:39` → fit_status, `priority_score:71` → order/when, `hiring_intent_score:113` → timing depth. Keep distinct columns `lead_score`, `priority_score`, `signal_score`.

## 5. Changing divisor/threshold without recalibration
**Mistake:** Change `score/1.8` to `/2.0` or `QUALIFY_THRESHOLD 6` to 5 without updating tests/simulation.
- **Why hurts:** `tests/test_scoring.py:11` perfect small → ≥8 assumption shifts; `pipeline.apply_qualification:244` priority calc shifts; `canonical.ts:244` edge borderline 10→6 vs 11→6 ambiguity amplifies; intent_engine base_icp*10 tightly coupled.
- **Correct:** Update `tests/test_scoring.py` expectations + `frontend/src/gtm/simulation.ts:98` breakdown + `canonical.ts` edgeCases.

## 6. Skipping verification waterfall prechecks
**Mistake:** Calling provider verify without `enrichment._local_prechecks:279` disposable 22 + spam-trap + DNS MX.
- **Why hurts:** Burns quota `track_provider_usage:109` reserve 20, hits disposable trap, degrades deliverability.
- **Correct:** `verify_email_waterfall:318` runs local 0.3-0.6 confidence then waterfall zerobounce>hunter_verify (`enrichment.py:360`) only if local passes.

## 7. Phone/email normalization caller-dependent
**Mistake:** Storing raw "(336) 555-0000" in suppression but checking normalized "+13365550000" or vice versa.
- **Why hurts:** `suppression.check:15` lowercases email but phone not normalized → suppressed phone bypasses if stored normalized vs raw (`canonical.ts:315`).
- **Correct:** Always `services/phones.py:9` normalize_phone before insert/check; `suppression.add:50` lowercases email scope value.

## 8. Using legacy NULL gtm_stage as feature
**Mistake:** Relying on `outbound_gate.py:137` legacy skip (NULL→ QA/compliance/stage bypass) to send new messages without QA.
- **Why hurts:** Opens spam hole; new messages must enroll via `pipeline.create_draft_message:432` NULL→QA_PENDING.
- **Correct:** Always enroll managed rows; keep legacy path only for pre-existing flows.

## 9. Scheduler global_limit double count
**Mistake:** Summing `global_limit += domain_limit` inside mailbox loop (`scheduler.py:155`).
- **Why hurts:** Over-allocates capacity, exceeds domain daily_cap 600, skips rate limit, triggers health downgrade `mailbox_health.py:20`.
- **Correct:** Sum per domain_key once; fix noted PARTIALLY.

## 10. Missing mailbox binding on followup
**Mistake:** Creating followup without `originating_mailbox_id` (resolver returns None when multiple ready mailboxes).
- **Why hurts:** `outbound_gate.py:223` followup_mailbox_correct false, `email_service.schedule_followups:348` marks HELD, silent drop, or gate blocks.
- **Correct:** `_resolve_original_mailbox:266` needs bound or history or exactly one ready mailbox else HELD; ensure campaign assignment gives single mailbox.

## 11. Not handling unordered QA run tie
**Mistake:** Querying latest QA with `ORDER BY created_at DESC LIMIT1` (`outbound_gate.py:56`) vs `created_at DESC, id DESC` (`qa_service.py:117`).
- **Why hurts:** Concurrent QA runs same timestamp → gate reads older than QA service wrote, decision mismatch.
- **Correct:** Use `created_at DESC, id DESC` everywhere; currently divergent PARTIALLY.

## 12. Reply kill switch partial purge
**Mistake:** Deleting `session_leads` + marking `messages` rejected but leaving `outbound_messages queued` (`services/email_service.py:376` vs `sequences.py:83`).
- **Why hurts:** Scheduler still assigns followup for minutes after reply, sends to now-suppressed lead (legal risk).
- **Correct:** Also call `check_followup_cancellation` immediately in same txn or make polling instant; tests `tests/test_gtm_acceptance.py:288` show gap.

## 13. Conflation of outreach_queues
**Mistake:** Querying `messages` for scheduler capacity while followups live in `outbound_messages`.
- **Why hurts:** `scheduler.py:164` eligible from outbound_messages, `email_service.py:252` due_sends from messages — two dashboards show different reality (`canonical.ts:570`).
- **Correct:** Keep both in sync via schedule_followups that writes messages + outbound_messages via sequences.on_initial_sent; audit counts from both.

## 14. Making backend call LLM
**Mistake:** Importing LLMProvider directly in service and calling `complete()` instead of via n8n.
- **Why hurts:** Breaks `services/pipeline.py:1` deterministic boundary, breaks n8n contract `GET context → LLM → POST apply`, mixes cost tracking.
- **Correct:** Keep backend pure; only `services/hiring_signals.py:87` + `research.py:181` + `website_intel.py:196` call LLM via provider abstraction with cheap/strong tier and fallback; new code should follow same pattern or delegate to n8n.

## Safe vs Dangerous Summary
- Safe: additive, flagged PARTIALLY, behind flag, with tests.
- Dangerous: rewrite FSM without migration, invent data, bypass gate, conflate queues/scores.

## What Must Be Tested After Modification
- `pytest tests/test_state_machine.py tests/test_pipeline.py tests/test_gtm_acceptance.py tests/test_email_gates.py` — must all pass on orbit_test.

## Quick checklist before push
- [ ] No direct status/gtm_stage UPDATE outside transition()
- [ ] No invented email/name/finding (null if missing)
- [ ] status + gtm_stage kept consistent if both touched
- [ ] Verify waterfall prechecks still run before provider
- [ ] Phone normalized via `phones.py:9` before suppression compare
- [ ] Offer in OFFER_CATALOG + PAIN_TO_OFFER mapped if new
- [ ] Tests cover both happy + rejected + blocked paths
- [ ] `pytest` on orbit_test passes, no real email sent

## Related docs
- 01-global-rules.md invariants
- 03-state-machine.md FSM graphs
- 13-change-protocol.md 9 steps
