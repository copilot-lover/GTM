# STAGE 06-08 — OUTBOUND: DECIDE + GATE + OUTREACH (3-in-1)

> **IETM teaching doc · Stages 6,7,8 of 12 · Progressive disclosure: 🟢 Everyone → 🟡 Operator → 🔴 Builder**
> Canonical: `frontend/src/gtm/canonical.ts:401` (decide, index 6), `462` (gate, index 7), `528` (outreach, index 8) · Simulation: `frontend/src/gtm/simulation.ts:130-165` · Pipeline: `backend/app/services/pipeline.py:351,384` · Gate: `backend/app/services/outbound_gate.py:96` · Send: `backend/app/services/email_service.py:125` · Scheduler: `backend/app/services/scheduler.py:397`
> **This doc covers 3 canonical stages as one operational unit — they have no useful human meaning separately.** Selling it as three docs would imply three handoffs; there is one decision-to-send path.

---

# WHAT IS IT?

> 🟢 **BASIC**

**OUTBOUND is DECIDE + GATE + OUTREACH acting as one machine:**

- **DECIDE** — selects the **relevant problem, plausible outcome, and evidence-backed angle**; drafts a message that **cites evidence** (`pipeline.apply_draft:384`, `gtm_lifecycle DISCOVERED→…→COPY_GENERATED→QA_PENDING`).
- **GATE** — renders **judgment before send** — deterministic, auditable compliance + quality gate (`outbound_gate.can_send:96` — 13 structural checks; `qa_service.run_copy_qa:177` + `run_compliance_qa:250` critics).
- **OUTREACH** — runs a **controlled cadence that reacts to behavior** (timing, mailbox assignment, kill-switch on reply) (`email_service.schedule_followups:289`, `scheduler.tick:397`, `sequences.py`).

> Together: **DECIDE proposes → GATE judges → OUTREACH delivers-and-listens.** All three reading the same `OPPORTUNITY` decision packet as their source of truth.

**Message strategy formula (how DECIDE picks angle):**

```
PROBLEM + SERVICE + CONTACT + CONTEXT + SIGNAL = ANGLE

PROBLEM    = primary_pain from research (e.g., scheduling pressure)
SERVICE    = OFFER_CATALOG pick mapped to pain (e.g., ai_receptionist)
CONTACT     = verified decision maker who cares about that problem (Owner Maria)
CONTEXT    = website/understand findings that prove it (no chatbot, weak CTA)
SIGNAL    = timely trigger that makes it NOW (dispatcher hiring fresh 3d + ads)
          = one CSI-ranked angle (Context + Signal → Interpretation)
```

> 🟡 Operators learn one formula, not three stage definitions. That keeps the personalization lesson portable.

---

# WHY DOES IT EXIST?

> 🟢 Three reasons, one for each substage:

- **DECIDE exists because personalization isn't mail-merge.** The strongest message is about **the prospect's current situation**, not Orbit's capabilities. Without DECIDE, you send `GENERIC_COPY` ("Learn about our AI services?") — `qa_service.run_copy_qa:213` will fail it, correctly.
- **GATE exists so autonomy doesn't become spam.** *Autonomous does not mean send everything.* Every send must have a legitimate reason or it doesn't send (`outbound_gate.py:1` header). Fail-closed protects domain health, compliance, prospect respect.
- **OUTREACH exists because a blast isn't outbound.** Respect + deliverability require a **cadence that changes based on prospect behavior** — reply → cancel follow-ups, unsubscribe → suppression, bounce → pause mailbox, OOO → delay (`email_service.kill_switch:376` + `sequences.check_followup_cancellation` via `scheduler.py:423`).

> 🔴 GATE is the only path to `SEND_READY`; it cannot be bypassed because `claim_for_send` calls `can_send` **first** (`email_service.py:160`) and `outbound_gate` is enforced in **code**, not UI.

---

# WHAT GOES IN?

