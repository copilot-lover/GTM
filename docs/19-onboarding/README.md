# ONBOARDING — Teach the Explorer (Learn Mode + Simulation)

> **IETM teaching doc · Progressive disclosure: 🟢 Everyone → 🟡 Operator → 🔴 Builder**
> Explorer: `frontend/src/gtm/canonical.ts:GTM_STAGES` (the 12-panel System Map + Lessons explorer) · Simulation: `frontend/src/gtm/simulation.ts:1` (the only synthetic prospect — ABC HVAC) · Architecture learn layers: `orbit-gtm-os.html` guided views
> **This is the "how to use the docs you're reading" doc — the meta-layer that makes the other 11 IETM docs exercisable rather than just readable.**

---

# WHAT IS IT?

> 🟢 **BASIC**

Onboarding is **the Learn Mode explorer** that turns the 12-stage GTM spec into a **teachable, explorable, simulation-driven interface** — not a PDF you scroll, but a map you click.

It has two halves:

| Half | What you get | Where it lives |
|------|-------------|---------------|
| **The Explorer** | A 12-panel System Map (`find → learn`) + `WHY` panel + Detail panel (`WHAT IS IT? → DEEPER DETAIL`) that **all read from one file** so docs never drift | `frontend/src/gtm/canonical.ts:76` (`GTM_STAGES[]` with `whatItIs, whyExists, whatEnters, whatHappens, decisions, whatComesOut, realExample, whatCanGoWrong, edgeCases, howItConnects, whyItMatters, advanced, trace`) |
| **The Simulation** | A **single synthetic prospect — ABC HVAC** — walking **end-to-end** through all 12 stages without real data, showing exactly what Orbit knows, what it doesn't, what it decides, and why | `frontend/src/gtm/simulation.ts:11` (`SimulationStep` + `ABC_HVAC_PROFILE:30` + `ABC_HVAC_SIMULATION:46` 12 steps + `SIMULATION_VARIANTS:239` 6 reply branches) |

> 🟡 The word "onboarding" is literal: this doc onboards **you**, not a prospect — by letting you rehearse the whole `FIND→BOOK→LEARN` loop before writing a line of production code or running `FIND`.

---

# WHY DOES IT EXIST?

> 🟢 Three reasons the map + simulation exist:

1. **Prevents documentation drift.** Without a single source, System Map copy, Lessons, Onboarding, Search, and Detail Panels gradually diverge — operators read one truth, builders another. `canonical.ts:1` powers all 5 consumers from **one array**, so renaming `identify → contact-discovery` is a one-edit change.
2. **Makes the system exercisable without risk.** `simulation.ts:1` (`ABC HVAC`) lets you practice `P1 (78) vs P3`, `verified vs syntax_ok`, `QUESTION vs PRICE` escalation, and kill-switch timing **without touching real companies, real mailboxes, or real billing** — the dispatcher's phone is `+13365551234 (normalized E.164)` (`simulation.ts:39`), not a live dial.
3. **Teaches the mental model, not just the UI.** The IETM structure (each stage: `WHAT IS IT? … DEEPER DETAIL`) is embedded in every `GTM_STAGES[]` entry — the same 12 headings this doc follows — so the explorer is **the IETM you're reading, rendered**.

---

# WHAT GOES IN?

> 🟡 What the explorer + simulation consume:

**Explorer inputs (`frontend/src/gtm/canonical.ts:24`):**

- `GtmStage` fields: `id GtmStageId 12-union + index 1-12, title, short, icon, color/accent, whatItIs, whyExists, whatEnters[], whatHappens, decisions[], whatComesOut[], realExample {title, body}, edgeCases[], whatCanGoWrong[], howItConnects{from, to, detail}, whyItMatters, advanced, trace{backendModules[], stateMachine, agent, tables[]}`
- `GtmBrain[]` (`GTM_LEADS + GTM_INTENT` — `canonical.ts:55`)
- `GtmPrinciple[]` (7 principles — qualitative navigation, not code)

**Simulation inputs (`frontend/src/gtm/simulation.ts:11`):**

