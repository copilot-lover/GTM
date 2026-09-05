# STAGE 01 — FIND (Business Discovery)

> **IETM teaching doc · Stage 1 of 12 · Progressive disclosure: 🟢 Everyone → 🟡 Operator → 🔴 Builder**
> Canonical: `frontend/src/gtm/canonical.ts:77` (`id:"find", index:1`) · Simulation: `frontend/src/gtm/simulation.ts:46` · Providers: `backend/app/providers/job_sources.py`

---

# WHAT IS IT?

> 🟢 **BASIC**

**FIND** builds a broad but useful universe of **potential businesses before deciding which deserve attention**. It answers "what exists?" not "what's worth pursuing."

Input: scattered public signals (Maps, directories, hiring activity, websites, ads, reviews).
Output: **candidate business record** — `Company + Lead status=new` with source lineage.

It is the **only stage that creates Company/Lead rows** — downstream never creates, only transitions (`frontend/src/gtm/canonical.ts:128`).

---

# WHY DOES IT EXIST?

> 🟢 Without FIND, you only talk to who you already know. That starves the pipeline and biases toward familiar sources. FIND ensures **coverage**, then the next stages narrow with intelligence. It prevents pipeline starvation.

In GTM terms: FIND is the **top of the machine**, not the top of the funnel — every candidate is logged with `source_url + collected_at` so downstream can audit *why* it exists.

---

# WHAT GOES IN?

> 🟢 Three classes of raw signal (no judgment yet):

1. **Directory + Maps** — Google Maps listings, business directories, chambers, BBB/Yelp/Angi, state license DBs
2. **Web presence** — websites, social media, job postings, advertising (Google Ads active?), reviews (`google_rating, review_count`)
3. **Growth/expansion signals** — hiring activity, new-location indicators, tech footprints

> 🟡 All inputs arrive as `{name, website, phone, city, state, source, source_url}` normalized by pluggable provider adapters (`backend/app/providers/job_sources.py` + `providers/base.py Registry` — `JobsPipe, TheirStack, JSearch, FantasticJobs, Adzuna` + Maps scrapers — `frontend/src/gtm/canonical.ts:95`).

---

# WHAT HAPPENS?

> 🟡 Deterministic pipeline (no LLM):

1. **Scan** continuously via provider adapters — each provider's `fetch()` returns normalized candidates
2. **Normalize** to `{name, website, phone, city, state, source, source_url, collected_at}`
3. **Deduplicate** by `SHA-256(name|city|state)` + phone-normalized dedupe via `backend/app/services/phones.py` (dialer) — `canonical.ts:95`
4. **Check active/legitimate** — recency (`hiring_superseded? expired after 60d` per `hiring_signals.py:437`) + signal absence filter
5. **Create** `companies` + `leads(status=new)` + `hiring_signals` / `job_postings` rows (dual — consolidation pending) with source lineage (`source_url + collected_at`)
6. **Enforce idempotency** — `ON CONFLICT (workspace_id, source, source_job_id)` (`hiring_signals.py:370`) and `INSERT ... ON CONFLICT (workspace_id, lower(business_name), city, state) DO UPDATE` (`hiring_signals.py:306`) prevent double-counting
7. **Flag** `needs more info vs ready to UNDERSTAND` — low-info (no website) still profiled from Maps+jobs but flagged

> 🔴 Resilience: each provider wrapped with `CircuitBreaker(5,60s)+retry_with_backoff_sync(3)` (`canonical.ts:133`). Worker pool `discovery:1`. Provider fixtures fallback exists — masks failure if all sources return 0 (documented risk).

---

# WHAT DECISIONS ARE MADE?

> 🟡 FIND decisions (`frontend/src/gtm/canonical.ts:97`):

- **Is there enough information to evaluate?** → else mark `low-info`, keep monitoring (no website → still profiled, UNDERSTAND will have low confidence)
- **Does it match broad ICP filters?** → `home-services, local, owner-operated` — franchise/multi-location not yet filtered (that's QUALIFY's job)
- **Is it active and legitimate vs closed/stale?** → hiring recency + `expires_at`, review recency; `hiring_superseded expired after 60d`
- **Duplicate of existing business?** → `SHA-256` + phone dedupe → merge/keep best record; fuzzy dedupe `>0.9 SequenceMatcher` in `hiring_signals.dedupe_postings:409` for cross-provider dups

---

# WHAT COMES OUT?

> 🟡

- **Candidate business record** — `companies.id, business_name, city, state, vertical, website, phone, source` + `leads(id, status=new, lead_score null, fit_status null, updated_at)`
- **Initial profile** — `type, size proxy, services, location` (lightweight until UNDERSTAND enriches)
- **Flag** — `needs more info vs ready to UNDERSTAND`
- **Source lineage for audit** — every contact stores `source URL + date` (`source_url, collected_at`, `job_url` in `hiring_signals.py:362`) — downstream evidence bundles cite this URL

---

# REAL-WORLD EXAMPLE — ABC HVAC at FIND

> 🟢 Local HVAC, 3 service areas (Greensboro / High Point / Winston-Salem), hiring dispatcher, weak booking

**Raw input observed:**

```
Local HVAC, 3 service areas mentioned (Greensboro, High Point, Winston-Salem)
New dispatcher job posting — $18-22/hr — "answer 50+ inbound calls/day"
Google Ads active, website exists but booking flow weak (not yet known — FIND doesn't crawl)
```

**FIND interpretation:**

> Raw candidate — not yet a judgment. Deduplicated `SHA-256("ABC HVAC|Greensboro|NC")`. Created `Company + Lead status=new` with source lineage. Stored as lead `status=new`, company deduplicated on `city/state`, activity logged. Possible call-handling pressure noted but not scored — UNDERSTAND will confirm.

