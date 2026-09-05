# 05 — GTM_INTENT (Hiring Signals, Intent Engine, Website Intel)

## Role
GTM_INTENT answers: What is happening at this business and why now? Watches hiring/website/expansion signals continuously, re-scores existing leads, decays stale evidence. Agent: `app/agents/registry.py:18` `GTM_INTENT read_signals, write_scores, cannot_send`. Schedule default 900s (`app/config.py:80`).

## Hiring Signals Engine
**File:** `services/hiring_signals.py:1`

- **Role taxonomy:** 10 categories `ROLE_CATEGORIES:23` (receptionist, dispatcher, customer_service, appointment_setter, call_center, scheduler, service_coordinator, office_admin, sales, other) + `KEYWORD_ROLE_MAP:36`.
- **Classify:** `classify_role(title,desc):87` tries LLM cheap tier (`app/providers/base.py` LLMProvider complete) with JSON output, fallback keyword scan (`hiring_signals.py:113`). Returns `{role_category, confidence 0.3-0.7-1.0, rationale}`. Fail-closed other/low confidence if unclear.
- **Detect intent signals:** `detect_intent_signals:121` 7 bools: after_hours, phone_heavy, scheduling_duties, icp_match, high_volume, lead_intake, multiple_openings. LLM cheap tier first, keyword fallback (`hiring_signals.py:154` lists like after-hours/evening/weekend).
- **Score:** `compute_signal_score:188` additive weights `DEFAULT_SIGNAL_WEIGHTS:48` (dispatcher 35, receptionist 30, icp_match 30, high_volume 20, posted_3d 15, etc) + freshness: posted_3d/7d/14d bonuses. Company-based: weak_website, no_online_booking, no_after_hours, strong_reviews. Normalized `score*100/max_theoretical` clamped 0-100 → `intent_category high_value≥80, medium≥60, low≥40, irrelevant` (`hiring_signals.py:253`).
- **Freshness multiplier:** `FRESHNESS_MULTIPLIERS:69` 0d1.0,3d0.9,7d0.7,14d0.4,30d0.1. Missing posted_at → 0.05 (`hiring_signals.py:176`).
- **Normalize:** `normalize_raw_posting:265` title/desc/posted_at parse ISO, calls classify+detect, emits signal dict with source, source_job_id, job_url, company_name/city/state.
- **Resolve company:** `_resolve_company:296` INSERT ... ON CONFLICT (workspace_id, lower(name), city, state) DO UPDATE → company_id.
- **Upsert:** `upsert_hiring_signal:315` → fetch company, compute score, expires 60d (`base_date+ timedelta 60:340`), pain_hypothesis string (phone_heavy etc), orbit_product_fit ai_receptionist etc, INSERT INTO hiring_signals ON CONFLICT (workspace_id, source, coalesce(source_job_id, job_url)) DO UPDATE all fields (`hiring_signals.py:370`).
- **Dedupe:** `dedupe_postings:413` by (source, job_id) + fuzzy SequenceMatcher >0.9 same company+title across sources.
- **Expiry:** `apply_expiry:437` UPDATE status expired where expires_at<now or posted_at<now-60d, emit alerts for high/medium value.
- **Refresh scores:** `refresh_scores:468` PARTIALLY — re-parses without stored intent_signals (uses false defaults), so partial refresh.
- **Flags override:** `_get_signal_weights:167` merges `system_flags signal_scoring_weights` over defaults.

**What it owns:** raw → normalized signal, role/intent detection, scoring, dedupe, expiry.
**Not:** lead priority re-evaluation (intent_engine), website crawl (website_intel), outreach.

## Intent Engine (Re-evaluation)
**File:** `services/intent_engine.py:1`

- **Event registry:** `DEFAULT_EVENT_WEIGHTS:19` JOB_POSTED 35, JOB_REMOVED -10, NEW_LOCATION 25 etc (11 types). `register_event_type:38` mutable global `_extra_event_types` (no persistence, race unsafe PARTIALLY). `known_event_types:42` merges.
- **Ingest:** `ingest_event:58` validates event_type ∈ known, resolves lead_id from company_id highest priority_score if omitted (`intent_engine.py:73`), INSERT intent_events, enqueue `gtm_intent_process` via job_queue idempotency `intent-process-{row id}` (`intent_engine.py:103`).
- **Process batch:** `process_pending_events:117` UPDATE processed=true WHERE id IN (SELECT ... FOR UPDATE SKIP LOCKED LIMIT 200) → collect lead_ids/company_ids → resolve company→lead → `reevaluate_lead` per lead.
- **Re-evaluate:** `reevaluate_lead:181` deterministic full recalc:
  - Load lead, base_icp = lead_score*10 (`intent_engine.py:193`).
  - Fetch active hiring_signals + intent_events last 30d (`intent_engine.py:197`).
  - Per signal: age → recency `max(0,1-age/30)` (`intent_engine.py:216`), points `min(35, signal_score* freshness_multiplier*recency)` round 1 dec, label `{role_category} hiring`. `freshest_age` tracks min age.
  - Per event: weight*recency.
  - Total = base_icp + Σ contributions + bonus `signal_count>=4 → +10, ≥2 → +5` → clamp 0-100 (`intent_engine.py:246`).
  - Priority band: `total≥70 && freshest≤7 → P1` else `total≥50 or _has_tier_a → P2` else P3 (`intent_engine.py:256`). **Bug:** `_has_tier_a:282` reads `scores.tier` but reevaluate never writes tier → always P3 unless score≥50 PARTIALLY.
  - Writes `leads.priority_score` + INSERT scores score_type opportunity with components `{source: GTM_INTENT, base_icp, contributions[], signal_count, computed_at}` (`intent_engine.py:263`).
