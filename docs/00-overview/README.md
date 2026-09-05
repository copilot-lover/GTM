# Orbit GTM OS — Overview

> **IETM teaching doc · Progressive disclosure: 🟢 Everyone → 🟡 Operator → 🔴 Builder**
> Canonical source: `frontend/src/gtm/canonical.ts:11` (12 stages) + `frontend/src/gtm/simulation.ts:30` (ABC HVAC)
> Architecture viewpoint: `orbit-gtm-os.html` + `orbit-gtm-os.architecture.json`

---

# WHAT IS IT?

> 🟢 **BASIC**

Orbit GTM OS is a **continuous decision system** for go-to-market — not a funnel, not a campaign tool. It runs `FIND → UNDERSTAND → QUALIFY → IDENTIFY → OPPORTUNITY → DECIDE → GATE → OUTREACH → RESPONSE → CONVERSE → BOOK → LEARN → (back to FIND)` as a closed loop (**shorthand: FIND→BOOK→LEARN continuous decision system**). Every stage observes, reasons, acts or stops, and learns.

Two brains run underneath the loop:

- **GTM_LEADS** — business understanding + ICP eligibility (`frontend/src/gtm/canonical.ts:56`)
- **GTM_INTENT** — signal ingestion + timing + priority re-evaluation (`backend/app/services/intent_engine.py:1`)

Together they turn public signals into **verified, evidence-backed conversations** that a human can book.

```
FIND (discover universe)
  → UNDERSTAND (enrich context) → QUALIFY (score Fit+Need+Timing)
  → IDENTIFY (who to talk to)   → OPPORTUNITY (hypothesis + angle)
  → DECIDE (message strategy)    → GATE (judgment before send) → OUTREACH (cadence that reacts)
  → RESPONSE (what did they mean?) → CONVERSE (continue & qualify)
  → BOOK (meeting + handoff packet) → LEARN (observation vs interpretation → next FIND)
```

> 🟡 **OPERATOR** — The loop is durable: PostgreSQL + job queue + event outbox drive it. Nothing is fire-and-forget. Every transition is auditable via `activities`, `scores`, `qa_runs`, `message_stage_events`.

---

# WHY DOES IT EXIST?

> 🟢 Without a decision loop, teams spam the same 200 contacts. Orbit exists to answer four questions **every time** before contacting anyone:
> 1. Is this business real and worth attention now?
> 2. Do we know who can decide?
> 3. Do we have a credible, evidenced reason to talk?
> 4. Is timing right — or should we hold?

If any answer is no, the system **fails closed** (holds, rejects, or routes to human review) — protecting deliverability, compliance, and prospect respect. Fail-closed is the core GTM principle (`backend/app/services/pipeline.py:103`).

---

# WHAT GOES IN?

> 🟢 Public signals the system can observe — not claimed facts:

- Business directories, Maps, hiring postings, ads, reviews, BBB/Yelp, websites, social
- Website scrape results (`backend/app/services/website_intel.py:96`), hiring signals (`backend/app/services/hiring_signals.py:265`)
- Enrichment returns (Apollo/Hunter/Clearbit via `backend/app/services/enrichment.py:144`)
- Intent events (`backend/app/services/intent_engine.py:58` — `JOB_POSTED`, `EXPANSION`, etc.)
- Reply text + thread history (`backend/app/services/email_service.py:413`)

> 🔴 `hiring_signals` and `job_postings` are dual tables — migration consolidation pending (`frontend/src/gtm/canonical.ts:133`). Treat hiring_signals as source of truth for scoring.

---

# WHAT HAPPENS?

> 🟡 The 12 stages are implemented as **two cooperating state machines**:

| Machine | File | Stages | Rule |
|---------|------|--------|------|
| **Lead FSM** | `backend/app/services/state_machine.py:6` | `new → enriching → qualified → signal_holding → outreach_ready → contacted → responded → qualified_conversation → meeting_booked → won/lost` | `can_transition()` guards every move; `do_not_call` allowed from any non-terminal |
| **Message lifecycle** | `backend/app/services/gtm_lifecycle.py:12` | `DISCOVERED → QUALIFIED → RESEARCHED → COPY_GENERATED → QA_PENDING → QA_PASSED → COMPLIANCE_PENDING → SEND_READY → SCHEDULED → SENT` (plus `HELD`/`SUPPRESSED`/`EXPIRED`) | `AUTHORIZED_SEND_STAGES = ('SEND_READY','SCHEDULED')`; only these may be claimed by `email_service.claim_for_send()` |

