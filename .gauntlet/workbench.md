# Gauntlet Workbench — Hands-Off Prod Ready (API Keys + Warmed Inboxes → Approvals Only)

## Goal
Make Orbit GTM truly hands-off after onboarding: operator connects API keys (OpenRouter, Apollo/Hunter, ZeroBounce) + warmed inboxes/domains + Telegram, then system runs indefinitely with **zero touch except approvals**. No manual restarts, no stub ingestion, no duplicate sends, no silent failures.

## Constraints
- Preserve existing interfaces: `app/services/scheduler.py:397` tick(), `app/config.py:25`ApprovalMode, `n8n` workflows externalize via `ORBIT_SERVICE_TOKEN`
- Never weaken tests or relax `outbound_gate`/`suppression` hard gates
- No real outbound in tests (fixtures only)
- Resilience first: retries, DLQ, idempotency

## Non-Goals
- Not building new GTM stages or UI redesign
- Not billing / multi-tenant pricing
- Not parallel dialer

## References
- Master spec: `docs/ORBIT_MASTER_SPEC.md:560` 10.3 n8n owns I/O, 7.4 warmup caps
- Contracts: `.gauntlet/contracts.md` (0005-0007 tables + provider protocols)
- Scheduler: `orbit/backend/app/services/scheduler.py:105` get_daily_capacity, `207` next_available_slot, `281` assign_mailboxes
- n8n: `orbit/n8n/workflows/lead-intelligence.json:1`, `email-transport.json:1`, `lead-ingestion.json:12`,`daily-gtm-health-audit.json:1`
- Tests: `orbit/backend/tests/*` 279 passed

## Evidence Required
- `pytest -q` 279+ pass, `npm run build` 86 modules
- Notebook-style proof: slot distribution histogram + inbox assignment weighted random test
- n8n workflow JSON diff + execution receipt (retry/DLQ visible)
- `GET /api/gtm/explorer` + `GET /control-plane/overview` health

## Quality Bar (inspectable, not adjectives)
1. **Scheduler randomization** — `next_available_slot` jitter spreads across full `window_start-window_end` (not just early 5-50min), `assign_mailboxes` uses weighted random among `remaining>0` with same-ratio shuffle; verified by 1000-slot histogram (stddev < 15% of window) and 1000-assign distribution (chi-square uniform p>0.05)
2. **Capacity correctness** — `global_limit` = sum(domain_cap) once per domain, not per mailbox; verified by unit test with 2 domains × 3 mailboxes
3. **n8n lead ingestion not stub** — `lead-ingestion.json` returns non-empty `candidates` via deterministic seed or fails loud with Telegram alert; not `candidates:[]`
4. **Email transport + dialer idempotency/retries/DLQ** — duplicate `Authorization` header fixed, `retryOnFail 3` on every external POST, error branch reports to `/apply/send-result?ok=false` and `alerts` table; dialer dedupes by `idempotency_key` date-salted (no duplicate morning session)
5. **Hands-off health** — `daily-gtm-health-audit` `retryOnFail 2` + `onError:continueRegularOutput` on Telegram, `daily-digest-health` wired to Telegram not console.log

## Resource Envelope
- Tokens: unlimited (user granted)
- Time: overnight, ~5 waves
- Parallel builders: up to 3

## Stop Condition
End when bar 1-5 all PASS with independent critic evidence, or 2 consecutive waves show no material improvement, or user stops.

## Workstreams
- **WS-A Scheduler Randomization** — inbox weighted random + full-window time jitter + capacity fix (owner: builder-a, critic-a)
- **WS-B n8n Lead Ingestion** — replace stub with seeded adapter + validation + alert (builder-b, critic-b)
- **WS-C Email/Dialer Reliability** — fix duplicate Auth header, DLQ/idempotency, duplicate session guard (builder-c, critic-c)

## Verdict History
- WS-A Scheduler Randomization — `PASS` (critic-a independent fresh context)
- WS-B n8n Lead Ingestion — `PASS` (critic-b independent fresh context)
- WS-C Email/Dialer Reliability — `PASS` (critic-c independent fresh context)

## Active Gap
None — all 5 quality bar items verified with independent critic evidence.

## Evidence
- `.gauntlet/evidence/ws-a-slot-hist.json` + `.console.txt` (1000 slots, stddev 11.9% < 15%)
- `.gauntlet/evidence/ws-a-assign-dist.json` + `.console.txt` (1000 assigns, chi-square 1.65 p>0.05)
- `.gauntlet/evidence/ws-a-capacity.json` + `.console.txt` (2×3 mailboxes, global_limit 1200)
- `.gauntlet/evidence/ws-b-validation.json` + `.console.txt` (5 deterministic HVACs, alert paths wired)
- `.gauntlet/evidence/ws-b-execution-simulation.log` (full trace)
- `.gauntlet/evidence/ws-c-validation-receipt.json` + diffs (all 4 criteria)
- `.gauntlet/evidence/ws-c-summary.md` (human receipt)

## Final Status
`COMPLETE` — All 5 quality bar items PASS with independent critic evidence. System ready for API keys + warmed inboxes → approvals only.
