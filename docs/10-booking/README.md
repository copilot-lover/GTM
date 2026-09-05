# STAGE 11 — BOOK / HANDOFF (Meeting + Packet)

> **IETM teaching doc · Stage 11 of 12 · Progressive disclosure: 🟢 Everyone → 🟡 Operator → 🔴 Builder**
> Canonical: `frontend/src/gtm/canonical.ts:~` (`id:"book", index:11`) · Simulation: `frontend/src/gtm/simulation.ts:201` · State: `backend/app/services/state_machine.py:9` · Signals: `backend/app/services/twilio_service.py:168` · Handoff: `frontend/src/gtm/canonical.ts:converse→book howItConnects`
> **This is the "money stage" — every prior stage earns the right to arrive here; every downstream stage (RESPONSE→BOOK gap) is where value is captured or lost.**

---

# WHAT IS IT?

> 🟢 **BASIC**

**BOOK** proposes a meeting, confirms a slot, and hands `Owner → Salesperson` a **structured packet** with everything learned so far — so the first call is **relevant, not cold**.

Input: a qualified conversation (`intent READY TO BOOK` or `BOOKING_REQUEST` + verified contact + `priority P1/P2`).
Output: a booked meeting (`meetings` + `opportunities`) + **handoff briefing** + `meeting_booked` lead status.

> 🟡 Three jobs: **propose** (link + proposal), **confirm** (calendar), **brief** (evidence → opening line).

---

# WHY DOES IT EXIST?

> 🟢 Two failures without it:

1. **No packet → cold call** — salesperson re-discovers what Orbit already knew (3 areas, dispatcher strain, weak booking) and asks it again — burns trust earned in prior stages.
2. **No confirm → ghosted meeting** — `BOOKING_REQUEST` without a calendar slot, confirmation, or no-show sequence means 30% no-show at the finish line.

BOOK exists to **convert conversational interest into held pipeline** with minimum friction.

---

# WHAT GOES IN?

> 🟡 Same decision packet that ran OUTBOUND, now plus live conversation state:

- **Conversation qualification** — `P1, interest confirmed (after-hours question = buying signal), ServiceTitan stack known, timeline likely now (hiring indicates urgency)` (`simulation.ts:203`)
- **No serious objections** — `OBJECTION` handled or none; questions answered; ServiceTitan question resolved in `CONVERSE`
- **Ready signal** — explicit `"Sure, book Thursday?"` (`intent READY TO BOOK`) or implied `BOOKING_REQUEST` (`email_service.REPLY_CLASSES:359`) — not just `curious`
- **Contact + calendar** — verified `contacts.email`, operator-linked `Cal.com` embed (`BOOK` router or `twilio_service.set_disposition appointment_set`), `timezone` guard (`twilio_service.TIMEZONE_GUARD_START 8 - END 21`)

> 🔴 Guard: don't book `unclear` or `later` — ask clarifying first (`09-conversation/` rule). `leads.status` must be evolvable: `responded → qualified_conversation → meeting_booked` (`state_machine.py:7,8`).

---

# WHAT HAPPENS?

> 🟡 Four moves (`simulation.ts:201` `stage:"book"`):

1. **Detect readiness** — `RESPONSE` `BOOKING_REQUEST` or `CONVERSE` `"Sure, book Thursday 10am"` → `READY TO BOOK` → route `CLASS_ROUTING["BOOKING_REQUEST"]: send_booking_link → create meeting` (`email_service.py:364`). `scheduler` variant may also `send_booking_link` automatically if campaign configured.
2. **Propose meeting** — send `booking link` (Cal.com embed) — `schedule-followups` cadence separately; booking is not the same as outreach cadence (distinct state machine per note `canonical.ts:outreach edgeCases "No-show sequence after booking → distinct state machine (not outreach)"`). Link carries: `lead_id, opportunity_id, suggested slot (Thu 10 ET)` + packet preview.
3. **Confirm + notify** — on `Cal.com` booking, `leads status qualified_conversation → meeting_booked` via `state_machine.transition` (`state_machine.py:8`), `meetings` row `booked` emitted, `hot-lead alert` via `Telegram` + dashboard toast + `control-plane` alert (same `control → outbound` pause path but for booking alerts), `opportunities.stage → proposal|won` future.
4. **Assemble packet** — structured briefing:
   ```
   ABC HVAC (3 areas: Greensboro/High Point/Winston-Salem, 4.6★)
   Trigger: dispatcher hiring URL (fresh 3d) + weak booking (no chatbot, slow form)
   Likely problem: scheduling pressure — 50+ calls/day, overflow, after-hours gap
   History: 2 Q&A turns (ServiceTitan q → after-hours q), intent READY, objections: none
   Qual notes: owner Maria Chen verified (appolo 92% → ZeroBounce), P1 (priority 78, tier A), ServiceTitan stack confirmed
   Suggested opening: "Noticed you're hiring a dispatcher while expanding 3 areas — hear that's often peak-season call pressure..."
   Calendar: Thu 10 ET link
   ```
   — mirrors `simulation.ts:215` `informationPassedForward[1]` exactly: `"ABC HVAC (3 areas, 4.6★), trigger: dispatcher hiring URL + weak booking, likely problem: scheduling pressure, history: 2 Q&A turns, intent READY, objections: none, qual notes: owner verified, P1"`.