Backend owns **state + validation**; n8n owns **I/O** (scrape, LLM, SMTP) via `stage_context()` / `apply_*` in `backend/app/services/pipeline.py:165`. Split is spec §10.3 — backend never calls LLM.

---

# WHAT DECISIONS ARE MADE?

> 🟢 At every stage: **Advance, Hold, Reject, or Escalate** — never guess.

- **Advance** — evidence supports next stage (e.g., `fit_status=qualified` → enrich)
- **Hold** — not enough confidence; keep monitoring (`signal_holding`, `HELD` via `qa_runs.failed_rules`)
- **Reject** — `rejected_too_large`, `rejected_not_relevant`, `expired` (`backend/app/services/scoring.py:55`)
- **Escalate** — human review queue (`review_reasons` array in `pipeline.py:75`)

> 🔴 Hard gates that cannot be bypassed: enrichment requires `fit_status==qualified` (`pipeline.py:178`), draft requires `primary_pain + recommended_offer` (`pipeline.py:386`), send requires gate `allowed=true` (`outbound_gate.py:96`).

---

# WHAT COMES OUT?

> 🟡 One of three terminal outcomes per lead:

1. **Meeting booked** — `meeting_booked` + handoff packet (company + pain + evidence + conversation history)
2. **Correctly suppressed** — `do_not_call`/`rejected`/`suppression` table (global/email/phone/company scope)
3. **Learning** — observation logged for next FIND cycle (`backend/app/services/learning_loop.py:43` requires N≥10 before changing behavior)

Every stage also emits auditable rows: `leads`, `companies`, `hiring_signals`, `research_reports`, `messages`, `scores`, `qa_runs`, `message_stage_events`, `activities`.

---

# REAL-WORLD EXAMPLE — ABC HVAC

> 🟢 **Running example used in every doc** · Source: `frontend/src/gtm/simulation.ts:30-44`

**ABC HVAC** — Local HVAC, 3 service areas (Greensboro / High Point / Winston-Salem), hiring **dispatcher** ($18–22/hr, "answer 50+ calls/day"), weak booking flow (no chatbot, mobile 62, slow forms), 4.6★ 82 reviews, 6-10 employees, owner-visible, Google Ads active.

| Stage | What happens to ABC HVAC |
|-------|--------------------------|
| **FIND** | Maps + JSearch detect dispatcher posting (fresh 3d, URL logged) → SHA-256(`ABC HVAC|Greensboro|NC`) dedupes → `companies` + `leads status=new` |
| **UNDERSTAND** | Crawl finds no chatbot, weak CTA, after-hours gap; reviews + ads confirm demand |
| **QUALIFY** | ICP 8/10 + intent 78 → `priority 78 P1 HIGH-VALUE FIT` (explanation: 31.2 + 24 + 12 + 5) |
| **IDENTIFY** | Waterfall finds owner **Maria Chen** via Apollo 92% → ZeroBounce verified → not suppressed |
| **OPPORTUNITY** | `research_reports` hypothesis: dispatch strain + booking friction → offer `ai_receptionist`, confidence medium-high, reason NOW: hiring + ads |
| **DECIDE→GATE→OUTREACH** | 73-word draft cites posting URL → 13 gate checks pass → operator approves → sent via `hello@orbit-send1.com` Day 0; Day 3 follow-up queued |
| **RESPONSE→CONVERSE→BOOK** | Reply "How does this work with ServiceTitan?" → `QUESTION` → kill switch fires → human answers → "Sure, Thu 10am" → `meeting_booked` |
| **LEARN** | Booking via dispatcher+weak-booking angle recorded; after N≥10 HVAC dispatchers, weight this signal higher for similar verticals |

See the full 12-step simulation: `frontend/src/gtm/simulation.ts:46` (`ABC_HVAC_SIMULATION`).

---

# WHAT CAN GO WRONG?

> 🟡 Systemic risks (details per stage in `frontend/src/gtm/canonical.ts:119`):

- Scraping blocked → provider returns `[]` silently; no alert if all sources 0
- Dual writes drift (`companies.tech_signals` vs `leads.website_findings`) if cache stale
- Direct DB inserts bypass dedupe → duplicates with whitespace/casing variance
- No RLS tenant leak if `workspace_id` omitted (conftest found `/events/pending` unscoped)
- `provider_available` check always `True` (`outbound_gate.py:197`) — real SMTP failure only caught at send time