```
ABC_HVAC_PROFILE = {
  name: ABC HVAC, tagline: Local HVAC · 3 service areas · Greensboro NC,
  website: abchvac.example.com (weak booking, no chatbot),
  ads: Google Ads active (Greensboro/High Point/Winston-Salem),
  hiring: Dispatcher posting 3 days ago — $18-22/hr — "answer 50+ calls/day, schedule service appointments",
  reviews: 4.6★ 82, 3.2% monthly growth,
  tech: single location, family-owned, owner-visible, 6-10 employees,
  decisionMaker: Maria Chen (Apollo 92% verified ZeroBounce),
  phone: +13365551234 normalized E.164, emailStatus verified, operationalPressure, confidence medium-high,
  score: {fit 8, intent 78, priority 78, tier P1, qualification HIGH-VALUE FIT}
}
SimulationStep = {stage, stageTitle, whatOrbitKnows[], whatOrbitDoesntKnow[],
                  signalFound, howItInterprets, decision, whyDecision,
                  informationPassedForward[], conversation?{prospectSays, intent, orbitReplies, nextAction}}
```

Plus `SIMULATION_VARIANTS:239` (`positive / objection / wrongPerson / later / unsubscribe / angry`) — the 6-reply evaluation harness side-by-side with ABC HVAC.

> 🟢 No real `leads` rows are read to run the simulation — it's **synthetic and deterministic**, runnable in Storybook or as a `frontend/src/gtm/` unit test without `backend` running.

---

# WHAT HAPPENS?

> 🟡 The Learn Mode flow:

1. **Open the System Map** — 12 colored tiles (`find cyan → learn amber`) each reading their `GtmStage` title/short/icon/color/advanced from `canonical.ts:76`. `LEADS` brain + `INTENT` brain shown alongside as separate cards (`frontend/src/gtm/canonical.ts:GtmBrain`).
2. **Click a stage** — detail panel renders `whatItIs → whyExists → whatEnters → whatHappens → decisions → whatComesOut → realExample → whatCanGoWrong → edgeCases → howItConnects → whyItMatters → advanced`, each sourced from `canonical.ts:what*` not from Markdown. `trace` renders as "Where to look in code" (`backendModules, stateMachine, tables`).
3. **Run the simulation** — call `getSimulationStep("find")` (`simulation.ts:280`) → renders its `whatOrbitKnows / whatOrbitDoesntKnow / signalFound / howItInterprets / decision / whyDecision` inline with the detail panel's `realExample`. Advance via `getNextStageId(currentId)` (`simulation.ts:283`) to walk `find → understand → qualify → identify → opportunity → decide → gate → outreach → response → converse → book → learn`.
4. **Branch the conversation** — at `response|converse` steps, flip between `SIMULATION_VARIANTS` (`simulation.ts:239`) cards (`PRICE vs OBJECTION vs WRONG_PERSON …`) — each is one turn that re-teaches the 13-intent taxonomy without needing new fixtures.
5. **Exercise the gates** — operators answer "what would happen if ABC HVAC's email were only `syntax_ok` not `verified`?" — answer visible: `outbound_gate.can_send:130` `email_verified` → `false` → `HOLD`, but simulation step `identify` already says `emailStatus verified` for current path.

> 🔴 The Learn Mode explorer is **not** the production dashboard (17 pages at `frontend` `React+Vite`). It is a **documentation surface** that happens to be built from the same `GTM_STAGES` data — so operator training never diverges from builder reality.

---

# WHAT DECISIONS ARE MADE?

> 🟡 Only one decision belongs to this doc: **are you ready to write or gate production?**