> 🟡 Unified input — the **opportunity profile** plus contact + operational controls:

| Input | Origin | Consumed by |
|-------|--------|-------------|
| `research_reports` (primary_problem, reason_now, evidence[], recommended_offer) + `scores.tier` + `primary_pain, secondary_pain` | `research.py` / `opportunity.py` | DECIDE (angle), GATE (credibility), OUTREACH (first-send context) |
| Verified `contacts.email` (`verification_status=='verified'`) + `suppression` clearance + mailbox `health_state`, `sending_domains.status`, `campaigns.status` | `enrichment.verify_email_waterfall:318`, `suppression.check` | GATE (7 of 13 checks), OUTREACH (capacity / assign) |
| Decision maker identity (`contacts.is_decision_maker + rank`) + `leads.contact_id` link | `enrichment.find_decision_maker_email:194` via `pipeline.apply_enrichment:288` | DECIDE (who the draft addresses) |
| Sequence config `initial + followups day 0/3/7/14 (+28)` + `cadence_config.offsets_days` if campaign-level (`campaigns.cadence_config`), `angle rotation` | `sequences.py` + `email_service.schedule_followups:289` (`cadence [0,3,7,14]`) | OUTREACH (pacing) |
| Mailbox assignment `originating_mailbox_id` + business-hours guard + `daily_send_limit` + `health_state` | `mailboxes`, `sending_domains`, `scheduler.get_daily_capacity:104` | OUTREACH (health-multiplied capacity, `next_available_slot:207` jitter) |

> DECIDE also reads `leads.website_findings.pain_points` to choose among 8 offers (`scoring.OFFER_CATALOG:24` + `pipeline.PAIN_TO_OFFER:125`): `ai_receptionist, missed_call_recovery, after_hours_booking, lead_qualification, website_conversion, follow_up_automation, review_generation, appointment_scheduling`.

---

# WHAT HAPPENS?

> 🟡 Three phases in one claim-to-send lifecycle:

**Phase A — DECIDE (draft, still unsent):**
1. Operator or trigger invokes `pipeline.stage_context("offer"):198` → n8n gets `OFFER_SYSTEM:138` (choose exactly one `offer_id` from catalog, pain→offer hints `pipeline.PAIN_TO_OFFER:125`); returns `{offer_id, why, expected_outcome}`; `apply_offer:351` checks `offer_id ∈ OFFER_CATALOG` and hard rule #4 `expected = PAIN_TO_OFFER[primary_pain]` must equal `offer` else `PipelineError("offer-pain mismatch")` + review flag; writes `leads.recommended_offer`; emits `lead.draft_requested`.
2. Next, `pipeline.stage_context("draft"):208` → `PERSONALIZE_SYSTEM:146` (Hermes structure, **exactly 4 sentences**: Fact / Inference / Offer / Question, **<75 words**, plain language, no invented facts, reference only provided evidence); returns `{subject, first_sentence, body, cta, followup_angle}`; `apply_draft:384` validates deterministically: `word_count >=75`? `banned_phrases` in `BANNED_PHRASES:377` present? `4-sentence structure` via `re.split(r"[.!?]+")` (`pipeline.py:401`) — any violation → `_flag_review` + `PipelineError`; otherwise `create_draft_message:416` inserts `messages(workspace_id, lead_id, subject, body_text, status='pending_approval') RETURNING id` then `gtm_lifecycle.transition_message("QA_PENDING", actor=GTM_COPY)` (`pipeline.py:432`).
3. Immediately `qa_service.run_copy_qa:177` reviews the draft for `MISSING_EVIDENCE, UNSUPPORTED_FACT, WRONG_SIGNAL, GENERIC_COPY, EXCESSIVE_CLAIM` — writes `qa_runs(status passed|failed, failed_rules)` and transitions `QA_PENDING → QA_PASSED|QA_FAILED|HELD` (`qa_service.py:231`). On pass → `run_compliance_qa:250` → `COMPLIANCE_PENDING → SEND_READY|COMPLIANCE_FAILED|SUPPRESSED|HELD` (`qa_service.py:298`).

