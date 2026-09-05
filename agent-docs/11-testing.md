# 11 — Testing (How to Verify: pytest, Test Files, Isolated DB, Fixtures)

## How to Run
```bash
# from orbit/backend
python -m pytest -q
python -m pytest tests/test_state_machine.py tests/test_pipeline.py -v
python -m pytest tests/test_gtm_acceptance.py -k QARejection -v
python -m pytest -k "intent or hiring" --tb=short
```
Config: `backend/pytest.ini:1` `pythonpath = . tests`. Env: `.env` → `POSTGRES_*`; `tests/conftest.py:17` switches to `orbit_test` DB via `POSTGRES_DB=orbit_test`.

## Isolated DB
**File:** `tests/conftest.py:23` `applied_migrations` session fixture:
- Reads `backend/.env` for POSTGRES_HOST/PORT/USER/PASS (`conftest.py:11`).
- Sets `os.environ["POSTGRES_DB"]="orbit_test"` + `get_settings.cache_clear()` (`conftest.py:29`).
- Creates `schema_migrations` if not exists, loops `db/migrations/*.sql` sorted, INSERT if not done, executes file text, INSERT migration row (`conftest.py:34`).
- Sets `ORBIT_TEST_DB` env.

`clean_db:49` truncates all public tables CASCADE between tests (keep schema). Returns DB clean each test; no cross-test leak.

`_reset_rate_limiter:65` clears `RateLimitMiddleware._hits` per test.

## Fixtures
- `workspace:78` → (workspace_id, user_id) inserts workspaces + users + workspace_members owner. Return str ids.
- `make_lead:96` → helper `make_lead(db_url, workspace_id, name, city, state, phone)` inserts companies (phone) + leads (company_id) returns lead_id str. Used everywhere.
- `db_url:73` → TEST_DB_URL string.

Helper pattern in tests: `_verified_contact` inserts contacts `email_verification_status` `verified/dns_ok` etc and links leads.contact_id (`tests/test_gtm_acceptance.py:22`); `_managed_draft:37` inserts messages pending_approval then QA_PENDING transition; `_insert_signal:91` hiring_signals fixture.

