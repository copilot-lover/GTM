# STAGE 09-10 — CONVERSATION: RESPONSE + CONVERSE (13-intent taxonomy)

> **IETM teaching doc · Stages 9 & 10 of 12 · Progressive disclosure: 🟢 Everyone → 🟡 Operator → 🔴 Builder**
> Canonical: `frontend/src/gtm/canonical.ts:599` (`id:"response", index:9`), `~` (`id:"converse", index:10`) · Simulation: `frontend/src/gtm/simulation.ts:167-201` · Reply: `backend/app/services/email_service.py:357,413` · Sequences: `backend/app/services/sequences.py` · n8n: `reply-classification.json`
> **These two stages are paired — `RESPONSE` understands what was said, `CONVERSE` continues it. Teaching them separately would split intent from dialogue.**

---

# WHAT IS IT?

> 🟢 **BASIC**

**RESPONSE** classifies what the reply **means** (not just what it says) into a **13-category intent taxonomy** and **recommends what to do next** (book, draft, suppress, escalate).

**CONVERSE** continues the live dialogue — remembering history, answering consistently, handling objections, and detecting when to **escalate vs. continue**.

> Together they answer: **"What do they want, and should a human take over or should the system keep talking?"**

**13-intent taxonomy (from `frontend/src/gtm/canonical.ts:616` + `email_service.REPLY_CLASSES:359, CLASS_ROUTING:364` — unified, spec §4.1 FR-13, backed by `email_service.py` code):**

| # | Intent | Signal | Routing | Escalate? |
|---|--------|--------|---------|-----------|
| 1 | **interested** | "Looks useful, tell me more" | `hot_lead_alert` — operator handles personally | — |
| 2 | **curious** | "How does this work?" | `draft_for_review` — answer workflow | — |
| 3 | **pricing** | "How much does it cost?" | `notify_human` — **never auto-quote** | ✅ yes (high value / negotiation) |
| 4 | **details** | "Does it work with ServiceTitan?" | `notify_human` + draft for review | variant |
| 5 | **objection** | "We already have a receptionist" | `draft_for_review` — handle, operator approves | if persists |
| 6 | **not_interested** | "Not interested, thanks" | `suppress_and_close` — honor + learn | — (suppress domain+phone) |
| 7 | **wrong_person** | "Not me — talk to Jamie" | `re-identify` with referral (higher confidence) | — don't suppress domain |
| 8 | **later** | "Call me in 3 months" | nurture, record timing (90d), monitor `hiring_signals 60d` | — set reminder |
| 9 | **ready_to_book** | "Book Thursday 10am" | `send_booking_link` → create meeting | — → BOOK |
|10 | **existing_conversation** | prior thread continuation | continue using history | if prior `HUMAN_REQUIRED` |
|11 | **unclear** | "maybe??" | ask clarifying question, **don't assume** | — |
|12 | **proof** | "Send a case study?" | `notify_human` + proof packet | if high value |
|13 | **do_not_call** | "Stop spamming me!" / "Remove me" | **immediate** `do_not_call` + global suppression + audit + kill switch | — (always human-seen) |

> 🔴 Source note: the canonical `converse` detail collapses some into behavior buckets (exploring / evaluating / ready), but the 13-category `REPLY_CLASSES` above is the code truth (`email_service.py:359`). Earlier canonical gloss added timing/industry-fit splits that already resolve to `later` / `do_not_call` here.

---

# WHY DOES IT EXIST?

> 🟢 **Wrong interpretation wastes the opportunity.** A pricing question treated as rejection loses a qualified deal; a "maybe later" treated as "no" trashes a future meeting; a "wrong person with referral" treated as loss discards a better lead you were handed for free.

