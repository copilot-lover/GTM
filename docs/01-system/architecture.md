# System Architecture — Orbit GTM OS

> **IETM teaching doc · Progressive disclosure: 🟢 Everyone → 🟡 Operator → 🔴 Builder**
> Viewpoint source: `orbit-gtm-os.html` · Config: `orbit-gtm-os.architecture.json` · 13 components, 3 guided views

---

# WHAT IS IT?

> 🟢 **BASIC**

The architecture is **one VM, two responsibilities**: the **backend owns state** (PostgreSQL + state machines + gates), **n8n owns I/O** (scrape, LLM, SMTP, phones). The frontend observes — it never decides sendability.

Viewpoints in `orbit-gtm-os.html` (archify):
- **request-path** — a lead from browser → API → durable state → async orchestration
- **intelligence** — where qualification, research, scoring are produced and validated
- **outbound** — send path, health checks, kill switches

> Diagram shows 13 components inside a single region `orbit/backend + frontend + n8n (single VM)` with a `workspace isolation · suppression · QA` security group.

---

# WHY DOES IT EXIST?

> 🟢 Separation prevents two failure modes:
> 1. **Long I/O inline** — if the API called LLMs or scrapers synchronously, requests would hang for seconds and retry storms would corrupt state. Instead the API validates, emits an event, and returns; n8n does the slow work and posts back via `POST /api/pipeline/{id}/apply/{stage}` (`backend/app/services/pipeline.py:1`).
> 2. **Stuck automation** — Postgres `job_queue` + `outbox` (`queue` component, `SKIP LOCKED · LISTEN` on `orbit_events`) makes every transition durable and observable. If n8n is down, jobs queue; when it returns, it polls and resumes.

> 🟡 Without this split, spam and data corruption are one stray `UPDATE` away. Gate checks live in **code** (`outbound_gate.py:96`, `email_service.py:125`), not in the UI.

---

# WHAT GOES IN?

> 🟡 Layers (from outer to inner, per `orbit-gtm-os.architecture.json:components`):

| Layer | Component | Position | What it handles |
|-------|-----------|----------|----------------|
| **Frontend** | `React + Vite :8100` · 17 pages | `[230,300]` | System Map, Lessons, Onboarding Learn Mode, Prospect Simulation, Search, Detail Panels — all read from `frontend/src/gtm/canonical.ts:76` (single source of truth) + `frontend/src/gtm/simulation.ts:46` |
| **Backend Core API** | `FastAPI Gateway :8100` · 19 routers (`backend/app/main.py`) | `[430,300]` | JWT auth + workspace scoping, `POST /api/pipeline/{id}/context/{stage}` + `apply/{stage}`, `GET /outreach/messages/{id}/send-decision`, `/events/pending`, Twilio webhooks. Hard gates enforced here. |
| **Postgres** | `49 tables · 9 migrations` | `[680,300]` | `companies`, `leads`, `hiring_signals`, `job_postings`, `contacts`, `messages`, `outbound_messages`, `research_reports`, `scores`, `qa_runs`, `message_stage_events`, `activities`, `suppression`, `mailboxes`, `sending_domains`, `campaigns`, `job_queue`, `outbox`, `intent_events`, `intent_events` etc. |
| **n8n** | `8 workflows · SMTP` | `[920,470]` | Polls `queue → n8n` (`via [[505,570],[995,570]]`), applies results via API, transports SMTP, runs LLM calls (strong/cheap tiers). Workflows include `reply-classification.json`. |
| **AI agents** | Providers layer (`registry`) | `[1090,315]` | LLM (strong/cheap), enrichment (Apollo/Hunter/Clearbit), verification (ZeroBounce/HunterVerify), scraping (Scrapling/Scrape provider), circuit breaker + retry + fixture fallback (`backend/app/providers/base.py`). |
| **Twilio** | Via providers | — | Voice (click-to-call, `backend/app/services/twilio_service.py:74`), Access Tokens (WebRTC), status webhooks (idempotent by `CallSid`). |

> Also: **Pipeline Engine** (`pipeline.py`), **Enrichment+Research**, **Scoring & Signals**, **Outbound+Health**, **Control Plane** (audit · flags · digest), **Auth & Workspaces** (JWT+onboarding).

---

# WHAT HAPPENS?

> 🟡 Request path (follow `orbit-gtm-os.html: Connections`):

