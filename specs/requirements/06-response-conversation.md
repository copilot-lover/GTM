# RESPONSE INTERPRETATION & CONVERSATION — Requirements

**Flow:** MESSAGE → MEANING → INTENT → NEXT BEST ACTION
**Status:** PARTIALLY IMPLEMENTED (n8n classification + keyword fallback; conversation state via activities).

---

## 1. Taxonomy

Possible intents (13): `interested, curious, pricing, question, objection, not_interested, wrong_person, later, ready_to_book, unclear, implementation_question, timing_question, do_not_call` — spec §4.1 FR-13 `INTERESTED/PRICE/QUESTION/OBJECTION/NOT_INTERESTED/BOOKING_REQUEST/HUMAN_REQUIRED`. Current `services/sequences.py:classify_reply` keyword-based; n8n LLM workflow `reply-classification.json` provides richer classify.

---

## 2. Responsibilities

| ID | Requirement | Classification |
|----|-------------|----------------|
| RESP-REQ-001 | System SHALL classify inbound reply intent into taxonomy with confidence | PARTIALLY IMPLEMENTED n8n workflow + keyword `sequences.classify_reply` |
| RESP-REQ-002 | System SHALL map intent→next action: HUMAN_REQUIRED escalate task, BOOKING_REQUEST → booking link, pricing/question → human notify, unsubscribe → suppression | PARTIALLY IMPLEMENTED `services/email_service.py:apply_classification` |
| RESP-REQ-003 | System SHALL fire universal kill switch on any inbound reply on any channel, pause automation, alert operator | IMPLEMENTED `services/email_service.py:kill_switch` (Twilio + email) |
| RESP-REQ-004 | System SHALL keep conversation history (all messages + activities actor-labeled) and never ask for already-known info | IMPLEMENTED `messages.thread_id`, `activities` timeline |
| RESP-REQ-005 | System SHALL recognize human handoff conditions: high-value P1, complex, sensitive, HUMAN_REQUIRED class, negotiation | IMPLEMENTED `services/sequences.py` threshold |
| RESP-REQ-006 | System SHALL handle wrong-person referral (re-identify with named referral, don't suppress company) | IMPLEMENTED spec but manual via `wrong_person` branch |
| RESP-REQ-007 | System SHALL recognize timing `TALK_LATER` and record nurture reminder vs close | PARTIALLY IMPLEMENTED `sequences` later detection |

---

## 3. Conversation invariants

- Remember prior conversation, avoid repeating, avoid asking known info, answer relevant, handle objections, recognize handoff.
- Objective is meaningful progress toward correct outcome (BOOKED / QUALIFIED NOT READY / NOT A FIT), not endless chat.

---

## 4. Verification

- `tests/test_gtm_acceptance.py` durable reply, human required fallback
