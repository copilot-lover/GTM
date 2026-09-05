# 04 — GTM_LEADS (Pipeline Contexts, Enrichment Waterfall, Scoring)

## Role
GTM_LEADS owns FIND→UNDERSTAND→QUALIFY→IDENTIFY deterministic reasoning. Agent spec: `app/agents/registry.py:14` `read_prospects, write_qualification, write_contacts, cannot_send True`.

## Pipeline Contexts (n8n contract)
**File:** `services/pipeline.py:165` `stage_context(workspace_id, lead_id, stage) → {system, user, required_keys}`

| Stage | System prompt | User payload | Hard gate |
|-------|---------------|--------------|-----------|
| qualification | `QUALIFY_SYSTEM:95` (detect ICP signals single_location etc, fail-closed unclear→false) | business_name, website, city/state, vertical, rating, locations, source_evidence | none (entry) |
| enrichment | `ENRICH_SYSTEM:107` (extract owner/name/email verbatim, NEVER guess) | business_name, page_content placeholder, scrape_url | `fit_status==qualified` else PipelineError + flag review (`pipeline.py:179`) |
| audit | `AUDIT_SYSTEM:115` (detect has_online_booking, chatbot, mobile, after_hours, pain_points quoting content) | business, homepage_content placeholder, scrape_url | website required else flag `audit skipped: no website` (`pipeline.py:190`) |
| offer | `OFFER_SYSTEM:138` (choose ONE offer_id from OFFER_CATALOG, cite pain) | business_name, vertical, primary/secondary pain, pain_points | `primary_pain` required else PipelineError (`pipeline.py:199`) |
| draft | `PERSONALIZE_SYSTEM:146` (Hermes 4 sentences, <75 words, plain, no invented facts) | owner_name None fail-closed, business_name, evidence {observed, pains, website_findings}, offer | `primary_pain && recommended_offer` else error (`pipeline.py:208`) |

`STAGE_KEYS:154` maps required response JSON keys per stage. n8n workflow: GET context → scrape via `POST /api/scrape` → call LLM itself → POST `/api/pipeline/{lead_id}/apply/{stage}`.

**Backend never calls LLM** (`pipeline.py:1` header + `pipeline.py:84` _emit events only deterministically).

## Apply Pipeline (deterministic validators)
- `apply_qualification:240` → `scoring.icp_fit_score:39` → `fit_status_for:55` (threshold 6, too_large check) → `priority_score:71` (0-100) → update leads + `state_machine.transition new→enriching|rejected:266` + emit `lead.enrichment_requested`.
- `apply_enrichment:279` → validate qualified, update companies owner_name, `verify_email:440` syntax+DNS, handle review_reasons, `state_machine.transition enriching→qualified:318`, emit `lead.audit_requested`.
- `apply_audit:325` → require pains+primary, `primary in pains` check, update website_findings/primary_pain, emit `lead.offer_requested`.
- `apply_offer:351` → `offer ∈ OFFER_CATALOG:357`, `PAIN_TO_OFFER:125` contract `expected == offer` else flag `offer-pain contract violation:363` + PipelineError.
- `apply_draft:384` → word_count<75, BANNED_PHRASES (`pipeline.py:377` 11 phrases), 4-sentence `re.split:401`, flag review on fail, `create_draft_message:416` inserts messages pending_approval + `gtm_lifecycle.transition_message NULL→QA_PENDING:432`.

All `apply_*` use `_load_lead:30` join leads→companies, `_update_lead:53` whitelist `_LEAD_UPDATABLE:46`, `_add_activity:66`, `_flag_review:75`, `_emit:84` outbox. Tests `tests/test_pipeline.py:66` qualification, `109` enrichment gating, `141` offer contract, `167` draft QA.

## Enrichment Waterfall
**File:** `services/enrichment.py:144` `enrich_company_waterfall(company_id)`
- Priority via flag `enrichment_provider_priority` default `["apollo","hunter","clearbit"]` (`enrichment.py:154`).
- Loop checks `track_provider_usage:109` quota reserve 20 (`provider_usage` table) — returns False if `used >= quota-reserve`.
- Calls `registry.get(provider).enrich_company(enriched)` → merges → `_update_company:54` filters to `COMPANY_ENRICHABLE_FIELDS:44` (valid columns only) → `_log_enrichment:77` to `enrichments` table.
- Stops when `filled_after >= len(TARGET_FIELDS:27 6 fields)` or no progress (`enrichment.py:181`).
- Quota period monthly `YYYY-MM` (`enrichment.py:112`).