> Drift risk noted: `apply_draft` word-count + banned + 4-sentence checks duplicated verbatim in `qa_service.run_copy_qa` (`canonical.ts:441`).

**Phase B — GATE (judge, still unsent until SEND_READY):**
- `outbound_gate.can_send(workspace_id,message_id):96` loads `messages ⊕ leads ⊕ contacts ⊕ companies ⊕ campaigns ⊕ mailboxes ⊕ sending_domains`, runs **13 structural checks** (`canonical.ts:481`, each via `_add:17` with `passed + detail`) — all must pass for `allowed=true`:

| # | Check | `detail` on failure |
|---|-------|---------------------|
| 1 | `lead_eligible` | `lead status in (rejected, do_not_call, archived, lost)` |
| 2 | `contact_eligible` | `contact has no email` / `contact opted out` |
| 3 | `not_suppressed` | `suppression_check blocked (email/phone/company)` |
| 4 | `email_verified` | `email not provider-verified (status=syntax_ok\|dns_ok)` |
| 5 | `copy_qa_passed` | `no copy qa_runs row` / `latest copy qa failed` |
| 6 | `compliance_passed` | same for `compliance` qa |
| 7 | `stage_authorized` | `gtm_stage not in (SEND_READY,SCHEDULED)` — **legacy `NULL` skips this + 5,6 via `legacy=true` path** (`outbound_gate.py:137`) |
| 8 | `mailbox_healthy` | `mailbox health_state=paused` |
| 9 | `domain_healthy` | `sending_domain status != active` |
| 10 | `within_sending_limits` | `sent_today >= daily_send_limit` (date-aware via `sent_today_date==today` else 0, `outbound_gate.py:186`) |
| 11 | `provider_available` | always `True` (stub — `canonical.ts:505`) |
| 12 | `campaign_active` | `campaign status != active` (if campaign_id present, else pass) |
| 13 | `sequence_state_ok` | `lead replied after last outbound` → false for followup step (`outbound_gate._lead_replied_after_last_outbound:80`) |

For `sequence_step >0` adds `followup_mailbox_correct` (must match `original_mailbox`: `outbound_gate._original_mailbox:68`) — prevents split-mailbox thread breaks.

Result: `GET /outreach/messages/{id}/send-decision` returns `{allowed, reasons[], checks[]}` (auditable); `POST /outreach/claim/{id}` (`email_service.claim_for_send`) re-checks gate inside `idempotency + UPDATE status='sending'` (`email_service.py:141`) and releases claim if blocked (`_release_claim:230`).

> 🟡 `APPROVALS` queue: dashboard + Telegram cards `approve/edit/reject/push-to-phone` (`email_service.approve:71` — guard `status in (pending_approval,drafted)`, `gtm_stage in (QA_PASSED,SEND_READY)`). Only `approved` messages may be claimed.

