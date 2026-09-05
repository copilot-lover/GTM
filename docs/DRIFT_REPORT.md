# CODE / DOCUMENTATION DRIFT AUDIT — 2026-08-31

> Compared ACTUAL CODE (`backend/app/services/*.py`, `routers/*.py`, `db/migrations/0001-0009`, `frontend/src/gtm/*`) against SPEC (`docs/ORBIT_MASTER_SPEC.md`, `specs/requirements/*`), HUMAN docs (`docs/0*`), AGENT docs (`agent-docs/*`), MERMAID (`docs/18-mermaid/diagrams.md`), EXPLORER (`canonical.ts`).

## Method

- Grep `file:line` anchors in every doc must exist (validated via `grep -n`).
- Trace every requirement ID to an implementation file; missing → PLANNED/UNDOCUMENTED/CONFLICTING.
- Compare state machine constants `state_machine.TRANSITIONS` vs `12-state-machine/README.md` vs `agent-docs/03-state-machine.md` vs mermaid.
- Compare invariants lists `specs/invariants/contracts.md` vs code guards.

## Findings

| Category | Status | Details |
|----------|--------|---------|
| CODE > DOCS — implemented but undocumented before this delivery | FIXED | `services/intent_engine.py:268` contributions, `services/outbound_gate.py:96` 13 checks, `services/qa_service.py:177` findings loop — now documented in human + agent docs, canonical.ts, mermaid 5 |
| DOCS > CODE — spec describes but not implemented | FLAGGED | Booking calendar (FR-30) FixtureCalendar not overridden (`docs/10-booking` PLANNED), closed-loop prompt evolution (FR-24) audit_history 24h only, inbox warmup 2-4 wks not enforced |
| CODE ≠ SPEC | CONFLICTING | `ORBIT_MASTER_SPEC.md:supabase` says Lovable Cloud + RLS but `orbit/README.md` constrains to self-hosted VM Postgres on-VM — documented as PROPOSED resolution, not ML compliance claim |
| DIAGRAM ≠ CODE | FIXED | Mermaid now generated from `state_machine.py:6` + `gtm_lifecycle.py:31` vs ad-hoc; validated state counts match |
| AGENT RULE ≠ IMPLEMENTATION | CONFLICTING (known) | `intent_engine._has_tier_a:282` reads `scores.tier` but never written → always null; two qualification paths `pipeline.apply_qualification:new→enriching` vs `routers/leads.score_lead:new→qualified` — both flagged in `canonical.ts:whatCanGoWrong` + `agent-docs/14-common-pitfalls` |
| Duplicate sources | FLAGGED | `OFFER_CATALOG` duplicated 4 places with 8/9/10 sizes; `rank_title` duplicated 5 vs 10 keys; `global_limit` double-count in `services/scheduler.py:155` (perf issue) — all flagged not silently fixed per “No implementation drift” rule |

## No drift (confirmed)

- `services/state_machine.py:6` → `docs/12-state-machine` → `agent-docs/03-state-machine` → `docs/18-mermaid:3` identical 18 states + do_not_call injection
- `services/gtm_lifecycle.py:20` `AUTHORIZED_SEND_STAGES` ↔ `outbound_gate.py:154` ↔ mermaid 4
- `canonical.ts:76` single source ↔ explorer + docs/19-onboarding + human docs (no hardcoded dupe explanations)

## Action

Re-run this audit via `python3 /tmp/run_audit.py` + `grep -R "whatCanGoWrong" orbit/frontend/src/gtm/canonical.ts` after any GTM change. Change protocol `agent-docs/13-change-protocol.md` step 8 requires drift re-check.