**Decision-maker:** `find_decision_maker_email:194` loops 10 titles Owner/Founder/...Dispatcher (`enrichment.py:210`), calls `apollo_email_finder.find_email` per title, ranks via `rank_title:251` (owner 1, founder 2, etc), inserts into `contacts` `ON CONFLICT DO NOTHING` (`enrichment.py:238`) PARTIALLY — does not update `leads.contact_id`, so lead may stay contact-less and gate fails `no email`. Must be handled by caller `pipeline.apply_enrichment`.

**Verification:** `verify_email_waterfall:318` local prechecks `DNS MX + disposable 22 + spam-trap 12` (`enrichment.py:279`) → provider waterfall `zerobounce/hunter_verify` (`enrichment.py:360`) → on valid≥0.9 call `mark_provider_verified` (`email_service.py:546`).

**PARTIALLY IMPLEMENTED:** `TARGET_FIELDS` has `owner_email` (`enrichment.py:27`) but `COMPANY_ENRICHABLE_FIELDS` lacks it → enriched owner_email dropped (`enrichment.py:58` filter). Rank_title duplicated with different values vs email_finder provider.

## Scoring (within LEADS scope)
- `services/scoring.py:39` `icp_fit_score(signals)` total ± weighted → `max(0,min(10, round(total/1.8)))` detail ± map. Weights `ICP_SIGNAL_WEIGHTS:3` (+1 to +3) and `ICP_NEGATIVE_WEIGHTS:12` (-3 to -4). Clamped.
- Threshold `QUALIFY_THRESHOLD=6` (`scoring.py:20`). `fit_status_for:55` → too_large? rejected_too_large : score≥6 qualified : unclear? rejected_unclear : score≥4 borderline : rejected_not_relevant. `signals_too_large:67` checks enterprise/national.
- `priority_score:71` weighted 0.40 intent +0.30 fit +0.20 contact +0.10 history (normalized 0-1 → 0-100). Used in `pipeline.apply_qualification:244` with history 0.
- Frontend mirrors tiers `frontend/src/gtm/canonical.ts:224` P1 85-100 etc.

## What Component Owns vs Not
- **LEADS owns:** contexts, scoring arithmetic, gating, waterfall orchestration, contact creation (but not send).
- **Does NOT own:** LLM calls (n8n), SMTP send (email_service), message lifecycle beyond draft creation (gtm_lifecycle), intent re-evaluation (intent_engine), mailbox health.

## Invariants / Contracts
- Evidence mandatory for qualify; never invent email/name (`pipeline.py:212` owner_name None).
- Offer-pain deterministic link (`pipeline.py:362`).
- Draft 75w/4-sentence/banned-phrase enforced both in pipeline and qa_service (duplicate drift risk).

## Safe vs Dangerous
- Safe: tune `QUALIFY_THRESHOLD`, adjust waterfall priority via `system_flags`, add pain→offer mapping.
- Dangerous: remove enrichment gate, bypass `_update_lead` whitelist, invent email via string concat, skip `verify_email`.

## Before/After Modifying
- Before: read `services/pipeline.py:165` + `services/enrichment.py:144` + `tests/test_pipeline.py`.
- After: `pytest tests/test_pipeline.py tests/test_enrichment_verification.py tests/test_scoring.py`; check `leads.review_reasons` and `event_outbox` emitted.

## Examples
- Qualification: Acme with single_location+owner_visible+residential+simple+local → score 8/10 → qualified (`tests/test_scoring.py:12`). Franchise+national → 0 (`tests/test_scoring.py:21`).
- Enrichment: qualified lead with website `https://acme.test` → waterfall finds owner via apollo, verifies syntax_ok→dns_ok→verified chain.
- Offer: primary_pain `no_online_booking` → `PAIN_TO_OFFER after_hours_booking` (`pipeline.py:126`) required; `review_generation` would raise mismatch (`tests/test_pipeline.py:142`).

## Related
- Intent engine (05-gtm-intent) reuses scoring but with recency decay.
- Outbound gate (08) checks verification status set here.
- QA service (09) re-validates draft constraints.
