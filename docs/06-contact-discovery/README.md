# STAGE 04 — IDENTIFY (Who Should We Talk To?)

> **IETM teaching doc · Stage 4 of 12 · Progressive disclosure: 🟢 Everyone → 🟡 Operator → 🔴 Builder**
> Canonical: `frontend/src/gtm/canonical.ts:271` (`id:"identify", index:4`) · Simulation: `frontend/src/gtm/simulation.ts:103` · Enrichment: `backend/app/services/enrichment.py:194` · Finder: `backend/app/providers/email_finder.py`

---

# WHAT IS IT?

> 🟢 **BASIC**

A **correct contact is not someone who works at the company; it's someone who understands the problem, influences the decision, or approves the solution.** IDENTIFY ranks decision makers, finds verified contact info, and blocks sends that aren't ready.

Company → Person → **Verified contact** (or `HOLD`). Finding a name is not enough — the email must be `verified`, not suppressed, and not a generic `info@`.

---

# WHY DOES IT EXIST?

> 🟢 Two failures if you skip it:

1. **Right person at wrong time fails; wrong person at right time also fails.** Picking the title that matches the problem angle (ops problem → ops manager) doubles relevance.
2. **Blasting `info@` or unverified emails destroys deliverability** — one hard bounce degrades `mailboxes.health_state` (`scheduler.HEALTH_MULTIPLIER`) and pauses the whole domain.

IDENTIFY maximizes relevance **and** protects domain health by failing closed: no verified contact → `HOLD`, not send.

---

# WHAT GOES IN?

> 🟡 Three inputs, one gate, one ranking:

- **Qualified company** — `fit_status==qualified` (hard-gated in `pipeline.apply_enrichment:281` + `enrichment.enrich_company_waterfall` pre-check `pipeline.py:178`)
- **Opportunity angle** — ops vs hiring vs booking (produced by `OPPORTUNITY` or hypothesized from `hiring_signals.pain_hypothesis`) to **choose which role to prefer** (ops problem → ops manager/GM, hiring pressure → owner/ops leader, booking → owner/office manager, multi-location → founder/regional operator — `canonical.ts:289`)
- **Title ranking + verification waterfall** — providers `Apollo/Hunter/Clearbit` with priority `apollo>hunter>clearbit` via `flags.enrichment_provider_priority` (`enrichment.py:99`) and quota reserve 20 (`enrichment.track_provider_usage:109`), then verification cascade (`_local_prechecks:279` → `ZeroBounce>HunterVerify` per `flags.verification_provider_priority` at `enrichment.py:360`)

---

# WHAT HAPPENS?

> 🟡 Deterministic ranking + waterfall, step by step:

1. **Rank decision makers** by `rank_title()` (`enrichment.py:251`): `Owner 1, Founder 2, President 3, GM 4, Operations Manager 5, Service Manager 6, Office Manager 7, Dispatcher Lead 8, Dispatcher 8, other 99`. Full 10-title loop `Owner, Founder, President, General Manager, GM, Operations Manager, Service Manager, Office Manager, Dispatcher Lead, Dispatcher` (`enrichment.py:210`).
2. **Waterfall enrich** — `enrich_company_waterfall:144` tries providers in `flag` priority, calls `provider.enrich_company(enriched)` (`providers/base.py`), merges `result` into `COMPANY_ENRICHABLE_FIELDS` (`enrichment.py:44`) via `_update_company:54`, logs `enrichments` row, stops when `filled_after >= len(TARGET_FIELDS) or filled_before unchanged` (`enrichment.py:181`). Tracks `provider_usage` quota per `track_provider_usage:109`.
3. **Find email** — `find_decision_maker_email:194` loops 10 titles via `finder.find_email(company, contact_name, title)` (`email_finder.py`), picks `best_result` by `rank < best_rank or (rank==best_rank & confidence>best_confidence)` (`enrichment.py:228`), inserts `contacts(workspace_id, company_id, email, email_verification_status='unknown', is_decision_maker=true) ON CONFLICT DO NOTHING` (`enrichment.py:239`).
4. **Verify waterfall** — `verify_email_waterfall:318` loads `contacts`, runs `_local_prechecks:279` (`EMAIL_RE` (`enrichment.py:23`), `DISPOSABLE_DOMAINS 22`, `SPAM_TRAP_KEYWORDS`, DNS MX via `dns.resolver`), returns `disposable/ spam_trap / invalid` immediately if local fails, else loops `zerobounce>hunter_verify` providers, calls `provider.verify(email)` → `VerificationResult(result='valid', confidence≥0.9)` → `mark_provider_verified()` (`enrichment.py:381`) updates `contacts.email_verification_status='verified'`.
5. **Cross-check gates** — `suppression.check()` (`outbound_gate.py:120` global/email/phone/company + `email_service.suppression_check:175`), duplicate check (`companies` uniqueness), `DNC` check. Generic `info@` → `HOLD`, not sent (`canonical.ts:289`).