1. **User → Frontend** (`HTTPS`, emphasized edge)
2. **Frontend → API** (`/api/* (JWT)`) → `Auth & Workspaces` validates, then `SQL` to `PostgreSQL`
3. **API → Queue** (`enqueue`, dashed) — `job_queue.enqueue()` + `events.emit()` on `orbit_events` (`backend/app/services/events.py`, `job_queue.py`)
4. **Queue → n8n** (`poll + NOTIFY`, dashed) — n8n `GET /events/pending` / `LISTEN orbit_events`, claims with `FOR UPDATE SKIP LOCKED` (`backend/app/services/intent_engine.py:121`)
5. **n8n → API** (`apply results`) — `POST /api/pipeline/{id}/apply/{stage}` → pipeline validates (`pipeline.py:240-413`) → emits next event → new queue row
6. **Pipeline ↔ Enrichment/Scoring** — `pipeline → enrichment (waterfall)`, `pipeline → db (transitions)`, `scoring → db (scores)`
7. **Outbound → n8n** (`claim → SMTP`, emphasized) — `email_service.claim_for_send()` (`email_service.py:125`) → n8n transports → `apply_send_result()` (`email_service.py:201`)
8. **Control Plane → Outbound** (`pause/resume`, security) — flags `kill_switches`, `shadow_mode`, `approval_mode` read by `scheduler.py:35` + `outbound_gate.py`

n8n also fans out to **Providers** (`LLM · email · enrich`, dashed).

---

# WHAT DECISIONS ARE MADE?

> 🟡 Architecture-level decisions (visible in balance card `Backend owns state, n8n owns I/O`):

- **What to enqueue vs. what to compute inline?** Inline: validation, arithmetic, FSM transitions, QA. Enqueued: LLM, scraping, SMTP, enrichment provider calls.
- **Where is sendability decided?** Always in code (`outbound_gate.can_send` + `claim_for_send` checks `email_verified + suppression + qa_runs + stage_authorized`), never in UI.
- **What pauses?** `scheduler._get_kill_switches()` (`scheduler.py:35`) + `outbound_gate` reason propagation; domain/mailbox/campaign/global granularity.
- **What tier is this message?** `opportunity.py:305` (`A+` 90+ → `call_email_linkedin`, etc.) informs scheduler `_needs_approval()` (`scheduler.py:80` — hybrid mode requires approval for `A/A+`).

---

# WHAT COMES OUT?

> 🟡 Durably:

- **State rows** — `leads.status`, `messages.gtm_stage`, `message_stage_events` (every stage hop with `actor, reason, qa_run_id` — `gtm_lifecycle.py:93`)
- **Audit rows** — `activities` (every agent/system action, actor-labeled), `audit_log`, `qa_runs` (deterministic findings), `email_verifications`, `provider_usage`
- **Observability** — `pipeline.py` + `gtm_lifecycle.stage_history()` (`gtm_lifecycle.py:111`) → frontend Detail Panels cite exact evidence + stage history, never guessed reasoning.

---

# REAL-WORLD EXAMPLE — ABC HVAC through the layers

> 🟢 ABC HVAC (Greensboro, 3 areas, dispatcher hiring, weak booking) — same running example:

| Layer | ABC HVAC touch |
|-------|----------------|
| **Frontend** | Operator searches "ABC HVAC" → System Map highlights `FIND` candidate; detail panel shows `canonical.ts:108` realExample + trace `app/providers/job_sources.py` (maps). Simulation page replays `ABC_HVAC_SIMULATION` step 1. |
| **API** | `POST /api/leads` creates `companies` + `leads status=new`; `request_qualification()` (`pipeline.py:506`) emits `lead.qualification_requested`. |
| **Postgres** | Rows: `hiring_signals` (dispatcher, `signal_score 78`, `freshness 0.9`), `companies.tech_signals` (no chatbot), `leads.website_findings`, `research_reports` (dispatcher pain), `scores` (priority 78), `messages` (draft), `qa_runs` (QA_PASSED), `message_stage_events` (all 9 hops to SENT). |
| **n8n** | Workflow `hiring-intake` calls `job_sources.py` → `website-intel` scrapes Scrapling → `research` calls LLM strong tier → `copy` drafts via Hermes prompts (`pipeline.py:146`) → `send-email` claims & transports. |
| **AI agents** | `hiring_signals.classify_role()` LLM cheap→keyword fallback (`hiring_signals.py:87`), `research._call_llm_research` strong tier (`research.py:181`), `enrichment.enrich_company_waterfall` Apollo→Hunter→Clearbit (`enrichment.py:144`) |
| **Twilio** | Operator clicks-to-call Maria Chen → `twilio_service.place_call()` (`twilio_service.py:74`) checks DNC + timezone guard (8am-9pm), dials via `api.twilio.com`, posts `StatusCallback` → `process_status_webhook()` updates `calls` idempotently by `CallSid`. |

