# 09 — Conversation (Reply Classification Taxonomy, Kill Switch)

## Role
Understand what prospect meant (intent) before deciding response; pause all automation on inbound; route to human where judgment matters. Spec FR-12 universal kill switch, FR-13 intent before response.

## Reply Classification Taxonomy
### Backend deterministic gates
- `services/email_service.py:359` `REPLY_CLASSES = {INTERESTED, PRICE, QUESTION, OBJECTION, NOT_INTERESTED, BOOKING_REQUEST, HUMAN_REQUIRED, UNSUBSCRIBE}` + `CLASS_ROUTING:364` mapping → hot_lead_alert, booking, notify_human, draft_for_review, suppress_and_close.
- `services/sequences.py:142` `ESCALATION_KEYWORDS = [legal,lawyer,attorney,cease,desist,spam,report,human,real person,speak to someone,call me,angry,furious,unacceptable,lawsuit,complaint,fraud]` + `HUMAN_REQUIRED_CLASSES = {HUMAN_REQUIRED, PRICE, QUESTION}`.
- `services/sequences.py:151` `classify_reply(text)` keyword only: if any escalation keyword → HUMAN_REQUIRED else INTERESTED. Minimal fallback; real classification delegated to n8n LLM workflow `n8n/workflows/reply-classification.json` per canonical `canonical.ts:614` (no backend fallback → if n8n down replies queue unclassified PARTIALLY).
- Tests: `tests/test_gtm_acceptance.py:246` compliance etc but reply classification mostly logic in services.

### Canonical 13-class (frontend simulation)
**File:** `frontend/src/gtm/canonical.ts` RESPONSE stage + `frontend/src/gtm/simulation.ts:239` SIMULATION_VARIANTS enumerate prospect replies:
- interested (curious positive)
- curious
- pricing (PRICE)
- details / proof
- objection (OBJECTION "we already have receptionist")
- not_interested (NOT_INTERESTED)
- wrong person (WRONG_PERSON "Not me, talk to Jamie jamie@...")
- later / TALK_LATER (revisit 3 months, nurture)
- ready to book (BOOKING_REQUEST)
- existing conversation
- unclear (maybe?? → ask clarifying)
- proof, timing, industry fit, do_not_call (opt-out angry/spam)

Routing per `services/email_service.py:364` + simulation decisions:
- INTERESTED → acknowledge & propose meeting, hot_lead_alert
- PRICE/QUESTION → notify human + draft for review, never auto-quote (`email_service.py:367` PRICE notify never auto-quote)
- OBJECTION → draft_for_review handle concern
- NOT_INTERESTED/UNSUBSCRIBE → suppress_and_close + `suppression.add:50` scope email value lowercased
- BOOKING_REQUEST → send booking link
- HUMAN_REQUIRED → notify human always human
- WRONG PERSON → re-identify with referral Jamie (do NOT suppress company) (`simulation.ts:249` wrongPerson)
- LATER → record timing, nurture, monitor expiry 60d (`simulation.ts:254`)
- UNCLEAR → ask clarifying, don't advance to BOOK
- OOO auto-reply → timing record, follow up appropriately not full kill (edge in `canonical.ts:565`).

### Evidence strength
- Classification returns confidence 0.0; routing ignores threshold → low confidence still routes without human review (PARTIALLY per `canonical.ts:643`).

## Kill Switch (universal)
**File:** `services/email_service.py:376` `kill_switch(conn, workspace_id, lead_id, reason)`

```python
current = SELECT status FROM leads WHERE id=%s
if can_transition(current, "responded"): UPDATE leads SET status=responded  # state_machine.py:36 allows from contacted etc but not from won/archived
DELETE FROM session_leads WHERE lead_id AND session_id IN (SELECT id FROM calling_sessions WHERE workspace_id AND status pending/active)
UPDATE messages SET status='rejected', error='kill switch: reply received' WHERE lead_id AND status IN ('approved','scheduled','pending_approval')
INSERT activities ... 'KILL SWITCH fired: {reason}'
```