> 🔴 Also: `pipeline.verify_email:438` (syntax+DNS gate) and `_local_prechecks:279` are **separate code paths** — caller-dependent which runs first. Both set `syntax_ok → 30pts, dns_ok → 60pts`.

---

# WHAT DECISIONS ARE MADE?

> 🟡 (`frontend/src/gtm/canonical.ts:290`)

- **Which role most likely cares?** → title ranking + angle match. For ABC HVAC ops+hiring pressure → `Owner` (rank 1) preferred.
- **Is the contact usable?** → verified + `not opted_out` + not suppressed + not duplicate → else `HOLD` with `reason='bad contact'` (`canonical.ts:304`)
- **Multiple strong contacts?** → pick one highest-ranked, note alternative for later (`contacts.is_decision_maker` + `notes` for handoff packet)
- **Wrong person reply later ("not me, talk to X")?** → later `RESPONSE` stage classifies `WRONG_PERSON` and re-identifies with named referral — don't suppress domain (`canonical.ts:294`)

---

# WHAT COMES OUT?

> 🟡

- **Likely decision maker + verified contact** — `contacts(id, email, email_verification_status='verified', email_verification_confidence, email_verification_provider, verified_at, is_decision_maker)` or `HOLD` if poor quality
- **Enrichment provenance** — `enrichments(workspace_id, company_id, provider, operation, request, response, succeeded, cost_units)` + `contacts` triage fields `provider_used, confidence, source_notes, verified_at`
- **Suppression/DNC clearance** — `outbound_gate.not_suppressed` check passed; `contacts.opt_out_flag false`
- **Lead linkage** — `leads.contact_id` updated atomically via `pipeline.apply_enrichment:288-319` (not via `find_decision_maker_email` alone — see "What can go wrong" about that bug). Lead stays `enriching` until enrichment complete, then `qualified` via `state_machine.transition(enriching→qualified)` (`pipeline.py:318`)

> ⚠️ `find_decision_maker_email` inserts `contacts ... ON CONFLICT DO NOTHING` **without** linking `leads.contact_id` — known bug (`canonical.ts:300`). Always treat `pipeline.apply_enrichment` as the atomic path that writes `leads.contact_id`.

---

# REAL-WORLD EXAMPLE — ABC HVAC at IDENTIFY

> 🟢 Local HVAC, 3 areas, hiring dispatcher, weak booking:

**Signal → angle → person mapping:** Operational + hiring pressure → `Owner` or `Operations Manager`. Strongest pain is dispatch strain → Owner is closest to workforce decisions.

**Orbit waterfall (from `simulation.ts:103`):**

```
Title ranking: Owner (1) > GM (10) > Ops Manager (12) — angle matches Owner/ops
Waterfall priority apollo>hunter>clearbit: Apollo finds Maria Chen owner, 92% confidence
ZeroBounce verifies → verified (provider confidence 0.97 ≥0.9)
Suppression check clear (global+email+phone+company via suppression.check)
Generic info@ also found but discarded per rule — need decision maker
```