---

# WHAT CAN GO WRONG?

> 🟡 As noted in cards `Multi-layer enforcement` + `Resilience by default`:

- `provider_available` always `True` (`outbound_gate.py:197`) — real SMTP failure only caught at `apply_send_result(ok=false)` → `record_failure()` retries 3× then `failed`.
- `hiring_signals` + `job_postings` dual tables — `refresh_scores()` (`hiring_signals.py:468`) can't fully recompute without stored `intent_signals` (partial refresh).
- `research._fallback_research()` (`research.py:207`) generates generic "High inbound call volume…" — violates fail-closed if LLM down; flagged as known architectural contradiction (`canonical.ts:186`).
- Tenant leak: `GET /events/pending` (`intent_engine.py:117`) and `intent_engine.ingest_event` not workspace-scoped in all paths — conftest found it.

> 🔴 Recovery: see `orbit/docs/RECOVERY.md` + `RUNBOOK.md`. Kill switches (`control → outbound`) are security edges that pause globally without deploys.

---

# EDGE CASES

> 🟡

- **Legacy managed rows** (`messages.gtm_stage IS NULL`) skip only QA/compliance/stage checks so pre-existing flows unchanged (`outbound_gate.py:137`). Managed rows must start at a valid `STAGES` entry (`gtm_lifecycle.py:12`). Initial enrollment allowed from `NULL` → any `STAGES` (`gtm_lifecycle.py:53`).
- **Idempotency** — `messages.idempotency_key`, `job_queue.idempotency_key`, `hiring_signals (workspace,source,source_job_id)` conflict target — all `ON CONFLICT` guarded.
- **Concurrent stage hop** — `transition_message()` (`gtm_lifecycle.py:58`) optimistic `UPDATE … WHERE gtm_stage IS NOT DISTINCT FROM %s` + `RETURNING` — if race, caller gets `InvalidTransition: concurrent stage change`.
- **No website** — `fetch_website_intel()` (`website_intel.py:234`) writes empty `WEBSITE_FINDINGS_SCHEMA` and still writes `leads.website_findings` (low-info flag for downstream).
- **n8n down** — `job_queue` + `outbox LISTEN` retain jobs; `pipeline.apply_*` is idempotent via `stage_context` required keys; replay safe.

---

# WHAT HAPPENS NEXT?

> 🟢 Systems view done → zoom into the two brains that power it:

- Next: `02-gtm-leads/` — business understanding, ICP, enrichment, research
- Then: `03-gtm-intent/` — signals, timing, priority, fact→opportunity chain
- After brains: `04-discovery` → `11-learning` — each stage as IETM module (all cite this architecture view for where they sit)

> Use the **guided views** in `orbit-gtm-os.html` (toolbar) to isolate `intelligence` vs `outbound` before diving into stage docs.

---

# WHY DOES IT MATTER?

> 🟢 Architecture determines whether autonomy is safe. This architecture makes three promises auditable:
> 1. **No hallucinated sends** — every `body_text` claim must cite `evidence_refs`, checked by `qa_service.run_copy_qa` (`qa_service.py:177`).
> 2. **No suppressed sends** — `suppression.check()` (`outbound_gate.py:120` + `email_service.py:175` + `twilio_service.py:97`) runs in code on every claim.
> 3. **No lost replies** — `kill_switch()` (`email_service.py:376`) pauses ALL automation for lead on any inbound, idempotently.

Without these boundaries, "AI GTM" is spam with better copy. With them, it's `observe → reason → decide → act when appropriate → stop when appropriate → escalate when appropriate`.

---

# DEEPER DETAIL (technical)

> 🔴 **BUILDER — read only if wiring code**

**Canonical files (ground truth, never invent):**