**Rows written:** `companies(business_name='ABC HVAC', city='Greensboro', state='NC', website='abchvac.example.com', source='jsearch', phone='+13365551234')`, `leads(status='new', company_id=…)`, `hiring_signals(title='Dispatcher', role_category='dispatcher', signal_score 78, freshness 0.9, intent_category='medium_value')` or `job_postings` twin, `activities(type='ai_action', summary='candidate created from Maps+JSearch…', actor='agent')`.

> Source: `frontend/src/gtm/simulation.ts:46` `ABC_HVAC_SIMULATION[0]` (stage find) — see `whatOrbitKnows`, `signalFound`, `decision`.

---

# WHAT CAN GO WRONG?

> 🟡 Cataloged in `frontend/src/gtm/canonical.ts:118`:

- **Scraping blocked (anti-bot)** → source adapter returns `[]` silently; provider fixtures fallback masks failure; no alert if all sources return 0
- **Phone normalization skipped** → duplicate leads slip through, double-contact risk (phone stored raw vs E.164 via `phones.normalize_phone`)
- **Direct DB insert bypasses dedupe logic** → duplicate companies with same `name+city+state` but different whitespace/casing — dedupe `SHA-256` not enforced at DB unique index for all variance forms
- **No RLS row filter** → tenant leak if `workspace_id` not supplied (conftest showed `/events/pending` unscoped)
- **No threshold for zero results** — starvation invisible

> 🔴 Mitigation: use `hiring_signals.dedupe_postings:409` fuzzy `>0.9` for cross-provider, phone-normalized via `phones.normalize_phone`, and always pass `workspace_id` to `_resolve_company:296`.

---

# EDGE CASES

> 🟡 (`frontend/src/gtm/canonical.ts:112`)

- **Duplicate name with slightly different spelling** → normalized `name+city+state` dedupe catches it; phone dedupe in dialer is second net
- **Business with no website** → still profiled from Maps + jobs, marked low-info, UNDERSTAND will have low confidence and may route to `rejected_unclear`
- **Inactive/closed business** → filtered via recency + signal absence; `hiring_superseded` expired after 60d (`hiring_signals.apply_expiry:437` + `intent_engine EVENT_LOOKBACK_DAYS=30`)
- **CSV import with 5-row preview** → column mapping + header detection prevents bad data entering FIND (frontend importer, PLANNED column-mapped ingest)

---

# WHAT HAPPENS NEXT?

> 🟢 `FIND` produces raw candidates; `UNDERSTAND` enriches them so signals become interpretable:

- **→ UNDERSTAND** (`05-qualification`? Actually next is `05` UNDERSTAND continuity) enriches `website_intel.fetch_website_intel()` + `hiring_signals.process` into `tech_signals + website_findings` so QUALIFY can score.
- FIND is the only stage that **creates Company/Lead rows** — downstream never creates, only transitions via `state_machine.transition` (`backend/app/services/state_machine.py:40`).

> If FIND flagged `low-info`, the lead stays `new` and is re-checked on next scan rather than advanced.

---

# WHY DOES IT MATTER?

> 🟢 Coverage is strategy. Without FIND you optimize only within what you already see; with FIND you build **a machine that finds fewer, better leads with a clear reason to reach out**. Every downstream evidence bundle traces to the `source_url + collected_at` written here — break FIND, break the audit trail.

---

# DEEPER DETAIL (technical)

> 🔴 **BUILDER — progressive disclosure: read only if wiring providers or dedupe**

**Implemented (✅):**

- Providers: `backend/app/providers/job_sources.py` + `backend/app/providers/base.py` `Registry` with fixture overrides; list includes `JobsPipe, TheirStack, JSearch, FantasticJobs, Adzuna + Maps scrapers` — per `frontend/src/gtm/canonical.ts:133`
- Dedupe: `backend/app/services/hiring_signals.py:409` `dedupe_postings` (seen_keys `(source, source_job_id|job_url)` + fuzzy `SequenceMatcher >0.9` on `company_name+title`), plus `pipeline.py` `SHA-256(name|city|state)` and dialer phone-normalized (`backend/app/services/phones.py`)
- State: `leads.status='new'` initial; tables `companies, leads, job_postings/hiring_signals` (dual — migration consolidation pending); worker `discovery:1`
- Resilience: `CircuitBreaker(5,60s)+retry_with_backoff_sync(3)` per provider invocation; `hiring_signals.upsert_hiring_signal:315` `ON CONFLICT (workspace_id, source, coalesce(source_job_id, job_url))` + `_resolve_company:306` `ON CONFLICT (workspace_id, lower(business_name), city, state)`
- Tracing: `backendModules ["app/providers/job_sources.py", "app/services/pipeline.py", "app/routers/leads.py"]`, `stateMachine "new → enriching"`, `agent "GTM_LEADS"`, `tables ["companies","leads","job_postings","hiring_signals"]` — `frontend/src/gtm/canonical.ts:134`

**Planned / known gaps (🚧 / 🐛):**

- Fixture fallback masking 0-result failure → no starvation alert (planned: threshold monitor)
- Direct DB insert dedupe bypass → needs unique index on `lower(trim(business_name)), lower(city), state` (planned migration)
- RLS/workspace scoping gap on some read endpoints → needs conftest fix (known from `canonical.ts:122`)

**Reference simulation:** `frontend/src/gtm/simulation.ts:46` — ABC_HVAC_SIMULATION entry 0 (`stage:"find"`) mirrors this doc's example field-for-field.

---
*Stage 1 of 12 — Next: UNDERSTAND (`05-qualification` or split: `UNDERSTAND` enriches FIND's raw profile before QUALIFY scores).*