- **If you cannot trace ABC HVAC's 73-word draft to `pipeline.apply_draft:384` + `qa_service.run_copy_qa:177` rules** → re-read `08-outbound/`
- **If you cannot explain `P1 78` as `0.4 intent +0.3 fit +0.2 contact +0.1 history`** → re-read `05-qualification/` + `03-gtm-intent/`
- **If you think `OUTBOUND` is one stage not three** → re-read `08-outbound/`'s `PROBLEM+SERVICE+CONTACT+CONTEXT+SIGNAL=ANGLE` lesson
- **If you would suppress the whole domain for `"Not me, talk to Jamie"`** → re-read `09-conversation/`'s `WRONG_PERSON → re-identify, don't suppress` rule + `simulation.ts:253` variant
- **If you would rewrite qualification thresholds after one booking** → re-read `11-learning/`'s `N≥10, strong≥5` gate (`learning_loop.py:38`)

> The explorer doesn't decide for you — it gives you the **repeated exercise** to pass those self-checks before you touch `FLAGS` or `mailboxes`.

---

# WHAT COMES OUT?

> 🟡 A human who can:

- **Navigate the GTM Map** (12 stages + 2 brains + 7 principles) and click any stage to recite its `WHAT IT IS / WHY EXISTS / WHAT HAPPENS / DECISIONS / WHAT CAN GO WRONG / WHAT HAPPENS NEXT` — because the IETM you explored **is** that stage's doc
- **Replay ABC HVAC cold** (12 steps) — `whatOrbitKnows vs whatOrbitDoesntKnow` separation is the humility lesson (never claim 50 calls/day — cite "posting says 50+" )
- **Run 6 intent branches** — `SIMULATION_VARIANTS` are the evaluation harness for `09-conversation/` without needing a separate test suite
- **Carry the knowledge forward** — every IETM doc forward-refs the explorer as the recall tool ("if you forgot the chain, open Map → click IDENTIFY")

> In repo terms: the outcome is **0 production rows written** (`workspaces, companies, leads` untouched in Learn Mode), but on-disk `frontend/src/gtm/canonical.ts` + `simulation.ts` are the contract that future onboarding commits must not drift.

---

# REAL-WORLD EXAMPLE — ABC HVAC as your first rehearsal

> 🟢 This is the **actual content of your first hour** in Learn Mode — the full 12-step ABC HVAC walk, condensed:

| Stage | What you read on the panel | What you click next in the simulation |
|-------|---------------------------|---------------------------------------|
| **FIND** | `F` in `#0ea5e9` — Maps+JSearch → SHA-256 deduped → `status=new` | See `whatOrbitKnows: ABC HVAC, Greensboro NC, active, hiring dispatcher` vs `whatOrbitDoesntKnow: booking flow quality (needs crawl)` |
| **UNDERSTAND** | `U` — scrape findings aggregated into understanding | See `tech_signals + website_findings` (no chatbot, mobile 62, CTA weak) + `owner_operator_confidence 68` |
| **QUALIFY** | `Q` — `HIGH-VALUE FIT P1 78` breakdown | See `ICP 8/10 + intent 35 + fit 24 + contact 12 + history 5` contributions explain the 78 |
| **IDENTIFY** | `P` — waterfall `Owner rank 1 → Apollo 92% → ZeroBounce verified` | See `contacts Maria Chen verified` + why `info@` discarded |
| **OPPORTUNITY** | `O` — `research_reports` + 6-component `tier A 85, EMV $4.45` | See `primary_problem: scheduling pressure, reason_now: hiring+ads, avoid_assumptions: ServiceTitan unknown` |
| **DECIDE** | `✎` — `73w, 4-sentence Hermes angle` | See `subject 'Hiring a dispatcher in Greensboro?'` + why generic was rejected |
| **GATE** | `G` amber — 13-check audit `allowed=true` | See `all 13 checks pass` list + what single failure would HOLD |
| **OUTREACH** | `↗` — Day 0 10:15 ET via `hello@orbit...` + Day 3 queued + kill switch | See `capacity 28, business hours OK, idempotency key`, then `reply → cancel` timing |
| **RESPONSE** | `?` — `QUESTION (ServiceTitan)` confidence 0.82, kill switch fires | See `intent QUESTION → next CONVERSE`, plus flip through `SIMULATION_VARIANTS` pricing/objection/wrongPerson |
| **CONVERSE** | `?`+ history — `after-hours yes` answer, propose walkthrough | See `conversation:{prospectSays, intent, orbitReplies, nextAction}` |
| **BOOK** | `B` — `Sure, Thu 10am` → `meeting_booked` packet assembled | See `packet: 3 areas, 4.6★, trigger dispatcher+weak booking, scheduling pressure, P1` |
| **LEARN** | `L` — `N=6 HVAC dispatchers 33% vs baseline 12% → suggest weight higher, but N<10? log only` | See `evaluate_learning` thresholds mention `should_change=false` on current N, `informationPassedForward: every outcome → better next TARGET/CONTACT/ANGLE/TIMING` |