| File | Lines | What to read first |
|------|-------|--------------------|
| `backend/app/main.py` | 19 routers mounting | API surface |
| `backend/app/db.py` | pool + connection helpers | durability |
| `backend/app/services/pipeline.py` | `stage_context:165`, `apply_qualification:240`, `apply_enrichment:279`, `apply_audit:325`, `apply_offer:351`, `apply_draft:384` | spec §10.3 boundary |
| `backend/app/services/state_machine.py` | `TRANSITIONS:6`, `can_transition:36` | lead FSM |
| `backend/app/services/gtm_lifecycle.py` | `STAGES:12`, `AUTHORIZED_SEND_STAGES:20`, `transition_message:59` | message lifecycle |
| `backend/app/services/scoring.py` | `icp_fit_score:39`, `priority_score:71`, `hiring_intent_score:113`, `OFFER_CATALOG:24` | pure arithmetic |
| `backend/app/services/intent_engine.py` | `reevaluate_lead:181`, `ingest_event:58`, `process_pending_events:117` | recency decay + tier |
| `backend/app/services/outbound_gate.py` | `can_send:96` (13 checks) | judgment before send |
| `backend/app/services/email_service.py` | `claim_for_send:125`, `schedule_followups:289`, `kill_switch:376` | send + react |
| `backend/app/services/scheduler.py` | `tick:397`, `get_daily_capacity:104`, `assign_mailboxes:281` | adaptive pacing |
| `backend/app/services/qa_service.py` | `run_copy_qa:177`, `run_compliance_qa:250` | deterministic critics |
| `backend/app/services/enrichment.py` | `enrich_company_waterfall:144`, `find_decision_maker_email:194`, `verify_email_waterfall:318` | waterfall + provider priority |
| `backend/app/services/website_intel.py` | `fetch_website_intel:222` | scrape + detection |
| `backend/app/services/hiring_signals.py` | `upsert_hiring_signal:315`, `compute_signal_score:188` | normalize → upsert |
| `backend/app/services/research.py` | `research_company:330`, `_validate_research_report:258` | evidence citations |
| `backend/app/services/opportunity.py` | `compute_opportunity_score:238`, `compute_emv:379` | composite + EMV |
| `backend/app/services/twilio_service.py` | `place_call:74`, `process_status_webhook:145` | voice + DNC guard |
| `backend/app/providers/` | `base.py`, `registry`, `job_sources.py`, `email_finder.py`, `email_verification.py` | circuit breaker + retry |
| `orbit-gtm-os.architecture.json` | 13 components + 3 views + boundaries | view definitions |
| `frontend/src/gtm/canonical.ts` | `GTM_STAGES:76`, `GtmStage:24` | stage definitions as data |
| `frontend/src/gtm/simulation.ts` | `ABC_HVAC_PROFILE:30`, `ABC_HVAC_SIMULATION:46` | onboarding synthetic prospect |

**Connections (from `orbit-gtm-os.architecture.json:connections`):**

```
users → frontend          (HTTPS, emphasized)
frontend → api            (/api/* JWT)
api → auth                (validate)
api → db                  (SQL)
api → queue               (enqueue, dashed)
queue → n8n               (poll+NOTIFY, dashed, via [505,570]→[995,570])
n8n → api                 (apply results, via [995,600]→[400,600]→[400,330])
pipeline → enrichment     (waterfall)
pipeline → db             (transitions)
scoring → db              (scores)
outbound → n8n            (claim → SMTP, emphasized)
n8n → providers           (LLM · email · enrich, dashed)
control → outbound        (pause/resume, security)
```

**Boundaries:**

- `orbit/backend + frontend + n8n (single VM)` — region wrapping 10 components (`boundaries[0]`).
- `workspace isolation · suppression · QA` — security group wrapping `api, auth, pipeline, outbound, db` (`boundaries[1]`). RLS / workspace_id guards live here.

**Status:**

- ✅ **IMPLEMENTED** — all 13 components, queue outbox, dual FSMs, 13-check gate, scheduler health multiplier, kill switches, Twilio idempotency, deterministic QA.
- 🚧 **PLANNED** — none at layer level; per-stage PLANNED items are flagged in their own docs (e.g., no per-inbox daily cold-cap enforcement in send path despite spec §7.4 — noted in `canonical.ts:575`).

**Progressive disclosure contract:** This doc is the map, not the tour. Stage docs reuse this map, citing their component row here.

---
*View file locally: `open orbit-gtm-os.html`. Embed: `orbit-gtm-os.html?embed=1&theme=light`. Do not rename components without updating `orbit-gtm-os.architecture.json`.*