- Fired by `classify_reply:424` immediately after inserting inbound message `messages inbound status replied` (`email_service.py:418`), before LLM classification — durable FIRST.
- Also via `twilio_service` for calls and `sequences.check_followup_cancellation:88` polling for outbound_messages.
- **Outbound gate companion:** `outbound_gate.py:210` sequence_state_ok checks _lead_replied_after_last_outbound via MAX(sent_at) vs inbound created_at; COALESCE to_timestamp(0) means first send always allowed even if inbound before any outbound (pre-existing conversation not blocked — edge `canonical.ts:508`).
- **Gap PARTIALLY:** deletes session_leads + marks messages rejected but `outbound_messages queued` rows remain until polling check_followup_cancellation minutes later → followups still assignable for minutes after reply ( `canonical.ts:570` ).

### Tenant scoping bug PARTIALLY
- `GET /events/pending` and `/events/poll` no workspace scoping → tenant leak (`canonical.ts:641`).

## Apply Classification (n8n posts result)
**File:** `services/email_service.py:438` `apply_classification(workspace_id, lead_id, intent_class, confidence, suggested_response)`
- Uppercases, defaults to HUMAN_REQUIRED if unknown (`email_service.py:442`).
- Inserts tasks row `handle {intent}: {routing[1]}` (`email_service.py:448`).
- If NOT_INTERESTED/UNSUBSCRIBE → inserts suppression email via `suppression.add` (`email_service.py:453`).
- Returns routing + suggested_response passthrough.

## What Component Owns vs Not
- **Owns:** inbound persistence, kill_switch, task creation, suppression on opt-out, routing map.
- **NOT owns:** LLM classification (n8n), calendar booking (human), opportunity creation.
- **Sequences owns** keyword fallback classification and cancellation of `outbound_messages` followups; email_service owns messages cancellation.

## Contracts Preserve
- Any inbound on any channel → pause all automation for lead (FR-12 enforced deterministically, not UI).
- Intent before response: do not send auto-reply before classification + human review where required.
- Wrong person never marks company suppressed; later never closes as lost.
- Suppression canonical lowercasing email (`suppression.py:50`).

## Safe vs Dangerous
- Safe: add keyword to ESCALATION_KEYWORDS, extend REPLY_CLASSES mapping with new routing, tune SIMULATION_VARIANTS for harness.
- Dangerous: remove kill_switch DELETE/UPDATE, make classification auto-send without human draft review (violates FR-13), change do_not_call injection to not include new terminals, skip suppression.add on UNSUBSCRIBE (CAN-SPAM).

## Before/After Modifying
- Before: read `services/email_service.py:376` + `services/sequences.py:83` + `frontend/src/gtm/canonical.ts:614` trace + `n8n/workflows/reply-classification.json`.
- After: Simulate inbound via `POST /outreach/classify-reply` then `POST /apply/classification`; assert lead status `responded`, messages rejected count, session_leads deleted, activities KILL SWITCH row, outbound_messages cancelled, suppression row if UNSUBSCRIBE; `pytest tests/test_email_gates.py tests/test_gtm_acceptance.py -k reply`.

## Examples
- Positive "How does it work with ServiceTitan?" → QUESTION, not HUMAN_REQUIRED → draft_for_review path (simulation `simulation.ts:172`).
- Pricing "What does it cost for 10 techs?" → PRICE → notify_human escalate true due high value P1 (simulation positivePricing).
- Wrong person "Not me — talk to Jamie in ops, jamie@abchvac..." → WRONG_PERSON → re-identify Jamie, don't suppress domain (`simulation.ts:252`).
- Unsubscribe "Please remove me" → NOT_INTERESTED/HUMAN_REQUIRED → do_not_call + global suppression email+phone+company, cancel queued, learn (`simulation.ts:264`).

## Related
- Upstream: outbound 13 checks before send; scheduler kill switches flags.
- Downstream: BOOK handoff packet includes conversation history from activities; LEARN records outcome per intent class.