RESPONSE exists because **intent before response prevents misplay** (`canonical.ts:611`). CONVERSE exists because **one reply is not a conversation** — you must remember what was already said, avoid repeating questions (don't ask service area again when 3 areas already known), and recognize when you're **exploring** (discovery) vs **evaluating** (comparison) vs **ready** (books).

> The universal **kill switch** — any inbound pause ALL automation for lead — exists because **behavior always changes the path** (`email_service.kill_switch:376`, spec FR-12).

---

# WHAT GOES IN?

> 🟡 Single multiplexed input, two distinct readers:

- **Reply text + `thread_id` + `history` + previous `opportunity profile` + conversation state (from `activities`, `messages` directional, `research_reports`, `scores.priority`)** (`frontend/src/gtm/canonical.ts:612`)
  - RESPONSE reads: `inbound_text[:8000]` + `lead_id` + `leads.company_id` + `thread_id` for thread affinity
  - CONVERSE reads: full `activities (actor-labeled)` timeline + `messages (inbound vs outbound)` + `opportunity primary_problem/avoid_assumptions` + `hiring freshness` + `scoring fit` for next-turn context

> Input classification happens in **two places** — deterministic `sequences.classify_reply` keyword rules **and** LLM `n8n/reply-classification.json` — backend `email_service.classify_reply:413` is durable-first, not LLM-first.

---

# WHAT HAPPENS?

> 🟡 Two stages, sequential on every reply:

**Stage 9 — UNDERSTAND RESPONSE (classify + route + kill):**

1. **Durable-first ingest** — `email_service.classify_reply:413` receives `inbound_text`, **persists** `messages(workspace_id, lead_id, direction='inbound', body_text[:10000], status='replied')`, fires `email_service.kill_switch:376` (`conn.execute UPDATE leads status contacted→responded WHERE can_transition:[]`, `DELETE session_leads` where `calling_sessions workspace active/pending`, `UPDATE messages set rejected where approved|sched|pending_approval`, `INSERT activities 'KILL SWITCH fired'`), `INSERT tasks(type='handle HUMAN_REQUIRED: always human')`, `events.emit(conn, "reply.received", {lead_id, text[:8000]})` — all in **one transaction** (`email_service.py:418`).
2. **Classification** — two paths:
   - **n8n `reply-classification.json`** — LLM classifies `intent_class + confidence + suggested_response`. Backend counterpart `email_service.apply_classification:438` maps `intent.upper()` against `REPLY_CLASSES:359` (fallback `HUMAN_REQUIRED` if unknown) → looks up `CLASS_ROUTING:364` → inserts `tasks(type='handle {INTENT}: {action}')`, and for `NOT_INTERESTED|UNSUBSCRIBE` → `suppression.add(scope=email, value=email, reason)`.
   - **`sequences.classify_reply` keyword rules** — local keyword detection (speculative fallback when n8n down). **If n8n is down, replies queue but not classified, automation not paused until manual** — known gap (`canonical.ts:642`).
3. **Routing per class (FR-13):**
   - `INTERESTED → acknowledge & propose meeting` (hot alert)
   - `PRICE | QUESTION | PROOF → notify human + draft for review`
   - `OBJECTION → understand concern + draft handle`
   - `NOT_INTERESTED | UNSUBSCRIBE | DO_NOT_CALL → suppress + close + learn`
   - `BOOKING_REQUEST → booking link`
   - `HUMAN_REQUIRED → escalate immediately + attach packet` (high value P1, complex, sensitive)
   - `WRONG_PERSON → re-identify with named referral, don't suppress company`
   - `LATER → record timing, nurture, monitor expiry`
   - `UNCLEAR → ask clarifying, don't assume or advance to BOOK`
4. **Outcome:** `Lead status contacted→responded` (kill switch fires here), classification stored as `intent + confidence + suggested_response` (needs human review), `task` created for `HUMAN_REQUIRED` or `notify_human` queue. Duplicate support: `activities` actor-labeled (`email_service._add_activity` pattern), not hidden chain-of-thought.

**Stage 10 — CONVERSE (continue, remember, qualify):**

- Receives `RESPONSE` `intent + escalation + next_action` + full history; keeps state in `activities` timeline (actor-labeled, not hidden) plus prior `research`/`scores`.
- **Policy:**
  - Never repeat known info (ABC HVAC: don't re-ask 3 service areas — they're in `research.business_data`).
  - Never hallucinate pricing (`CLASS_ROUTING["PRICE"]: notify_human never auto-quote`).
  - Never assume `unclear→ready`; always ask clarifying and record.
  - Detect **exploring vs evaluating vs ready**: `exploring` (needs education — case study angle), `evaluating` (needs proof/pricing — careful escalation), `ready` (explicit `booking_request` or "Sure, book Thursday" → BOOK).
- **Branch handling** (`frontend/src/gtm/simulation.ts:239` `SIMULATION_VARIANTS` — side-by-side evaluation harness):
  - `positive (PRICE)` — escalate true → human handles pricing negotiation (P1)
  - `objection` — handle "AI augments, not replaces — after-hours + overflow" → if still not_interested → respect + suppress if requested
  - `wrongPerson` — `re-identify with Jamie` email explicit (confidence higher than waterfall)
  - `later` — nurture, 90d timing, set reminder
  - `unsubscribe/angry` — `do_not_call` from **any non-terminal** (`state_machine.py:29` loop) → `suppression.add` global+email+phone+company + `status do_not_call`

> 🔴 Escalation criteria (`canonical.ts:617` + `human_escalation.py`): `high value P1, complex, sensitive, HUMAN_REQUIRED class, large deal, negotiation`. `activities` sequence keeps the decision trace auditable for the operator task queue.

---

# WHAT DECISIONS ARE MADE?

> 🟡 (`frontend/src/gtm/canonical.ts:615-619`)

- **What is intent?** — pick one of 13; if multiple intents in one reply (`"price? and can it do X?"`) → pick dominant, address both in suggested draft (`canonical.ts:637`)
- **Needs escalation?** (`high value P1, complex, sensitive, HUMAN_REQUIRED, large deal, negotiation` — `human_escalation.py` criteria, plus `leads.priority_score ≥85` or `scores.tier IN (A,A+)` check in some `scheduler` paths)
- **Is this exploring vs evaluating vs ready? Should Orbit continue or hand to human?** — exploring needs education; evaluating needs proof; ready → BOOK now
- **Wrong person?** → find right contact via enriched suggestion (`enrichment.find_decision_maker_email` re-called with referral name), don't mark company `do_not_call`; later? → nurture; unclear? → ask

---

# WHAT COMES OUT?

> 🟡 Per reply:

- **`intent` + `escalation_flag` (bool) + `next_action` routing (`route: booking vs draft vs suppress`)** — `email_service.apply_classification:438` returns `{intent_class, routing, suggested_response, confidence}`
- **Kill switch fired** — `messages cancelled, session_leads deleted, operator alerted (Telegram + dashboard + control-plane + task)` — *first thing classify_reply does, before classification completes*
- **Classification + suggested draft** (needs human review) — stored as `tasks` + `activities`; `REPLY_CLASSES` not auto-acted upon for price/objection paths without operator approval
- **Lead status** `contacted → responded` (all automation stopped per FR-12) — later `responded → qualified_conversation` only after converse qualifies
- **For BOOK branch:** `BOOKING_REQUEST` signal `intent READY TO BOOK` → booking link sent via `CAL` integration (see `10-booking/`)

---

# REAL-WORLD EXAMPLE — ABC HVAC reply branching

> 🟢 Same ABC HVAC, after outreach Day 0 sent 10:15 ET via `hello@orbit-send1.com`:

**Scenario A — the documented simulate path (`simulation.ts:169` `stage:"response"`):**

```
Prospect says:  "How does this work with our booking process? We use ServiceTitan."
Intent:         QUESTION (wants details/proof, confidence 0.82, escalation false)
RESPONSE loop:  classifies QUESTION → wants ServiceTitan integration details
                kill_switch fires: automation paused for lead, session_leads deleted,
                operator alerted Telegram+dashboard "Response & Conversation · intent: QUESTION" + task
                lead contacted→responded
Next:           CONVERSE answer workflow — determine exploring vs evaluating vs ready
                update company record: ServiceTitan confirmed (no longer avoid_assumption), contactability↑
                draft (human-reviewed): "Yes — Orbit integrates with ServiceTitan… push booking/task… What's your flow?"
```

**Scenario B — CONVERSE turn (`simulation.ts:184` `stage:"converse"`):**

```
Prospect says:  "Sounds useful. Does it handle after-hours calls too?"
Intent:         CURIOUS → details + interest signal (CONVERSE intent, not RESPONSE)
Orbit replies:  "Yes — 24/7, including after-hours. … Many HVAC teams use it for after-hours + overflow when dispatch is busy. Want a 2-min walkthrough of the ServiceTitan booking flow?"
Next action:    If "yes" → BOOK; if "pricing?" → escalate HUMAN_REQUIRED (P1)
```

**Also covered as explicit variants (`simulation.ts:239` `SIMULATION_VARIANTS`):**

| Variant | Reply | Intent | Decision |
|---------|-------|--------|----------|
| `positive` | "Looks interesting! How does pricing work for 10 techs?" | `PRICE` | `HUMAN_REQUIRED` — pricing negotiation, high value P1, notify human with packet |
| `objection` | "We already have a receptionist, not interested." | `OBJECTION` | Handle 'AI augments, not replaces' → if still not_interested → respect + suppress if requested, learn |
| `wrongPerson` | "Not me — talk to Jamie in ops, jamie@abchvac..." | `WRONG_PERSON` | Re-identify with referral Jamie (higher confidence than waterfall), don't suppress company |
| `later` | "Call me in 3 months, busy season now." | `TALK_LATER` | `QUALIFIED NOT READY` → record 90d timing, nurture, monitor `hiring_signals 60d` expiry |
| `unsubscribe` | "Please remove me from your list." | `NOT_INTERESTED / UNSUBSCRIBE` | `do_not_call` + global suppression (email+phone+company), cancel queued, learn |
| `angry` | "Stop spamming me!" | `DO_NOT_CALL` | Immediate `do_not_call` from any non-terminal, global suppression, never contact again, audit logged |

> Also demonstrated in conversational detail `pipeline.py` long-expose (`simulation.ts:177` `conversation:{prospectSays, intent, orbitReplies, nextAction}`) — the only IETM doc that shows both prospect+orbit lines per turn.

---

# WHAT CAN GO WRONG?

> 🟡 (`frontend/src/gtm/canonical.ts:640` + outcome from inspection):

- **Reply classification LLM delegated to n8n `reply-classification.json` with no backend fallback** — if n8n down, replies queue but not classified, automation not paused until manual (until `kill_switch` was moved to `classify_reply:413` durable-first — now **automation pause is durable even without LLM**, but classification remains delayed)
- **`GET /events/pending` and `/events/poll` no workspace scoping → tenant leak** (intent events visible cross-workspace) — conftest gap still on `approve` read path
- **Auto-categorization confidence thresholds unused** — low confidence still routes without human review (`email_service.apply_classification:438` maps `confidence` but no `if confidence<0.6 → force human` branch)
- **Reply classification may miss CAN-SPAM unsubscribe phrase variant** (e.g., "unsubscribe me from hiring emails") → suppressed check bypassed, illegal send — needs phrase normalization vs `BANNED_PHRASES`-style heuristics
- **Kill switch deletes `session_leads` + marks `messages rejected` but `outbound_messages queued` rows remain until poll** → stale follow-ups assignable for minutes (same dual-queue gap as 08-outbound `canonical.ts:644`)
- **Out-of-office `OOO` may incorrectly fire full kill switch** if `classify_reply` treats it as inbound before `REPLY_CLASSES` discriminates `OOO` vs hard unsubscribes — should record timing + follow up appropriately, not full suppress

---

# EDGE CASES

> 🟡 (`frontend/src/gtm/canonical.ts:631` + `simulation.ts` variants):

- **Unclear reply (`"maybe??"`)** → ask clarifying question, don't assume or advance to BOOK (`canonical.ts:631` first)
- **Wrong person with referral** → re-identify using named referral (higher confidence than waterfall), don't suppress domain (see `SIMULATION_VARIANTS.wrongPerson`)
- **Angry response** → immediate `do_not_call` + global suppression + alert; **never argue** (`simulation.ts:272` angry)
- **Negative but polite** → respect, suppress if requested, learn (signal quality for similar ICP may be low)
- **Auto-reply OOO** → don't fire full kill switch; record timing, follow up appropriately (`canonical.ts:635`)
- **Multiple intents in one reply (`"price? and can it do X?"`)** → pick dominant, address both in suggested draft (`canonical.ts:637`)

---

# WHAT HAPPENS NEXT?

> 🟢 Two exits from this doc:

- **Ready → BOOK** (`10-booking/`) — `BOOKING_REQUEST / READY TO BOOK` + high `priority P1` + verified contact → propose meeting via `Cal.com` embed, confirm, notify owner, update `opportunity stage`
- **Not ready → nurture** — `LATER / UNCLEAR / OBJECTION-handled` → `leads` stays `responded|qualified_conversation`, CONVERSE loop continues, `hiring_signals` monitored for fresh signals, future 90d reminder via `tasks`

> Either path: **RESPONSE is the most important GTM step — misclassifying intent loses the meeting even if everything prior was perfect** (`canonical.ts:652`).

---

# WHY DOES IT MATTER?

> 🟢 This is where **pipeline value is captured or lost**. Correct interpretation → moves to BOOK; incorrect (treating objection as rejection) → discards a qualified opportunity. The 13-way split is not bureaucracy — it's why "We already have a receptionist" is *handled* (`AI augments…`) not *closed*, and why pricing isn't auto-quoted (which would undercut negotiation).

---

# DEEPER DETAIL (technical)

> 🔴 **BUILDER**

**Files & gates:**

| File | Lines | Purpose |
|------|-------|---------|
| `backend/app/services/email_service.py:359` | `REPLY_CLASSES 8 (+ mapping to 13 via spec)` | allowed intents: `INTERESTED, PRICE, QUESTION, OBJECTION, NOT_INTERESTED, BOOKING_REQUEST, HUMAN_REQUIRED, UNSUBSCRIBE` — gate |
| `backend/app/services/email_service.py:364` | `CLASS_ROUTING 8→(signal, action)` | `INTERESTED→hot_lead_alert, BOOKING_REQUEST→send_booking_link, PRICE→notify_human never auto-quote, QUESTION→draft for review, OBJECTION→draft, NOT_INTERESTED→suppress_and_close` |
| `backend/app/services/email_service.py:376` | `kill_switch(conn, workspace_id, lead_id, reason)` | `can_transition(current→responded)`, delete `session_leads` active+pending, reject `messages approved|sched|pending_approval`, audit `KILL SWITCH fired` |
| `backend/app/services/email_service.py:413` | `classify_reply(workspace_id, lead_id, inbound_text)` | **durably first** — `INSERT messages inbound`, `kill_switch`, `INSERT tasks`, `emit reply.received` atomically |
| `backend/app/services/email_service.py:438` | `apply_classification(...)` | `intent.upper() ∈ REPLY_CLASSES else HUMAN_REQUIRED`, `suppression.add` for NOT_INTERESTED/UNSUBSCRIBE, return `{intent_class, routing, suggested_response, confidence}` |
| `backend/app/services/sequences.py` | `classify_reply` (keyword) | deterministic fallback when n8n unreachable |
| `backend/app/n8n/workflows/reply-classification.json` | n8n workflow | LLM `reply-classifier` that posts to `apply_classification` |
| `backend/app/services/state_machine.py:20` | `responded → qualified_conversation | lost | archived` | converse FSM |
| `backend/app/services/human_escalation.py` |  | escalation predicate (high value, sensitive) |
| `backend/app/services/suppression.py` | `check, add` | hard gate, global/email/phone/company + `do_not_call` from **any non-terminal** (`state_machine.py:29` adds `do_not_call` to every non-terminal) |

**Taxonomy note (PLANNED fix):** current code `REPLY_CLASSES` lists 8; spec says 13. Missing formal entries (`curious, wrong_person, later, proof, timing, industry_fit`) already collapse to those 8 via routing — but naming mismatch creates operator confusion. Planned: normalize to 13 distinct with explicit mapping to 8 actions (flag in canonical).

**Tables:**
- `messages(direction inbound|outbound, status replied|approved|rejected|sent, body_text, thread_id, sequence_step, originating_mailbox_id, gtm_stage)` — `outbound_gate._lead_replied_after_last_outbound:80` reads these
- `tasks(type, due_at, created_by)` — `HUMAN_REQUIRED` handoff queue
- `suppression(workspace_id, scope, value, reason, created_at)` — global + per-scope checks
- `activities(workspace_id, lead_id, type, summary, actor)` — actor-labeled `system|agent|human` — **conversation state lives here**

**Status:**
- ✅ IMPLEMENTED — `classify_reply` durable-first now includes `kill_switch` before LLM; `apply_classification` routing; suppression on NOT_INTERESTED/UNSUBSCRIBE; kill-switch messaging via `outbound_messages` polling + `session_leads` purge
- 🚧 PLANNED — confidence threshold (`<0.6 → force human`) not enforced; `OOO` discrimination before full kill; private tenant scoping on `/events/pending`; deduping `outbound_messages` purge with `messages` atomically; normalize 13 vs 8 naming

**Progressive disclosure:** This doc is the only paired stage — operators must read RESPONSE before CONVERSE. Simulation `SIMULATION_VARIANTS` is the evaluation harness for the 13 intents side-by-side with ABC HVAC as the fixture.

---
*Trace: `app/services/email_service.py`, `app/services/sequences.py`, `n8n/workflows/reply-classification.json`, `app/routers/outreach.py` — `frontend/src/gtm/canonical.ts:599+`.*