**Writes:**
```
contacts(id, workspace_id, company_id, email='maria@abchvac.example.com',
         email_verification_status='verified', email_verification_confidence=92,
         email_verification_provider='zerobounce', email_verified_at=now(),
         is_decision_maker=true)
leads(contact_id=<contacts.id>) — via pipeline.apply_enrichment atomic
provider_usage(used+1, period=2026-08) — tracks Apollo quota, deprioritizes at quota-reserve 20
```

If only generic found, gate will `HOLD` with reason `'bad contact'` — verified `info@` not sent even if available (`canonical.ts:289`).

---

# WHAT CAN GO WRONG?

> 🟡 (`frontend/src/gtm/canonical.ts:312`)

- **`TARGET_FIELDS has owner_email but COMPANY_ENRICHABLE_FIELDS lacks column → enriched owner_email silently dropped`** (data loss, still appears unverified) — `enrichment.py:27,44` (`TARGET_FIELDS 6` vs `COMPANY_ENRICHABLE_FIELDS 14` mismatch)
- **`find_decision_maker_email` inserts contacts `ON CONFLICT DO NOTHING` but never updates `leads.contact_id` → lead stays contact-less, gate fails with 'no email' even though contact exists** (`enrichment.py:239` + `canonical.ts:314`). Mitigate: call `pipeline.apply_enrichment` not `find_decision_maker_email` directly from pipeline.
- **`rank_title` duplicated with different values** (`enrichment 5 keys vs email_finder 10 keys, 1-99 mapping divergence` — `canonical.ts:315`) → waterfall picks different best title per path depending on which map was evaluated.
- **Phone normalization caller-dependent:** `suppression.check` lowercases email but phone not normalized → suppressed phone bypasses if stored normalized vs raw (`canonical.ts:316`).
- **Quota 0 initial row treated as unlimited then later `quota>0` check inverts deprioritization logic for first call** (`enrichment.track_provider_usage:136` — first insert `quota=0, used=1` returns `True`, later same provider with `quota>0` triggers reserve gate at `quota - 20`).

---

# EDGE CASES

> 🟡 (`frontend/src/gtm/canonical.ts:306`)

- **Generic contact only** → `HOLD`, don't blast `info@`; log review queue `'missing owner'` (operator pulls owner manually via Maps/LinkedIn)
- **Wrong person later (`"not me, talk to X"`)** → `RESPONSE` classifies `WRONG_PERSON`, re-identifies with named referral `jamie@abchvac...` (higher confidence than waterfall because explicit referrer), don't mark company suppressed
- **Multiple strong contacts (Owner + GM)** → pick `Owner` (rank 1), keep GM as alternative in `contacts.notes` for handoff packet second contact
- **Disposable domain (`mailinator.com`)** → `_local_prechecks` fails `22-list` **before burning provider quota** (`enrichment.py:301`) — cheap local check saves paid quota
- **Spam-trap keyword (`abuse@, noreply@`)** → local `SPAM_TRAP_KEYWORDS` fails before provider (`enrichment.py:304`)

---

# WHAT HAPPENS NEXT?

> 🟢 `IDENTIFY` output is the **who** that `OPPORTUNITY` pairs with **what's happening** to craft a reason to reach out:

- **→ OPPORTUNITY** (`07-opportunity/`) uses that person + problem + timing to build a **personalized angle** (`research_reports` + `scores` + `contacts` → `opportunity.py:238`). Without a verified contact, `OPPORTUNITY` still writes a profile (observed pain) but `GATE` will `HOLD` with `'no verified contact'` (`canonical.ts:373`).
- IDENTIFY is gated on `QUALIFY` (hard rule, `pipeline.py:178`) and produces the contact gate `OUTREACH` checks (`outbound_gate.can_send:130` `email_verified` check).

---

# WHY DOES IT MATTER?

> 🟢 Deliverability + relevance. One unverified email or wrong person damages **domain health** (`mailbox_health.py`) and wastes human review. Fail-closed contact quality protects **the entire system** — a single `info@` hard bounce can pause `mailboxes.health_state='paused'` across the domain and block hundreds of queued sends.