## Test Files Inventory
| File | Covers |
|------|--------|
| `tests/test_state_machine.py:6` | lead FSM happy_path, cannot skip, kill_switch reachable, terminal, transition guard optimistic, 409 |
| `tests/test_state_transitions_comprehensive.py` | exhaustive matrix |
| `tests/test_pipeline.py:66` | qualification scoring + events, enrichment gating, offer pain contract, draft QA (75w, banned, 4 sentences), context prompts, unverified gate |
| `tests/test_scoring.py:11` | icp_fit 0-10, thresholds, priority weights, hiring intent very_high, clamped |
| `tests/test_gtm_acceptance.py:112` | QA rejection→resubmit→pass, unsupported claim blocks send, expired signal fails QA, stale signal decay, compliance cannot send, followup mailbox held, fresh hot reprioritizes+cools, structural gates invalid jump/unauthorized stage/registry/unknown event, scheduler+ledger, retry ceiling held, followups structurally enrolled, QA sweep advances |
| `tests/test_email_gates.py` | outbound_gate 13 checks parity + claim_for_send parity |
| `tests/test_suppression.py` | suppression global/email/phone/company blocking |
| `tests/test_hiring_signals.py` | classify_role, compute_signal_score, dedupe 0.9 fuzzy, expiry alerts |
| `tests/test_opportunity_research.py` | _assemble_evidence, fallback research, validate/repair, compute_opportunity_score tier |
| `tests/test_scheduler_outreach.py` | tick capacity health multiplier, allocation caps, assign mailbox ratio, business hours |
| `tests/test_api.py` | HTTP endpoints including /pipeline/context/apply, /outreach/claim, /gtm/* |
| `tests/test_control_plane.py` | agent registry permissions, scheduler ensure_default |
| `tests/test_e2e_acceptance.py` | end-to-end (if present) |
| `tests/test_json_contracts.py` | prompt JSON keys required per stage |
| `tests/test_provider_variability.py` | provider fixtures fallback |
| `tests/test_enrichment_verification.py` | waterfall, DISPOSABLE_DOMAINS 22, MX check, confidence |
| `tests/test_workers.py` | job_queue pools |

## Patterns to Follow When Adding Test
- Use `make_lead` + `psycopg.connect(db_url, autocommit=True)` raw SQL setup; assert via direct SQL fetch before/after service call.
- For stage machine, assert `can_transition` booleans and `transition` optimistic second call False, invalid raises HTTPException 409 (`test_state_machine.py:42`).
- For pipeline, construct `parsed` dict matching `STAGE_KEYS:154` and assert `fit_status`, `next`, `event_outbox` event_type, `review_reasons` JSON.
- For gate, create message via INSERT + `gtm_lifecycle.transition_message` to desired stage, set `status=approved`, then call `outbound_gate.can_send` assert checks dict; also assert `email_service.claim_for_send` raises SendBlocked on failure and resets status to approved (not sending).
- Always assert DB row after service: `leads.priority_score`, `scores.components`, `qa_runs.failed_rules`, `messages.gtm_stage`, `activities` row exists.
- Mock external: patch `registry.get` or `dns.resolver.resolve` to avoid network; use fixture providers; never hit real SMTP (see 12-safety).

## What Must Be Tested After Modification
- FSM change → `test_state_machine.py` + `test_state_transitions_comprehensive.py`.
- Scoring weight/threshold change → `test_scoring.py` + `test_pipeline.py::TestQualificationApply`.
- Pipeline stage logic → `test_pipeline.py` all classes.
- QA/gate → `test_gtm_acceptance.py` + `test_email_gates.py`.
- Intent decay → `test_gtm_acceptance.py::TestFreshHotSignalReprioritizes` + `TestInvalidSignalInvalidates`.
- Scheduler/mailbox → `test_scheduler_outreach.py`.
- Suppression → `test_suppression.py`.
- New provider → `test_provider_variability.py` + `test_enrichment_verification.py`.

## Examples
- Qualification test (`test_pipeline.py:67`): lead new + signals single_location etc → `apply_qualification` → fit_status qualified next enrichment, leads status enriching, event enrichment_requested.
- QA sweep test (`test_gtm_acceptance.py:588`): managed draft QA_PENDING + verified contact → `job_queue._HANDLERS[("ai","gtm_qa_audit")]` returns audited≥1 copy_passed≥1 compliance_passed≥1 failed 0 and stage SEND_READY.
- Mailbox mismatch test (`test_gtm_acceptance.py:289`): followup mailbox b != original a → gate allowed false followup_mailbox_correct failed detail contains a, transition to HELD history last actor gatekeeper.

## Safe vs Dangerous (testing)
- Safe: add fixture helper, extend isolation truncate list, add mock provider.
- Dangerous: use prod DB URL, leak workspace_id, run real SMTP in CI.

## What Must Be Tested After Modification (already described above — see "What Must Be Tested After Modification")

## Real file:line anchors (use to verify)
- FSM: `services/state_machine.py:40` transition(), `services/state_machine.py:6` TRANSITIONS, `services/gtm_lifecycle.py:59` transition_message() — exercised by `tests/test_state_machine.py:6`.
- Pipeline: `services/pipeline.py:30` _load_lead, `services/pipeline.py:240` apply_qualification, `services/pipeline.py:384` apply_draft — covered by `tests/test_pipeline.py:66`.
- Gate: `services/outbound_gate.py:96` can_send 13 checks, `services/email_service.py:125` claim_for_send — covered by `tests/test_email_gates.py`, `tests/test_gtm_acceptance.py:112`.
- Frontend canonical trace: `frontend/src/gtm/canonical.ts:76` GTM_STAGES source of truth mirrored in tests via why-panel.

## Related
- Fixtures rely on `app/config.py:94` get_settings cache_clear after POSTGRES_DB switch — do not cache connection string elsewhere.
- Migrations must run before tests; if adding migration, name sequentially (0009...) and idempotent ON CONFLICT.