> The full verbatim trip is `frontend/src/gtm/simulation.ts:46` — open it side-by-side with the Map and you'll see each panel's `Real-World Example {title, body}` is that `SimulationStep` exactly.

---

# WHAT CAN GO WRONG?

> 🟡

- **Treating the explorer as production** — Learn Mode renders from `canonical.ts`, not from `PostgreSQL` `leads` rows; a beautifully working Map doesn't mean `n8n` workflows are alive — check `job_queue` directly for real
- **Drift between simulation and code** — `simulation.ts` is a **fixture**, not a live readout; when `scoring.py:OFFER_CATALOG` adds a 9th offer, simulation's `ABC_HVAC_PROFILE` must be updated to reference it (otherwise the Map says one thing, simulation says stale)
- **Forgetting the synthetic phone is fake** — `+13365551234` is deterministic `E.164` in `simulation.ts:39`; if an operator pastes it into `twilio_service.place_call` in staging with `TWILIO_CALLER_ID` configured, it would actually attempt a dial — **simulation phones must never reach `place_call`**
- **N≈12 but treated as learn-ready** — `learning_loop.CONSERVATIVE_THRESHOLDS 10/5` are deliberately high; operators eager to "let ML learn faster" may bypass them by editing `frontend/src/gtm/simulation.ts` counts without real book evidence

---

# EDGE CASES

> 🟡

- **Batch of 0 leads** — Map renders fine; simulation still replays ABC HVAC as teaching aid even when `GET /api/leads?workspace=` returns `[]`
- **No website for ABC HVAC variant** — simulation marks `whatOrbitDoesntKnow: current booking software (ServiceTitan? Housecall?)` — the Map's `IDENTIFY` edge case "no website → low-info" is exercised here
- **Multi-location variant of ABC HVAC** — simulation mentions `multi-location → different scaling implications` but real `ABC HVAC` is single-brand; use the Map's `UNDERSTAND` edge-case note to explore that fork without a second fixture
- **Reply during simulation wait** — the simulation `outreach` step notes `reply during follow-up wait → check_followup_cancellation polling minutes gap` — touching it teaches the dual-queue timing gap even though `simulation` is static JSON
- **Theme / embed mode** — `orbit-gtm-os.html?embed=1&theme=light` renders the architecture map inside docs; `present=1` gives presentation stage; `theme` auto-detects via `localStorage.archify-theme` + `prefers-color-scheme`; dark-flash prevented by pre-paint `<script>` — all viewer-only, none stored as artifact truth

---

# WHAT HAPPENS NEXT?

> 🟢 After onboarding you **start building or operating**, but never without the explorer in the background:

- **Builder path** → pick a stage doc (`04-discovery` … `11-learning`), read `WHAT HAPPENS?` code-anchored table there, implement the next planned migration, then **re-run the simulation walk** to confirm the Map still matches the new code
- **Operator path** → run `FIND` on a real workspace, watch the first 3 new leads flow through `UNDERSTAND→QUALIFY` in real time, and keep the Map + simulation overlay pinned to interpret each `hiring signal freshness` transition as it decays
- **Reviewer path** → use `simulation.variants` as your test harness checklist: does `RESPONSE` `WRONG_PERSON` really re-identify and not suppress on staging? — assert it

> The good explorer answer to "am I done onboarding?" is: **you can click any of the 12 tiles cold and state its trace (`backendModules, stateMachine, tables`) + ABC HVAC's decision there without looking.**

---

# WHY DOES IT MATTER?

> 🟢 The explorer is how the OS **remains learnable as it grows**. A system with 12 stages, 2 brains, 7 principles, 49 tables, and 8 n8n workflows is too large to hold in working memory — but any one tile is one spec paragraph. Learn Mode is **progressive disclosure as a UI** — `🟢→🟡→🔴` via click depth, not scroll length — and the simulation is the **recurring character** (ABC HVAC) that makes abstract gate rules stick as a story.

---

# DEEPER DETAIL (technical)

> 🔴 **BUILDER**

**Modules & contracts:**