- **Terminal filter:** `_terminal_statuses_sql:169` excludes won/rejected/do_not_call/archived from company→lead resolution.
- **API:** `POST /gtm/leads/{id}/reevaluate` (`app/routers/gtm.py:221`) + `GET /gtm/leads/{id}/why` why-panel (`routers/gtm.py:161`) reads latest GTM_INTENT or any opportunity score.

**What it owns:** event→priority mapping, recency decay, explainable contributions for why-panel.
**Not:** signal creation (hiring_signals), offer selection (opportunity.py).

**Safe vs dangerous:**
- Safe: adjust EVENT weights, tweak recency formula constants, add new event_type via flag.
- Dangerous: change base_icp multiplier (*10) without migration, remove 30d lookback, break idempotency key.

## Website Intel
**File:** `services/website_intel.py:222`

- **Fetch:** `fetch_website_intel:222` loads company website, `scraping.scrape(website, stealth=True):99`, fallback empty result if missing/failed. Writes both companies.tech_signals + leads.website_findings (`website_intel.py:293`).
- **Extract:** `_extract_booking_cta:105` regex for book/schedule/appoint/reserve anchors/buttons; `_detect_chat_widget:122` intercom/drift etc 8 services; `_extract_phone_visible:141` tel: link; `_extract_forms:150` form→fields; `_check_ssl_valid:164` status 200 + https; `_check_mobile_viewport:169` meta viewport; `_detect_after_hours_messaging:174` footer/banner keywords after-hours/24/7; `_detect_tech_stack:188` patterns for servicetitan/housecall/jobber/workiz/hubspot/salesforce/calendly/ga/fb.
- **Gaps:** derive `after_hours_gap = has_phone && !after_hours`, `no_online_booking = !has_booking_cta`, `weak_website = !ssl || ttfb>3000 || !viewport` (`website_intel.py:274`).
- **LLM summarize:** `_llm_summarize_findings:196` cheap tier fallback if HTML complex; on LLM fail returns deterministic.
- **Schema:** `WEBSITE_FINDINGS_SCHEMA:70` booking_cta {text,href}, chat_widget, phone_visible, forms[], ssl_valid, mobile_viewport, ttfb_ms, after_hours etc.

**What it owns:** website → findings/tech_signals parsing.
**Not:** hiring intent, scoring, enrichment.

## Invariants / Contracts
- No writes to `leads.status` here; only priority/why-panel.
- Evidence assembled includes tech_signals + website findings + hiring signals for later research (`services/research.py:52`).
- Expiry 60d hiring, 30d intent event contributions decay to ~0 at 30d (stale 29d → 1/30 recency).

## Tests
- `tests/test_hiring_signals.py` role classification, scoring, dedupe.
- `tests/test_intent_engine` (via `tests/test_gtm_acceptance.py:209` stale vs fresh, `350` fresh hot reprioritizes then cools).
- Website intel: mock scraping provider, assert tech_signals written.

## Pitfalls flagged
- `_extra_event_types` no persistence → register lost on restart.
- `refresh_scores` ignores stored intent_signals → wrong refresh.
- `_has_tier_a` dead code due to missing tier write.

## Safe vs Dangerous (intent)
- Safe: tune DEFAULT_SIGNAL_WEIGHTS, recency window 30d via flag, add new TECH pattern.
- Dangerous: remove freshness_multiplier decay, persist _extra_event_types unsafely, change expires_at 60d without alert logic.

## What Must Be Tested After Modification
- `pytest tests/test_hiring_signals.py tests/test_gtm_acceptance.py -k intent` plus `GET /gtm/leads/{id}/why`; assert stale 29d → points ≤5 and not P1.

## Before/After
- Before: read `services/hiring_signals.py:188` + `intent_engine.py:181` + migrations for hiring_signals table.
- After: run `pytest tests/test_hiring_signals.py tests/test_gtm_acceptance.py -k intent`; verify `scores.components.contributions[]` and `leads.priority_score` updated; check `GET /gtm/leads/{id}/why`.

## Examples
- Fresh dispatcher hiring 0d score 100 freshness 1.0 recency 1.0 → ~35pts; stale 29d recency 0.03 → ≤1.2pts → P3 not P1 (`tests/test_gtm_acceptance.py:224`).
- Company with tech_signals housecall_pro + no_online_booking → signal_score +15 weak_website etc.