**Phase C — OUTREACH (send, then listen & react):**
1. Operator approves (`email_service.approve:71` → `status='approved', gtm_stage SEND_READY→SCHEDULED` + event `message.approved`).
2. Scheduler or n8n claims: `email_service.claim_for_send:125` (idempotency replay → cached `provider_message_id` if same key), gates, appends `can_spam_signature:51` (requires `ORBIT_PHYSICAL_ADDRESS` env or blocks), returns transport payload `{to_email, subject, body_text (+signature), from_email, idempotency_key}` to n8n `Send Email` node.
3. Transport outcome: `email_service.apply_send_result:201` (`ok → status='sent', gtm_stage SCHEDULED→SENT, activities 'email sent via n8n transport'` via `gtm_lifecycle:221`; `!ok → record_failure:239` `send_attempts+1` with retry, `failed` after 3).
4. Scheduler cadence: `scheduler.tick:397` (`capacity = get_daily_capacity():104 health-multiplied, eligible = get_eligible_messages():164 FROM outbound_messages WHERE queued|scheduled + eligible_at<=now + shadow=false, allocation = campaign_allocation_filter:241 (40/30/30 splits, min_new 50), assign = assign_mailboxes:281 (lowest sent/effective ratio wins, deduplicated)`), `next_available_slot:207` (business hours `window_start 08:30–window_end 16:30` (`scheduler.py:210`), `min_gap 5m + jitter 0-45m`, next business day fallthrough, timezone-aware).
5. Follow-ups: `email_service.schedule_followups:289` (`cadence [0,3,7,14]` or campaign `cadence_config.offsets_days:312`, picks `angle rotation ["short follow-up different angle","case-study","breakup"]`, resolves mailbox via `_resolve_original_mailbox:266`, inserts `messages(… status='approved', sequence_step, scheduled_send_at=now+offset, originating_mailbox_id)`, enrolls in lifecycle `SEND_READY` or `HELD` if mailbox unresolved — note this creates **approved** directly without approval-mode check (`canonical.ts:572`).
6. Reactive behavior: `email_service.kill_switch:376` (any inbound on any channel → `leads contacted→responded`, `DELETE session_leads` call queues, `UPDATE messages rejected` where `approved|scheduled|pending_approval`, `INSERT activities KILL SWITCH`); `sequences.check_followup_cancellation` via `scheduler.tick` polls and purges queued followups on reply; `twilio_service` bounce/complaint path degrades `mailbox.health_state` toward `paused`.

> 🔴 Danger window: `email_service.schedule_followups` writes `approved` without honoring `scheduler._needs_approval:80` hybrid `A/A+` branch; and `kill_switch` deletes `session_leads` + marks `messages rejected` but **`outbound_messages queued` rows remain until polling** → stale follow-ups assignable for minutes (`canonical.ts:575`).

---

# WHAT DECISIONS ARE MADE?

> 🟡 Across the 3 phases:

- **DECIDE:** Which `angle` is strongest for this business now given evidence? Is the angle credible? Generic vs contextual — enough situation-specific proof to be relevant? (`frontend/src/gtm/canonical.ts:418`)
- **GATE:** **YES → send-ready** (enough confidence, relevant, appropriate person, credible reason, good timing, all 13 gates pass) vs **NO → HOLD/SUPPRESSED/HELD/EXPIRED/SHADOW** (`canonical.ts:483`); plus shadow-mode decision (logged not sent) and hybrid approval mode (`scheduler._needs_approval:80` only `A/A+`)
- **OUTREACH:** Is it time for next step per `pacing, health, capacity, campaign cap, mailbox limit, business hours`? Has **prospect behavior changed the path**? Which **mailbox/domain** to assign? Follow-up mailbox must match original — `outbound_gate` enforces, so the decision is already made.

---

# WHAT COMES OUT?

> 🟡

- **`messages` stage transitions** — `messages.status` (`pending_approval → approved → sending → sent`, with `sending→approved` release on gate block) + `gtm_stage` (`DISCOVERED … SENT` via `gtm_lifecycle.TRANSITIONS:31`) — each hop rows `message_stage_events(from_stage, to_stage, actor, reason, qa_run_id)` (`gtm_lifecycle.py:93`)
- **Auditable gate decision** — `{allowed, reasons[], checks[13]}` from `outbound_gate.can_send` consumed by both `GET /outreach/messages/{id}/send-decision` and `claim_for_send`, and persisted indirectly via `qa_runs.failed_rules` holds
- **Send artifacts** — `provider_message_id` + `idempotency_key`, `sent_at`, `email_events(pending delivered/open/click/reply/bounce/complaint)` via `email_events` table
- **Activities timeline** — `email_sent (system)` + `audit_log` rows, keyed to `leads` history panel actor-labeled (`pipeline._add_activity:65`)
- **Mailbox health deltas** — `sent_today++`, bounce→`health_state` downgrade `healthy→normal→reduced→restricted→paused` (`scheduler.HEALTH_MULTIPLIER:22`), `pause_on_bounce` via `kill_switch` JSON blob (`scheduler._get_kill_switches:35`)

---

# REAL-WORLD EXAMPLE — ABC HVAC through DECIDE + GATE + OUTREACH

> 🟢 Local HVAC, 3 areas, hiring dispatcher, weak booking — from `frontend/src/gtm/simulation.ts:130-165` (stages decide, gate, outreach):

```
DECIDE picks angle:
  Problem: scheduling pressure (dispatcher posting "50+ calls/day")
  Service: ai_receptionist (pain already validated via opportunity)
  Contact: Owner Maria Chen (ops-relevant rank 1)
  Context: no chatbot, weak CTA, mobile 62
  Signal: hiring fresh 3d + active ads + weak booking → missed-call cost
  → Angle: "booking automation + AI receptionist for missed calls"
  Generic rejected by QA GENERIC_COPY: "Learn about our AI services?" (73w→ would fail)
  Contextual: "Noticed you're hiring a dispatcher while promoting new areas — often
    means more calls & scheduling pressure. Orbit helps service businesses respond, qualify,
    and book automatically — even core dispatcher tasks. Worth a brief intro?"
    (73w, cites posting URL, one CTA, follow-up angle 'missed-call cost' reserved)

GATE judges (13 checks audit from simulation gate):
  lead_eligible pass (qualified), contact_eligible pass (verified not opted_out),
  not_suppressed pass, email_verified pass, copy_qa_passed pending→will be QA_PASSED after QA,
  compliance_passed pending, stage_authorized false until COMPLIANCE→SEND_READY,
  mailbox_healthy pass (3/30 today), domain_healthy pass (active), within_limits 3/30 pass,
  provider_available pass, campaign_active pass, sequence_state_ok pass (step 0),
  followup_mailbox_correct pass (step 0). Currently QA_PENDING → gate would hold until QA/COMPLIANCE pass.
  After QA_PASSED + COMPLIANCE_PENDING→SEND_READY: allowed=true → stage SEND_READY, ready for operator approval.

OUTREACH delivers:
  Operator approves → claim_for_send re-checks gate + idempotency, issues transport payload with CAN-SPAM block
  (name + address + STOP). Day 0 sends 10:15 ET (business hours OK) via hello@orbit-send1.com (organic1:30, lowest ratio).
  Day 3: no reply, capacity 28 remaining, follow-up angle (missed-call cost) queued via same mailbox, scheduled_slot next_available_slot+jitter.
  If reply "not interested" on Day 1 → kill_switch deletes session_leads, marks messages rejected, queued outbound_messages cancelled within minutes via check_followup_cancellation, alerts operator via Telegram + dashboard toast + control-plane kill_switch.
  If bounce → mailbox health downgraded → paused if >2% bounce.
  If OOO auto-reply → reply-classifier tags OOO, records timing, follow up appropriately (don't suppress).

Loop: send → wait → observe → react (deterministic, not blast).
```

> This is the user-visible moment — a broken cadence (spam, ignored reply, wrong mailbox) damages brand permanently. Deterministic timing + human approval + behavior-reactive kill switch are what make outreach safe (`canonical.ts:584`).

---

# WHAT CAN GO WRONG?

> 🟡 (`frontend/src/gtm/canonical.ts:570` + notes above):

- **Dual queues split:** `messages` vs `outbound_messages` separate infra; `scheduler` walks `outbound_messages` while outreach walks `messages` → two dashboards show different reality, `followupsEnrolled` structurally not unified
- **`schedule_followups` creates `approved` directly without approval-mode check** → violates FR-10 (human approval in hybrid/autonomous) (`email_service.schedule_followups:328` `status='approved'` hardcoded)
- **`claim_for_send` UPDATE `status='sending' before gates** — `gate` failure `_release_claim` may race with `due_sends` poll (`email_service.due_sends:252` `status IN (approved)`), double-claim window (`email_service.py:141`)
- **Scheduler `global_limit += domain_limit` inside mailbox loop double counts** (`scheduler.get_daily_capacity:155` `global_limit += domains[dk]["domain_limit"]` inside `for mb` — should be once per domain)
- **No per-inbox daily cold caps enforcement in send path despite spec §7.4** (`mailboxes.daily_send_limit 30 default, not 20` — `canonical.ts:575`)
- **Kill switch deletes `session_leads` + marks `messages rejected` but `outbound_messages queued` rows remain until polling** → follow-ups assignable for minutes after reply (`canonical.ts:575`)
- **`provider_available` always True** — false confidence (`outbound_gate.py:197`)
- **Draft QA vs pipeline QA drift:** 75w >= in both but pipeline warns vs QA critical paths diverge if edited in one place only (`canonical.ts:441`)

---

# EDGE CASES

> 🟡 (`frontend/src/gtm/canonical.ts:503,563`)

- **Reply during follow-up wait** → `check_followup_cancellation` purges `queued outbound_messages` (polling, not instant — **minutes gap**)
- **Bounce/complaint** → mailbox `health_state` downgraded (`healthy→normal 0.9→reduced 0.6→restricted 0.25→paused 0.0`, `scheduler.HEALTH_MULTIPLIER:22`), future sends paused via `kill_switches` JSON blob (concurrent writes race on global flags)
- **Out-of-office auto-reply** → `reply_classifier` tags `OOO`, records timing, follow up appropriately (don't suppress, `email_service.classify_reply:413` `REPLY_CLASSES:359` includes `UNSUBSCRIBE`/`NOT_INTERESTED` but OOO is soft)
- **Mailbox daily caps 20-30 per inbox, per-domain stagger 600, warmup 2-4 weeks required before volume** (FR-28 dormant if not warmed)
- **Follow-up must match original mailbox** (`outbound_gate._original_mailbox:68`) — if bound mailbox unset, check fails → `followup_mailbox_correct false` → followup stays `HELD` (prevent thread break)
- **No-show sequence after booking** → distinct state machine, not outreach (don't reuse `messages` cadence for booking)

---

# WHAT HAPPENS NEXT?

> 🟢 From here the machine **listens**:

- **→ RESPONSE** (`09-conversation/` first half) — `UNDERSTAND RESPONSE (response)` interprets what the reply **means** (intent + escalation), firing `kill_switch:376` as its first act
- Every send produces `email_events` that `RESPONSE` reads; `CONVERSE` then continues the dialogue observing behavior

> Reminder: OUTREACH is the **only stage that touches external SMTP/Twilio** — all prior stages are internal reasoning (`canonical.ts:582`). Its idempotency keys + health guards protect deliverability for all other stages.

---

# WHY DOES IT MATTER?

> 🟢 This is where the customer **feels** Orbit. A broken cadence burns domain reputation and prospect trust permanently. Deterministic timing + human approval (`approval_mode` hybrid flag `scheduler._get_approval_mode:73`) + behavior-reactive kill switch are the **safety rails that make autonomous outbound not be spam**.

---

# DEEPER DETAIL (technical)

> 🔴 **BUILDER**

**Modules & line map:**

| File | Lines | Note |
|------|-------|------|
| `backend/app/services/pipeline.py:146` | `PERSONALIZE_SYSTEM` | Hermes 4-sentence prompt |
| `backend/app/services/pipeline.py:351` | `apply_offer()` | offer-pain hard rule #4 |
| `backend/app/services/pipeline.py:377` | `BANNED_PHRASES (11)` | must-match `qa_service` list |
| `backend/app/services/pipeline.py:384` | `apply_draft()` | 75w + banned + 4-sentence → review or `create_draft_message` |
| `backend/app/services/pipeline.py:416` | `create_draft_message()` | `pending_approval → QA_PENDING` enrollment |
| `backend/app/services/qa_service.py:177` | `run_copy_qa()` | 4 rules + `GENERIC_COPY` + `MISSING_EVIDENCE` → `QA_PASSED/FAILED` |
| `backend/app/services/qa_service.py:250` | `run_compliance_qa()` | consent/suppress/verified gate → `SEND_READY` |
| `backend/app/services/gtm_lifecycle.py:12` | `STAGES, AUTHORIZED_SEND_STAGES, TRANSITIONS:31` | message FSM, `transition_message:59` |
| `backend/app/services/outbound_gate.py:96` | `can_send()` | 13 checks + `legacy` bypass + `_latest_qa:56` divergence note |
| `backend/app/services/email_service.py:51` | `can_spam_signature()` | requires `ORBIT_PHYSICAL_ADDRESS` or `SendBlocked` |
| `backend/app/services/email_service.py:71` | `approve()` | `pending_approval→approved, SEND_READY→SCHEDULED` |
| `backend/app/services/email_service.py:125` | `claim_for_send()` | idempotency + outbound_gate |
| `backend/app/services/email_service.py:201` | `apply_send_result()` | `SENT` vs `FAIL→retry (3) → failed` |
| `backend/app/services/email_service.py:252` | `due_sends()` | `n8n polls` `status='approved' + scheduled_send_at<=now` |
| `backend/app/services/email_service.py:289` | `schedule_followups()` | day 3/7/14 cadence + mailbox inheritance |
| `backend/app/services/email_service.py:376` | `kill_switch()` | contacted→responded, queue purge, messages rejected |
| `backend/app/services/scheduler.py:104` | `get_daily_capacity()` | health-multiplied effective limits |
| `backend/app/services/scheduler.py:241` | `campaign_allocation_filter()` | 40/30/30 splits |
| `backend/app/services/scheduler.py:281` | `assign_mailboxes()` | lowest ratio wins, kill-switch checks |
| `backend/app/services/scheduler.py:207` | `next_available_slot()` | window + jitter + next business day |
| `backend/app/services/sequences.py` | cadence FSM + `on_initial_sent` + `check_followup_cancellation` | react path |
| `backend/n8n/workflows/` | 8 workflows inc. `reply-classification.json` | orchestration caller |

**Send lifecycle `gtm_lifecycle.py:12`: `DISCOVERED → QUALIFIED → INTENT_SCORED → RESEARCHED → COPY_GENERATED → QA_PENDING → (QA_PASSED→COMPLIANCE_PENDING→SEND_READY→SCHEDULED→SENT) | QA_FAILED/COMPLIANCE_FAILED/SUPPRESSED/HELD/EXPIRED/CANCELLED` — only `SEND_READY|SCHEDULED` may be claimed.**

**Status:**
- ✅ IMPLEMENTED — DECIDE draft+QA, GATE 13 checks audit, OUTREACH capacity/health/slot/assign/idempotency/kill-switch all live; safety `dry-run via mock SMTP fixtures, NO real sends without approval`.
- 🚧 PLANNED / KNOWN GAPS (all flagged in `canonical.ts:570-576` above) — not hidden; fix `schedule_followups` approval check, unify dual queues, add cold-cap enforcement, fix global_limit double-count, make `kill_switch` purge `outbound_messages` atomically.

**Progressive disclosure:** This doc is the only 3-stage composite — selling it as three docs implied three handoffs that don't exist. Operators learn `PROBLEM+SERVICE+CONTACT+CONTEXT+SIGNAL=ANGLE` as their portable mental tool.

---
*Trace: `app/services/email_service.py`, `app/services/scheduler.py`, `app/services/sequences.py`, `app/services/mailbox_health.py` — `frontend/src/gtm/canonical.ts:401-598`.*