| File | Lines | Purpose |
|------|-------|---------|
| `frontend/src/gtm/canonical.ts:1` | header comment | Powers: SYSTEM MAP, LESSONS, ONBOARDING (Learn Mode), PROSPECT SIMULATION, SEARCH, DETAIL PANELS |
| `frontend/src/gtm/canonical.ts:10` | `GtmStageId 12-union` | `find\|understand\|qualify\|identify\|opportunity\|decide\|gate\|outreach\|response\|converse\|book\|learn` |
| `frontend/src/gtm/canonical.ts:24` | `GtmStage` | 16 fields incl. `whatItIs, whyExists, whatEnters[], whatHappens, decisions[], whatComesOut[], realExample, edgeCases[], whatCanGoWrong[], howItConnects, whyItMatters, advanced, trace` |
| `frontend/src/gtm/canonical.ts:55` | `GtmBrain` | `leads\|intent, whatItDoes, whatItDoesNot, output, example, trace[]` |
| `frontend/src/gtm/canonical.ts:69` | `GtmPrinciple` | `n 1-7, title, detail` |
| `frontend/src/gtm/canonical.ts:76` | `GTM_STAGES:12` | stage 1 `find:F` through 12 `learn:L` — note `find`→`enriching` state-idx mapping via `trace.stateMachine` |
| `frontend/src/gtm/simulation.ts:11` | `SimulationStep` | 8 fields + `conversation?` extras |
| `frontend/src/gtm/simulation.ts:30` | `ABC_HVAC_PROFILE` | 14 fields: 3 areas + dispatcher + ads + reviews + etc |
| `frontend/src/gtm/simulation.ts:46` | `ABC_HVAC_SIMULATION 12` | end-to-end (know/dontKnow, signal, interpret, decision, forward + conversations) |
| `frontend/src/gtm/simulation.ts:239` | `SIMULATION_VARIANTS 6` | `positive/objection/wrongPerson/later/unsubscribe/angry` |
| `frontend/src/gtm/simulation.ts:280` | `getSimulationStep, getNextStageId` | helpers powering Learn Mode navigation |

**Implementation guard:**

- Every `GTM_STAGES[]` entry's `trace.backendModules[]` **must** point at real paths under `backend/app/services/` — unknown paths are a hard review finding (`RECOVERY.md` rule).
- `advanced` text (e.g., `"Providers: app/providers/job_sources.py … dedupe: pipeline.py SHA-256 … state: leads.status=new … worker: discovery:1 pool; resilience: CircuitBreaker(5,60s)…"` — `canonical.ts:133`) must stay accurate after any provider or FSM edit.
- `simulation.ts` is typed `SimulationStep[]` not `any` — CI fails if a step drops `informationPassedForward` or `whyDecision` (the IETM guarantee).

**Tables (Learn Mode reads none; the teaching reads like they do):**

- Simulation fixture rows are synthetic; production `companies, leads, hiring_signals, research_reports, scores, contacts, enrichments, activities, message_stage_events` are **not queried** by the simulation — they are what learners will eventually see after running real `FIND`.

**Status:**
- ✅ IMPLEMENTED — canonical 12 stages + 2 brains + 7 principles as data; simulation 12 steps + 6 variants as typed, deterministically runnable fixtures; helpers `getSimulationStep` + `getNextStageId`; no drift between Map/Lessons/Onboarding/Simulation/Search
- 🚧 PLANNED — `frontend` wired Learn Mode view for this doc's explorer (Map render + detail panel + simulation timeline UI exists as `gtm-flow.html` prototype — canonical fidelity flagged); `gtm-flow.visual-check.json` + `gtm-flow.workflow.json` (preset validation) — not yet merged as production nav

**Progressive disclosure contract:** This doc marks everything prior as `🟢→🟡` and marks itself as the `🔴-adjacent` integration point where builders verify the contract "every changed line in a stage doc must trace to a `file:line`" — via `canonical.ts.trace` per stage.

---
*Trace: `frontend/src/gtm/canonical.ts`, `frontend/src/gtm/simulation.ts` — `orbit-gtm-os.html` viewpoints overlay the Map; `orbit/docs/00-overview/` orients the loop that this doc makes runnable.*
