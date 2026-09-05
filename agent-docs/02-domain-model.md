# 02 — Domain Model

Source: `db/migrations/0002_core_schema.sql:1` + `0008_gtm_agents.sql:11`; runtime `app/db.py:17`.

## companies
- **PK:** `id uuid` + `workspace_id` scoping. Dedupe unique `uq_companies_dedupe` on `(workspace_id, lower(business_name), coalesce(city,''), coalesce(state,''))` (`0002_core_schema.sql:28`).
- **Core:** `business_name, website, phone, address, city, state, zip, vertical, employee_estimate, number_of_locations, owner_name, owner_operator_confidence 0-100, google_rating, review_count`.
- **Signals:** `tech_signals jsonb` (ServiceTitan/Housecall etc via `services/website_intel.py:188`), `website_findings` also on leads (dual write), `source, source_url, collected_at`.
- **Ownership:** FIND creates (`services/pipeline.py` enrichment note: only FIND creates). UNDERSTAND enriches via `services/enrichment.py:54` _update_company (filters to `COMPANY_ENRICHABLE_FIELDS` `enrichment.py:44`) and `services/website_intel.py:293` _write_findings.
- **Pitfall:** `TARGET_FIELDS` includes `owner_email` but `COMPANY_ENRICHABLE_FIELDS` lacks it → silent drop (`enrichment.py:27` vs `44`) PARTIALLY IMPLEMENTED.

## contacts
- **Columns:** `id, workspace_id, company_id, name, title, email citext, email_verification_status ∈ {unknown,syntax_ok,dns_ok,verified,failed}` (`0002_core_schema.sql:38`), confidence/provider/verified_at, phone/line_type, `is_decision_maker`, `opt_out_flag`.
- **Ownership:** `services/enrichment.py:238` find_decision_maker_email inserts via waterfall; `services/pipeline.py:301` verify_email syntax+DNS; `services/enrichment.py:318` verify_email_waterfall provider → `mark_provider_verified` (`email_service.py:546`).
- **Contract:** `email_verification_status == 'verified'` required before send (`services/outbound_gate.py:130`, `services/email_service.py:170`, `services/qa_service.py:274`).
- **Missing-data:** generic `info@` → HOLD not send; disposable 22-list (`enrichment.py:264`) + spam trap keywords (`enrichment.py:272`) precheck before quota burn.

## leads
- **Status FSM:** `status ∈ new,enriching,qualified,signal_holding,outreach_ready,contacted,responded,qualified_conversation,meeting_booked,meeting_held,proposal,won,lost,rejected,do_not_call,unreachable,archived` (`0002_core_schema.sql:57`). Guarded via `services/state_machine.py:6`.
- **Qualification:** `fit_status ∈ pending,qualified,borderline,rejected_too_large,rejected_not_relevant,rejected_unclear` + `lead_score 0-10` + `priority_score 0-100` (`0002_core_schema.sql:63`). Written by `services/pipeline.py:240` apply_qualification (icp_fit_score/1.8) and `services/intent_engine.py:181` reevaluate.
- **Evidence:** `evidence jsonb` (icp_signals, agent_evidence), `website_findings jsonb`, `primary_pain, secondary_pain, recommended_offer, personalization_notes, review_reasons jsonb`, `next_action_at`, `compliance jsonb`.
- **FK:** `company_id, contact_id nullable`. `contact_id` must be updated atomically with contacts insert (`services/pipeline.py:299` vs enrichment gap).
- **Safe vs dangerous:** Safe to add `review_reasons` entry; dangerous to invent `fit_status` without evidence.

## messages (email/SMS)
- **Dual status:** `status ∈ drafted,pending_approval,approved,scheduled,sent,delivered,opened,replied,bounced,failed,rejected` + `gtm_stage ∈ DISCOVERED..CANCELLED or NULL legacy` (`0008_gtm_agents.sql:15`). `AUTHORIZED_SEND_STAGES = SEND_READY,SCHEDULED` (`services/gtm_lifecycle.py:20`).
- **Enrichment columns:** `claims jsonb, evidence_refs jsonb, copy_input jsonb, experiment_id, prompt_version, originating_mailbox_id uuid` (`0008_gtm_agents.sql:101`).
- **Gate-enforced:** `services/pipeline.py:432` enrolls NULL→QA_PENDING on draft create; `services/qa_service.py:177` QA_PENDING→QA_PASSED/FAILED; `services/email_service.py:71` approve checks QA_PASSED/SEND_READY; `services/email_service.py:125` claim_for_send re-checks gate.
- **Idempotency:** `idempotency_key unique`, `provider_message_id unique` (`0002_core_schema.sql:128`).

