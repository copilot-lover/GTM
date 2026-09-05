# EVALUATION — How GTM is measured

## Funnel

Per `ORBIT_MASTER_SPEC.md §7.3` and `docs/03` intent traps: **FIND → UNDERSTAND → QUALIFY → IDENTIFY → OPPORTUNITY → DECIDE → GATE → OUTREACH → RESPONSE → CONVERSE → BOOK → LEARN**

Instrumentation: `scores`, `hiring_signals`, `activities` (actor human/agent/system), `audit_log`, `agent_runs` (tokens/cost/latency), `provider_usage`.

## Dashboards

- Control Center (`frontend/src/pages/ControlCenter.tsx`): `GET /api/control-plane/overview` systems health (n8n, Twilio, AI, email, queue, AI spend today), today panel, pipeline stages counts.
- Signals Dashboard (`SignalsDashboard.tsx`): intent event feed, P1/P2/P3.
- Agents Dashboard (`AgentsDashboard.tsx`): `GET /api/gtm/agents` + runs `last_status`, `tokens_24h`, `successes/failures_24h`.
- Leads table (`Leads.tsx`): server-side paginated, filters, saved presets.

## Evaluation questions LEARN answers

- Per-vertical/per-source conversion: which FIND source yields qualified→booked?
- Reply rate per signal/angle: hiring-pressure vs booking-angle
- Contact title success: Owner vs Ops Manager
- Gate hold reasons most frequent: which check fails most?
- Mailbox health: `mailbox_health.py:22` 5-factor → daily GTM health audit

## Acceptance criteria (spec v2 §24)

- QA rejection loop, unsupported claim→FAIL, invalid signal→reprioritized no send, compliance failure→CANNOT_SEND, follow-up with unavailable mailbox→HELD no fallback, fresh hot signal→intent rerun→score up, sender rejects non-authorized stage.