> 🔴 Reference failure catalog: `orbit/docs/14-failure-modes/` (planned) + `frontend/src/gtm/canonical.ts:whatCanGoWrong` per stage.

---

# EDGE CASES

> 🟡

- Duplicate name with spelling variance → SHA-256 + phone-normalized dedupe catches it
- No website → profiled from Maps + jobs, marked low-info, stays monitoring
- Multi-location vs franchise → suppressed (`rejected_too_large`) regardless of score
- Reply before any outbound → `sequence_state_ok` uses `COALESCE(MAX(sent_at), to_timestamp(0))` — first send still allowed; handled by `RESPONSE` kill switch
- Legacy `messages.gtm_stage IS NULL` skips QA/compliance/stage checks (`outbound_gate.py:137`) — intentional for pre-existing rows

---

# WHAT HAPPENS NEXT?

> 🟢 After understanding the loop, the next docs walk each segment in order:

1. `01-system/architecture.md` — how the loop is built (Frontend → API → Postgres → n8n → Twilio)
2. `02-gtm-leads/` + `03-gtm-intent/` — the two brains
3. `04-discovery` → `11-learning` — each stage as an IETM module
4. `19-onboarding/` — Learn Mode + simulation to practice the whole flow

> Reading order is sequential: overview → architecture → brains → stages 1-12 → onboarding.

---

# WHY DOES IT MATTER?

> 🟢 GTM is not a one-time list purchase. It's a **machine that finds fewer, better leads with a clear reason to reach out**. Every downstream decision (who to contact, what to say, when to send, when to stop) cites evidence produced upstream. Without the loop, personalization is mail-merge; with it, every message earns the right to be sent.

This is what makes Orbit **not spam**: `GATE` is the judgment before send, `RESPONSE` is the understanding before reply, `LEARN` is the memory before next cycle.

---

# DEEPER DETAIL (technical)

> 🔴 **BUILDER — progressive disclosure: read only if implementing**

**Implementation trace:**

- Single source of truth for stage definitions: `frontend/src/gtm/canonical.ts:76` (`GTM_STAGES` 12 entries, each with `trace.backendModules`, `trace.tables`, `whatItIs…advanced`)
- Simulation source of truth: `frontend/src/gtm/simulation.ts:46` (12 `SimulationStep` + `SIMULATION_VARIANTS` for 6 reply types)
- Backend entry points:
  - `backend/app/services/pipeline.py:165` `stage_context()` — n8n prompt context (deterministic, never calls LLM)
  - `backend/app/services/pipeline.py:240-413` `apply_*` — validation + state + events (emit next stage via `events.emit`)
  - `backend/app/services/state_machine.py:6` + `gtm_lifecycle.py:12` — dual FSMs, optimistic `UPDATE … WHERE status=%s` guards
  - `backend/app/services/intent_engine.py:181` `reevaluate_lead()` — recency-decayed contributions, `MAX_SIGNAL_CONTRIBUTION=35`, writes `scores` row `score_type='opportunity'`
  - `backend/app/services/outbound_gate.py:96` `can_send()` — 13 structural checks, auditable `{allowed, reasons, checks}`
  - `backend/app/services/email_service.py:125` `claim_for_send()` — idempotency + gates + `can_spam_signature()` hard requirement
  - `backend/app/services/qa_service.py:177,250` `run_copy_qa()` / `run_compliance_qa()` — deterministic critics, fail-closed

**Status:**

- ✅ **IMPLEMENTED** — 12 stages, 2 brains, dual FSMs, gates, waterfall enrichment, hiring signals, research + opportunity scoring, kill switch
- 🚧 **PLANNED** — `orbit/docs/12-state-machine/README.md` linked; `14-failure-modes` catalog; auto-reweighting after N≥10 (learning thresholds exist in `learning_loop.py:38` but not wired to auto-adjust thresholds yet)

**Progressive disclosure contract:** Every IETM doc follows `WHAT IS IT? → … → WHY DOES IT MATTER? → DEEPER DETAIL`. `DEEPER DETAIL` is always last and always marked 🔴 Builder.

---
*Generated from `frontend/src/gtm/canonical.ts:76` + `orbit-gtm-os.architecture.json`. Do not edit stage names without updating canonical.ts.*
