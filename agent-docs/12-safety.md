# 12 — Safety (No Real Outreach in Tests, Mock SMTP, Fixtures, Dry-Run)

## No Real Outreach in Tests
- **Isolated DB:** `tests/conftest.py:23` forces `POSTGRES_DB=orbit_test`; all tests truncate after (`conftest.py:49` clean_db). Production `orbit` DB never touched when running pytest.
- **Provider fixtures fallback:** `app/providers/job_sources.py` + `app/providers/base.py` Registry returns fixture data when external unavailable; `tests/test_provider_variability.py` validates empty-adapter returns [] silently not crash.
- **No SMTP in tests:** `services/email_service.py:125` claim_for_send returns payload for n8n SMTP node but never dials SMTP itself (spec §10.3 backend deterministic). Tests assert SendBlocked or payload fields, never open socket.
- **Kill switch in tests:** `services/email_service.py:376` tested via direct DB state, not via Twilio webhook.
- **Suppression hard gate:** `services/suppression.py:15` checked even in tests; `tests/test_suppression.py` ensures blocked.

## Mock SMTP / Transport
- **Abstraction:** `services/email_service.py:1` header: EmailProvider abstraction SMTP now, future Instantly/SES/Resend without rewrite. Actual transport done by n8n Send Email node that polls `services/email_service.py:252` `due_sends` where status approved.
- **Idempotency mock:** `email_service.py:130` idempotency_key replay returns cached provider_message_id without re-send. Test by re-calling claim_for_send with same key after apply_send_result provider_message_id set.
- **Fixtures for verification:** `services/enrichment.py:318` waterfall mocked via `registry.get` patched in `tests/test_enrichment_verification.py` to return `VerificationResult valid confidence 0.95` without DNS; `services/pipeline.py:440` verify_email uses `dns.resolver.resolve` mocked to return MX answers.
- **Mailbox health mock:** `services/mailbox_health.py:20` compute_health_score mocked to avoid real bounce events; scheduler capacity uses `sent_today` count not live SMTP.
- **Telegram mock:** `app/services/telegram.py` poller disabled in tests (`config workers_enabled false` `app/config.py:64`).

## Fixtures (safe data)
- `tests/conftest.py:96` `make_lead` creates synthetic "Acme Plumbing" Greensboro NC +336 etc, no real email.
- `tests/test_gtm_acceptance.py:22` `_verified_contact` uses `owner@acme.test` example domain (RFC 2606 reserved, never delivers).
- `services/enrichment.py:264` DISPOSABLE_DOMAINS 22 includes mailinator etc — tests use @acme.test not disposable, but disposable test uses @mailinator.com to assert local precheck fails before quota.
- DNS mock: `enrichment.py:301` disposable check lowercases domain; phone normalization via `services/phones.py:9` tested with "(336) 555-0000" → +13365550000.
- Job sources fixtures: `hiring_signals.py:315` upsert with `source fixture` and `job-{status}-{age}` keys in tests avoids hitting Adzuna/JSearch.

## Dry-Run / Shadow / Approval Modes
**Files:** `app/config.py:24`, `services/scheduler.py:64`, `services/flags.py:15`, `services/outbound_gate.py:197` stub

- **Config:** `outbound_dry_run: true` default (`config.py:25`) + `outbound_allow_real_send: false` (`config.py:26`). When true, `apply_send_result` never hits real SMTP (n8n workflow guards via env).
- **Shadow mode:** `services/scheduler.py:283` `_is_shadow_mode` reads `system_flags shadow_mode` (bool). If true, `assign_mailboxes:352` UPDATE outbound_messages status claimed shadow true, not scheduled — decision logged not sent (gate stage SUPPRESSED/HELD alternative per `canonical.ts:484`).
- **Approval modes:** `scheduler.py:73` `_get_approval_mode` reads `system_flags approval_mode` autonomous|approval|hybrid. Hybrid _needs_approval for A/A+ only (`scheduler.py:80` reads scores tier). Tests set flag via `flags.set_flag`.
- **Global kill switches:** `scheduler.py:35` `_get_kill_switches` reads `kill_switches` JSON blob {pause_all_sending, pause_followups, pause_ai_replies, pause_hiring_campaigns, pause_domain{}, pause_mailbox{}, pause_campaign{}}. Checked in `assign_mailboxes:304` `_is_paused` per message and `outbound_gate` indirectly via health.
- **Provider_available dead check:** `outbound_gate.py:197` always True gives false confidence; real SMTP failure only caught at `apply_send_result:226` record_failure.

