# Gauntlet Workbench — Orbit GTM OS spec verification

## Goal
Verify the implemented system at `/home/ubuntu/GTM/orbit` against `docs/ORBIT_MASTER_SPEC.md`
(§19 acceptance criteria) and the IMPLEMENTATION CONSTRAINTS (production-ready checklist).
Produce a markdown box breakdown in chat.

## Quality bar (concrete, inspectable)
1. Every §19 acceptance criterion mapped to PASS / PARTIAL / FAIL with primary evidence
   (command output, test results, live endpoint behavior) — no adjective verdicts.
2. Every constraints "production ready" item verified with evidence.
3. Backend test suite green (46+ tests, orbit_test isolation).
4. All three services healthy after restart; SPA + API + n8n reachable.
5. Independent fresh-context critic verdicts per workstream (builder never approves own work).

## Non-goals
- No new features beyond spec verification + highest-impact gap fixes.
- No purchases, external deploys, or commits without authorization (local service restarts OK).

## Resource envelope
- This session on the VM; 4 parallel critic workstreams; fix waves as needed.
- End: bar passed, user stops, envelope exhausted, blocked, or 2 waves with no material improvement.

## Workstreams (independent critics)
- WS1: Platform foundation + lead intelligence (spec §19.1–19.2)
- WS2: Outreach + email gates (spec §19.3) + constraints email section
- WS3: Dialer + hiring intent (spec §19.4–19.5)
- WS4: Dashboard/observability + production readiness (spec §19.6–19.7 + constraints checklist)

## Evidence & verdict history
| Wave | WS | Verdict | Largest gap | Fixed |
|---|---|---|---|---|
| (pending) | | | | |

## Stop condition
All four WS critics cite PASS at the mapped-criteria level, or two consecutive waves show no material improvement.

## Wave 1 verdicts (fresh-context critics)
| WS | Verdict | Largest gap |
|---|---|---|
| WS1 foundation/intelligence | FAIL | No pipeline-stage integration tests (offer-pain, gating, review-reasons untested) |
| WS2 outreach/email | FAIL | Idempotency_key unused — duplicate sends possible; dead-letter unreachable; reply endpoint fails open behind LLM; CAN-SPAM lacks physical address |
| WS3 dialer/hiring | FAIL | DNC suppression bypassed by phone reformatting (no normalize/company scope); HVAC dispatcher posting scores 65→nurture, never queued; no DTMF/mic-picker |
| WS4 prod/dashboard | FAIL | No n8n health check; dashboard polls nothing; agent_failures row[0] bug; RECOVERY.md incomplete |

## Wave 2 scope (fix targets)
1 place_call: normalized phone + company-scope suppression · 2 atomic send claim + idempotency key + attempts-based dead-letter · 3 persist reply + kill switch before/regardless of LLM · 4 n8n healthz check + dashboard 30s poll + agent_failures alias fix · 5 physical postal address env · 6 pipeline integration tests · 7 deterministic hiring-intent keyword signals + contact persistence · 8 SendBlocked→409 · 9 expiry-before-select · 10 DTMF keypad + mic picker · 11 RECOVERY.md completeness
