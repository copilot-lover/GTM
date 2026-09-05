# 13 — Change Protocol (9-Step, Must Follow in Order)

Do not skip steps. Every change touches a deterministic contract that downstream gates rely on.

## 1. Read canonical + service(s)
- Open `frontend/src/gtm/canonical.ts:76` GTM_STAGES + `frontend/src/gtm/simulation.ts:46` ABC HVAC walkthrough for affected stage.
- Open primary service file (e.g., `services/pipeline.py:30`, `services/state_machine.py:6`, `services/gtm_lifecycle.py:31`, `services/outbound_gate.py:96`, `services/scoring.py:39`, `services/intent_engine.py:181`, `services/hiring_signals.py:87`, `services/website_intel.py:222`, `services/enrichment.py:144`, `services/research.py:330`, `services/opportunity.py:238`, `services/email_service.py:125`, `services/scheduler.py:397`, `services/qa_service.py:177`, `services/suppression.py:15`).
- Trace backendModules in `canonical.ts:134` for cross-references.

## 2. Map FSM impact
- If leads.status involved: inspect `services/state_machine.py:6` TRANSITIONS + `state_machine.py:33` TERMINAL + `state_machine.py:29` do_not_call injection. Can adding new status/edge break terminal emptiness?
- If messages.gtm_stage involved: inspect `services/gtm_lifecycle.py:31` TRANSITIONS + `gtm_lifecycle.py:20` AUTHORIZED_SEND_STAGES + `outbound_gate.py:154` gate check.
- Decide if migration needed (`db/migrations/` + `schema_migrations` table `tests/conftest.py:31`) or just code. Never add status string not in DB CHECK constraint (`0002_core_schema.sql:57`, `0008_gtm_agents.sql:15`).

## 3. Preserve contracts
- Keep `stage_context → {system,user,required_keys}` and `apply_* → {next, lead_score...}` + `event_outbox` emit (`services/pipeline.py:165`).
- Keep `can_transition → bool` + `transition → bool|409` optimistic `WHERE status=%s RETURNING` (`state_machine.py:40`, `gtm_lifecycle.py:86` IS NOT DISTINCT FROM).
- Keep `can_send → {allowed,reasons,checks[13]}` auditable (`outbound_gate.py:234`).
- Keep `claim_for_send` idempotencyKey replay cache (`email_service.py:130`).
- Keep evidence mandatory, BANNED_PHRASES (`pipeline.py:377`), 75w/4-sentence (`pipeline.py:395`), PAIN_TO_OFFER (`pipeline.py:125`) consistency.
- Do not make backend call LLM; keep `services/pipeline.py:1` layer boundary.

## 4. Make surgical edit
- Touch only requested component; match existing style (AGENTS.md surgical changes).
- If `COMPANY_ENRICHABLE_FIELDS` (`enrichment.py:44`) updated, also update `TARGET_FIELDS` (`enrichment.py:27`) and OFFER_CATALOG (`scoring.py:24`) across all 4 duplicates.
- For phone/email, reuse `services/phones.py:9` normalize_phone and `enrichment._local_prechecks:279` disposable+MX logic, not ad-hoc regex.
- Use `_LEAD_UPDATABLE:46` whitelist for lead writes; `_update_company:54` filter for companies.

## 5. Flag PARTIALLY IMPLEMENTED if incomplete
- Existing gaps to flag: OFFER_CATALOG duplication, enrichment owner_email drop, find_decision_maker missing contact_id link, _has_tier_a dead, provider_available always True, global_limit double count, shadow blind, etc. Add `PARTIALLY IMPLEMENTED` comment and docs note if your change exposes new gap.
- Example: adding new OFFER requires updating 4 places; if only 1 updated, mark PARTIALLY.

## 6. Add / update tests first (or immediately after)
- Add test in appropriate file under `backend/tests/` using `tests/conftest.py:23` fixtures (workspace, make_lead, db_url).
- Follow existing helper patterns `_verified_contact` / `_managed_draft` (`tests/test_gtm_acceptance.py:22`).
- Cover happy path + prohibited transition + missing-data + suppression + reply handling where relevant. See `tests/test_pipeline.py:66` etc.
- Ensure new test fails before fix, passes after.

## 7. Run isolated DB verification
```bash
pytest -q
# or targeted
pytest tests/test_state_machine.py tests/test_pipeline.py tests/test_gtm_acceptance.py tests/test_scoring.py -v
```
- Must run against `orbit_test` (conftest auto). Never against prod.
- Also run `pytest tests/test_email_gates.py tests/test_suppression.py` if gate/suppression touched.
- Check `SELECT * FROM message_stage_events ORDER BY created_at` and `SELECT components FROM scores` manually if needed.

## 8. Verify safety + tenants
- Assert `outbound_gate.can_send` still blocks on missing verification / suppressed / unauthorized stage (`outbound_gate.py:96`).
- Assert `suppression.check` blocks (`suppression.py:15`).
- Assert workspace scoping `WHERE workspace_id=%s` preserved (grep for missing).
- Assert no real send: no provider_message_id set unless `apply_send_result ok true` and dry_run false; tests must use @acme.test domain.
- Check `ORBIT_PHYSICAL_ADDRESS` guard still raises (`email_service.py:59`) and kill_switch still deletes session_leads (`email_service.py:376`).

## 9. Document + simulate
- Update `frontend/src/gtm/canonical.ts:76` trace if backendModules changed (keep frontend ↔ backend drift out).
- Verify simulation `frontend/src/gtm/simulation.ts:46` ABC HVAC still walks stages; if logic changed, update simulation steps but keep tagline consistent.
- Update relevant agent-doc under `orbit/agent-docs/` (00-14) with new file:line references.
- Provide before/after evidence in PR: pytest log + stage_history dump + gate decision JSON.

## Checklist (copy into PR)
- [ ] Canonical + service read, FSM mapped, contracts preserved
- [ ] Surgical diff only (+ flag PARTIALLY if needed)
- [ ] Tests added/updated and pass on orbit_test
- [ ] Safety checks pass (gate, suppression, tenant, dry-run)
- [ ] Simulation/canonical trace updated if needed
- [ ] Agent-doc updated

## Safe vs Dangerous Reminder
- Safe: follow order 1-9, keep diffs surgical, add PARTIALLY flag.
- Dangerous: skip FSM map (step2), skip isolated run (step7), skip safety tenant check (step8).

## What Must Be Tested After Modification
- Per step7: full `pytest -q` plus targeted `tests/test_*` for touched area; assert gate + suppression + workspace scoping.

## Related
- 11-testing.md for fixture/run details.
- 12-safety.md for dry-run/shadow flags.
- 14-common-pitfalls.md for top mistakes checklist before push.