## What Must Be Done Before Manual Send
1. Verify `ORBIT_PHYSICAL_ADDRESS` set else `can_spam_signature:59` raises SendBlocked (CAN-SPAM block required).
2. Verify mailbox `daily_send_limit 30` per inbox per spec §7.4, `sending_domains daily_cap 600`, warmup 2-4 weeks before volume (`canonical.ts:567`).
3. Verify human approval: `email_service.approve:71` status pending_approval/drafted + QA_PASSED/SEND_READY, click approve in dashboard or Telegram card (`services/email_service.py:71`), n8n then claims via idempotency.
4. Verify outbound_gate allowed true: `GET /outreach/messages/{id}/send-decision` returns `allowed true, checks 13 passed` (`outbound_gate.py:234`).
5. Confirm kill_switches not paused (`flags.get_flag("kill_switches")` all false).
6. Dry-run first: set shadow_mode true → tick → check assigned count without sent.

## Safe vs Dangerous Changes
- Safe: adding flag pause_mailbox for incident, tuning health multiplier, mocking provider in test.
- Dangerous: flipping `outbound_dry_run` false without warming mailboxes, removing suppression check, setting `outbound_allow_real_send` true in test DB, bypassing approve() to auto-send, deleting shadow guard.

## Safe vs Dangerous Recap
- Safe recap: use orbit_test, mock DNS/provider, shadow_mode true, keep suppression.
- Dangerous recap: bypass claim_for_send, set ORBIT_PHYSICAL_ADDRESS empty, pause kill switch.

## What Must Be Tested After Modification
- `pytest tests/test_email_gates.py tests/test_gtm_acceptance.py::TestComplianceFailureCannotSend`; confirm no production send, gate still blocks unverified.

## Before/After Safety-Critical Change
- Before: review `services/outbound_gate.py:96` + `email_service.py:125` claim gates + `config.py:24` dry-run defaults.
- After: run `pytest tests/test_email_gates.py tests/test_gtm_acceptance.py::TestComplianceFailureCannotSend`; manually query `SELECT * FROM system_flags WHERE key='kill_switches'` and `SELECT gtm_stage, status FROM messages`; confirm no message reached status sent in orbit_test.

## Pitfalls Flagged PARTIALLY
- Shadow mode JSON blob concurrent writes race (no row-level lock).
- Mailbox daily caps 20-30 per inbox not enforced in send path despite spec (scheduler caps but email_service followup creates approved directly).
- DNS MX check `enrichment.py:307` resolver may timeout 30s and not fail-closed quickly in test (mock required).

## Real file:line anchors (use to verify)
- Gate hard blocks real send: `services/outbound_gate.py:96` can_send + `services/email_service.py:125` claim_for_send (idempotency) + `services/pipeline.py:432` gtm_lifecycle.transition_message NULL→QA_PENDING enrollment.
- Suppression: `services/suppression.py:15` check enforced in gate `services/outbound_gate.py:120` and compliance `services/qa_service.py:263`.
- Config dry-run: `app/config.py:24` outbound_dry_run, `frontend/src/gtm/canonical.ts:76` stages trace, `services/scheduler.py:64` _is_shadow_mode.

## Related
- Testing doc 11: isolated DB ensures prod not touched.
- Change protocol doc 13: step 9 verify kill switch still fires.