This gate is also **compliance**: CAN-SPAM requires an unsubscribe mechanism, and Orbit enforces `suppression` hard gate in code not UI (spec §11.2), checked on every `verify_email_waterfall` exit path.

---

# DEEPER DETAIL (technical)

> 🔴 **BUILDER**

**Files & gates:**

| File | Lines | Note |
|------|-------|------|
| `backend/app/services/enrichment.py:27` | `TARGET_FIELDS 6` | what enrichment considers "done" |
| `backend/app/services/enrichment.py:44` | `COMPANY_ENRICHABLE_FIELDS 14` | only columns that `_update_company` writes (owner_email missing → silent drop) |
| `backend/app/services/enrichment.py:109` | `track_provider_usage()` | quota with `reserve_threshold 20`; returns False to deprioritize when `used >= quota - reserve` |
| `backend/app/services/enrichment.py:144` | `enrich_company_waterfall()` | priority `flag:enrichment_provider_priority` default `apollo→hunter→clearbit`, stop when `filled_after >= len(TARGET_FIELDS)` |
| `backend/app/services/enrichment.py:194` | `find_decision_maker_email()` | 10-title loop + `rank_title:251` pick best |
| `backend/app/services/enrichment.py:251` | `rank_title()` | `owner 1, founder 2, president 3, gm 4, opsmgr 5, ... 8, other 99` |
| `backend/app/services/enrichment.py:279` | `_local_prechecks()` | `syntax 0.3 → dns 0.6` confidence, `DISPOSABLE_DOMAINS 22`, `SPAM_TRAP_KEYWORDS 15` |
| `backend/app/services/enrichment.py:318` | `verify_email_waterfall()` | local precheck → provider waterfall default `zerobounce→hunter_verify`, `result=='valid' && confidence>=0.9 → mark_provider_verified` |
| `backend/app/providers/email_finder.py` | `ApolloEmailFinder rank_title` | duplicate map (10 keys vs 5 in enrichment) — dedupe planned |
| `backend/app/providers/email_verification.py` | `ZeroBounce/HunterVerify, CircuitBreaker, fixture fallback` | |
| `backend/app/services/pipeline.py:178` | hard gate | `fit_status==qualified` else `PipelineError` |
| `backend/app/services/suppression.py` | `check()` + `add()` | hard gate, global/email/phone/company, phone normalized via `phones.normalize_phone` in some callers but not all |

**Contracts the gate enforces:**

- `contacts.email + contacts.email_verification_status=='verified'` must hold before `OUTBOUND GATE` can pass (`outbound_gate.can_send:130` checks `email_verification_status=='verified'`, not `syntax_ok`/`dns_ok`)
- Tables: `contacts` (email + verification), `companies` (owner_name, phone, tech_signals), `suppression` (scope, value, reason) — `frontend/src/gtm/canonical.ts:333`
- Worker pools: `enrichment:2, verification:2` (from `canonical.ts:197`)
- Simulation trace: `frontend/src/gtm/simulation.ts:103` mirrors Apollo→ZeroBounce with 92% exactly

**Status:**
- ✅ IMPLEMENTED — waterfall ranking, provider priority via flags, local prechecks, quota tracking, verification gating
- 🐛 KNOWN BUGS (documented, not hidden) — `owner_email` drop, `leads.contact_id` unlink on direct Finder path, `rank_title` duplicate maps, phone-normalization caller-dependence, quota 0-first-row edge — see `canonical.ts:312-317`
- 🚧 PLANNED — unique index on `contacts(email)` with workspace-aware soft enforcement (currently `ON CONFLICT DO NOTHING` global), single `rank_title` consolidation

---
*Trace: `app/services/enrichment.py`, `app/providers/email_finder.py`, `app/providers/email_verification.py` — tables `contacts, companies, suppression` — `frontend/src/gtm/canonical.ts:271`.*