> 🔴 **No packet = fail** — `BOOK` must include it; otherwise downstream `PROPOSAL → WON/LOST` (`state_machine.py:11`) is flying blind.

---

# WHAT DECISIONS ARE MADE?

> 🟡 (`simulation.ts:201` decision field + `state_machine`):

- **Book now vs nurture?** → `READY TO BOOK (explicit)` vs `CURIOUS/QUESTION` (stay in CONVERSE, clarify) vs `LATER` (record 90d reminder, don't book)
- **Who owns the meeting?** → `Owner` confirmed → assign to `owner_id`; multi-location fallback may assign to regional operator (planned split — current single owner path implemented)
- **Confirm slot viability?** → `timezone_guard_ok:65` (`ZoneInfo` prospect_tz, 8am-9pm guard), else propose alternate; for calls via `twilio_service.place_call:74`, guard is enforced before dial
- **Is handoff complete enough?** → must include `business + trigger + problem hypothesis + history + qual notes + suggested opening` per canonical BOOK definition; if `evidence[]` missing → block at `qa_service.run_research_qa:376` style provenance check (planned gate, not yet hard)

---

# WHAT COMES OUT?

> 🟡

- **`meetings` record** — `status booked|held`, `calendar_link`, `brief` (packet json), `lead_id`, `workspace_id`, `scheduled_at Thu 10 ET`
- **`opportunities` record** — `stage proposal|won|lost` future, linked via `leads.company_id` joins (`opportunity._get_meeting_history:149` reads these for `history` component)
- **Lead status** `meeting_booked` (`qualified_conversation → meeting_booked`, then `meeting_booked → meeting_held → proposal → won|lost` — `state_machine.py:9-11`)
- **Handoff packet** — see above; operator reads before the call, cited in `activities` + `Telegram` alert body
- **Learning event** — `booked via dispatcher+weak-booking angle → reinforce for similar HVAC vertical` (`simulation.ts:218`) → feeds `11-learning/`

> Tables: `meetings`, `opportunities`, `leads` (`meeting_booked`), `activities` (booking system event), `tasks` if `HUMAN_REQUIRED` follow-on.

---

# REAL-WORLD EXAMPLE — ABC HVAC at BOOK

> 🟢 Local HVAC, 3 areas, hiring dispatcher, weak booking — from `simulation.ts:201` `stage:"book"`:

```
Signal:     Ready to book signal: 'Sure, book Thursday?'
Interpret:  Intent READY TO BOOK → propose meeting via Cal.com embed, confirm Thu 10 ET,
            notify owner, update opportunity stage, summarize conversation for handoff.

Decision:   BOOKED → lead qualified_conversation→meeting_booked, meeting record booked,
            hot-lead alert via Telegram + dashboard, packet assembled

Conversation:
  prospectSays: "Sure, let's book Thursday 10am."
  intent:       READY TO BOOK
  orbitReplies: "Booked — Thu 10 ET. You'll get a calendar invite. Looking forward! [System: meeting booked, handoff briefing generated, operator alerted]"
  nextAction:   Human prepares with packet, attends, closes; outcome (won/lost/no-show) feeds LEARN

Forwarded for LEARN:
  "Every outcome → better next TARGET/CONTACT/ANGLE/TIMING"
  (booked angle + source JSearch+HVAC + score 78 → similar vertical weighting)
```

> This is the user moment the entire GTM was scored for — `P1, tier A, verified` all green before this line fires.

---

# WHAT CAN GO WRONG?

> 🟡

- **Double booking** — `Cal.com` external booking + `meetings` internal row can drift; no `idempotency_key` on `meetings` insert today (needs `source_job_id`-style guard similar to `hiring_signals.py:370`)
- **No-show ghosting** — lead hits `meeting_booked` then stops; `meeting_held` never fires → pipeline report inflates booked but never won; needs no-show sequence distinct from outreach cadence (noted as separate state machine `canonical.ts` outreach edgeCases)
- **Packet stale** — `research_reports` orphaned rows after repeated research calls (`research.py:355` no dedupe) → `_get_latest_research:110` reads only latest but older `evidence[]` audit trail is already dropped from packet if only latest copied
- **Timezone wrong** — `twilio_service.TIMEZONE_GUARD_START 8 / END 21` uses `prospect_tz or America/New_York` fallback (`twilio_service.py:68`); if `prospect_tz` not enriched, window may be wrong region
- **`appointment_set` disposition path** (`twilio_service.set_disposition:168` `valid` includes `appointment_set`) → writes `leads.outcome='completed'` (`twilio_service.py:192`) which competes with `state_machine meeting_booked` path — two writers for same outcome

---

# EDGE CASES

> 🟡

- **Prospect books via phone ("Call me at 2pm")** → `twilio_service.set_disposition("appointment_set")` (`twilio_service.py:172`) inserts `activities 'appointment_set — create meeting + alert'` and transitions future — must still emit packet (packet via notes field)
- **Prospect asks to reschedule before meeting held** → `meetings.status meeting_booked` self-loop (`meeting_booked → meeting_booked`, `state_machine.py:9`) — implemented, but calendar sync not automated (manual)
- **Lead converted via reply but prospect never booked** → stays `qualified_conversation` — `CONVERSE` must handle next turn without re-scheduling already-queued follow-ups (those were already purged at `RESPONSE` kill switch)
- **Wrong-person booked meeting** — if re-identified `Jamie` books → original lead `qualified_conversation→lost` + new `Jaime` lead `meeting_booked` (planned separate-lead model; current single-lead routing needs operator split)
- **No calendar configured** — booking link fallback is manual propose (`email_service.suggested_response` draft) — `BOOK` still queues task for operator to send alternate

---

# WHAT HAPPENS NEXT?

> 🟢

- **→ MEETING HELD** — operator attends with packet, runs relevant first call (dispatcher angle opener → ServiceTitan booking walkthrough)
- **→ PROPOSAL** (`state_machine.py:11` `proposal → won|lost`) — outcome recorded as `opportunities.stage`, drives `learning_loop` `history` component for next `opportunity` scoring run
- **→ LEARN** (`11-learning/`) — **every outcome (won/lost/no-show)** is an `Observation` (`learning_loop.Observation`) that `LEARN` interprets **without rewriting behavior on N=1**

> If the meeting never holds → `meeting_booked` eventually handled by no-show handling (planned automated reschedule + learn as negative signal for angle).

---

# WHY DOES IT MATTER?

> 🟢 This is **where pipeline converts to revenue**. The packet is how Orbit earns a relevant first call — not a cold one — and how `LEARN` gets ground-truth signal that is stronger than any intent prediction: `did we win this exact angle with this exact ICP+signal combo?`

---

# DEEPER DETAIL (technical)

> 🔴 **BUILDER**

**Modules & gates:**

| File | Lines | Note |
|------|-------|------|
| `backend/app/services/state_machine.py:7` | `responded → qualified_conversation → meeting_booked → meeting_held → proposal → won/lost` | canonical lead FSM for booking path |
| `backend/app/services/twilio_service.py:168` | `set_disposition`, `valid includes appointment_set` | phone-booked meetings, writes `leads.outcome='completed'` + `activities call` + suppression if `do_not_call` |
| `backend/app/services/twilio_service.py:65` | `TIMEZONE_GUARD_START 8, END 21`, `timezone_guard_ok()` | enforce before any booking-proposed slot |
| `backend/app/services/twilio_service.py:74` | `place_call`, `DNC check` | click-to-call guard for manual confirmation calls |
| `backend/app/services/opportunity.py:149` | `_get_meeting_history` | `meetings COUNT held|booked` + `opportunities won` joins for `history` component |
| `backend/app/services/email_service.py:359` | `REPLY_CLASSES BOOKING_REQUEST` | reply → `send_booking_link` |
| `backend/app/services/scheduler.py:281` | `assign_mailboxes` dedupe | calendar confirms also deduped via `outbound_messages` pattern — not yet for `meetings` |
| `backend/app/routers/` | booking router (Cal.com) | handles `POST /api/booking/confirm` → internal meeting + lead transition |

**Tables:**

- `meetings(id, workspace_id, lead_id, status booked|held|no_show, scheduled_at, calendar_link, brief jsonb, created_at)` — created at BOOK
- `opportunities(id, lead_id, company_id, stage proposal|won|lost, value_mrr, tier, recommended_pitch, reason_now, primary_problem)` — `opportunity.compute_emv:416` uses `AVG(value_mrr)` for next EMV
- `leads(status meeting_booked|meeting_held|won|lost, priority_score, fit_status, contact_id)` + `activities(type system, summary 'meeting booked + briefing', actor system)`
- `tasks` if human escalation still pending

**Status:**
- ✅ IMPLEMENTED — status path `meeting_booked→held→proposal→won/lost`, packet assembly, hot-lead alerts, phone `appointment_set` path, timezone guard
- 🚧 PLANNED / PARTIAL — Cal.com auto-sync, no-show sequence state machine separation, meetings dedupe idempotency, Jamie-split multi-lead booking, stale-research packet hygiene

**Packet contract (builder must maintain):**
```
packet = {
  company: { business_name, city/state, google_rating, 3 areas, hvac vertical },
  trigger: { source: hiring_signal.dispatcher, job_url, posted 3d, weak booking proof },
  hypothesis: { primary_problem, reason_now, severity },
  history: { conversation: [2 Q&A], intent: READY TO BOOK, objections: [], angle: dispatcher+ads+booking },
  qual: { owner Maria Chen verified 92%, priority 78 P1 tier A, ServiceTitan confirmed },
  opening_line: "Noticed you're hiring a dispatcher while promoting new areas…"
}
```
> Every field above is already row-sourced upstream — BOOK only organizes it.

---
*Trace: `app/services/state_machine.py`, `app/services/twilio_service.py`, `app/services/opportunity.py` — `frontend/src/gtm/canonical.ts:book` · Simulation `frontend/src/gtm/simulation.ts:201`.*