## qa_runs
- **Schema:** `workspace_id, object_type∈lead,research,copy,compliance, object_id, score, status∈passed/failed, findings jsonb, evidence_refs, failed_rules, attempt, model` (`0008_gtm_agents.sql:35`) index `ix_qa_runs_object`.
- **Logic:** `_store_qa_run` increments attempt (`services/qa_service.py:49`), `_failed_rules` critical only (`services/qa_service.py:45`). Copy QA fails closed on missing subject/body, unsupported claim, WRONG_SIGNAL, GENERIC_COPY (`services/qa_service.py:190`).
- **Must preserve:** ordering `ORDER BY created_at DESC, id DESC` in qa_service vs `created_at DESC LIMIT 1` in outbound_gate (`services/outbound_gate.py:56` vs `services/qa_service.py:117` divergence PARTIALLY).

## intent_events
- **Schema:** `workspace_id, company_id, lead_id, signal_id, event_type text (extensible registry, not SQL enum), source, payload jsonb, occurred_at, processed boolean, processed_at` (`0008_gtm_agents.sql:54`).
- **Ingestion:** `services/intent_engine.py:58` ingest_event validates known_event_types (`intent_engine.py:19`), resolves lead from company highest priority, enqueues `gtm_intent_process`. `process_pending_events` claims via `FOR UPDATE SKIP LOCKED` (`intent_engine.py:121`).
- **Re-evaluation:** `reevaluate_lead` decays recency `1 - age/30` (`intent_engine.py:216`), clamps MAX_SIGNAL 35, writes `scores` row `score_type='opportunity'` with components (`intent_engine.py:268`).
- **PARTIALLY:** `_has_tier_a` reads tier never written (`intent_engine.py:282`).

## hiring_signals
- **Columns:** `workspace_id, company_id, source, source_job_id, job_url, title, description, role_category ∈ 10` (`services/hiring_signals.py:23`), `intent_category high/medium/low/irrelevant`, `pain_hypothesis, orbit_product_fit, confidence, signal_score 0-100, freshness_multiplier, expires_at, status active/expired, posted_at`.
- **Logic:** `classify_role` LLM cheap→keyword fallback (`hiring_signals.py:87`); `detect_intent_signals` 7 bools (`hiring_signals.py:121`); `compute_signal_score` additive (`hiring_signals.py:188`); `upsert_hiring_signal` expires 60d (`hiring_signals.py:338`); `dedupe_postings` fuzzy >0.9 (`hiring_signals.py:413`); `apply_expiry` alerts high_value (`hiring_signals.py:437`).
- **Dual table:** `job_postings` still used in `research.py:82` alongside hiring_signals — migration pending PARTIALLY.

## scores
- **Use:** `score_type='opportunity'` stores GTM_INTENT priority (0-100) + components contributions + signal_count; `score_type='emv'` basis points (`services/opportunity.py:443`), `opportunity.py:361` also writes opportunity_score with tier. Index per lead. `intent_engine.py:268` and `opportunity.py:361` compete for same `scores` semantics — distinguish via `components.source='GTM_INTENT'` (`app/routers/gtm.py:176`).

## activities
- **Schema:** `workspace_id, lead_id, type∈email/call/sms/ai_action/meeting/note/system, summary, payload, actor∈human/agent/system` (`0002_core_schema.sql:87`). Written on every transition/draft/send/kill_switch (`services/pipeline.py:66` _add_activity, `services/email_service.py:215` sent, `services/email_service.py:408` KILL SWITCH). Timeline source of truth for CONVERSE.

## Valid States / Contracts Preserve
- `leads.status` only via `services/state_machine.py:6` FSM; `messages.gtm_stage` only via `services/gtm_lifecycle.py:31` AUTHORIZED_SEND_STAGES SEND_READY/SCHEDULED.
- Never change column types/checks without migration (`0002_core_schema.sql:57` CHECK).

## Safe vs Dangerous
- Safe: add new JSONB key to evidence/components, add index, log extra activity.
- Dangerous: rename/drop CHECK enum values without backfill, remove workspace_id scope, merge scores types.

## What Must Be Tested After Modification
- `pytest tests/test_pipeline.py tests/test_gtm_acceptance.py` for domain writes; verify `SELECT * FROM leads` status still in FSM, `scores` tier logic, suppression block.

## Related invariants
- Phone normalization `services/phones.py:9` E.164 before dedupe/comparison.
- Suppression `suppression` table scope email/phone/company/global (`0002_core_schema.sql:313`) hard gate.
- Frontend canonical mirrors DB model for explainability (`frontend/src/gtm/canonical.ts:46` trace.backendModules).
