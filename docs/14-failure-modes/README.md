# FAILURE MODES

## Common failures per stage (canonical.ts `whatCanGoWrong`)

- FIND: scraping blocked → silent `[]` fallback; phone not normalized → duplicates
- UNDERSTAND: regex misses SPA booking CTAs; dual write stale
- QUALIFY: threshold drift `/1.8`; two qualification paths diverge
- IDENTIFY: owner_email column drop; rank_title divergence; quota logic inverted for first call
- OPPORTUNITY: circular severity keyword; EMV static; research unbounded rows
- GATE: provider_available stub, limit race, stage tie-break divergence
- OUTREACH: dual queues (messages vs outbound_messages) split reality; schedule_followups without approval-mode check
- RESPONSE: n8n down → replies unclassified; tenant leak on `/events/pending`; kill-switch outbound_messages polling delay
- CONVERSE: no QA on conversational replies; inbound call routing missing
- BOOK: calendar fixture not overridden; no brief generation
- LEARN: closed-loop not wired; budget under-counted

## Recovery

- Every `PipelineError` → `_flag_review` + review queue; never silent skip.
- QA critical → `QA_FAILED` → resubmit until ceiling → `HELD` alert.
- Compliance critical → `COMPLIANCE_FAILED` → `HELD`.
- Bounce >2% → mailbox `health_state` degrade → `pause_on_bounce` via `sending_domains`.
- DNC at any time → immediate `do_not_call` terminal + global suppression + purge from sessions/outbound_messages.

## Human escalation

Spec §6.4 terminal states `rejected, do_not_call, archived` require operator action to reset — no auto win-back from `won`. Review queue via dashboard + Telegram + `GET /api/leads?review_reasons`.
