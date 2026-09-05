# Event Interfaces — `orbit_events` (Postgres outbox + LISTEN/NOTIFY)

**Table:** `orbit_events` (audit trail) + `pg_notify('orbit_events', json)` — n8n `LISTEN` workflow `event trigger on orbit_events`

---

## 1. Emit

```
events.emit(conn, event_type: str, payload: dict, workspace_id: str | None) -> str id
```

Implementation `services/events.py:1`: single INSERT + pg_notify, short-lived connection.

---

## 2. Pipeline chain

```
lead.qualification_requested  -> n8n: fetch /pipeline/{id}/context/qualification + scrape -> POST /pipeline/{id}/apply/qualification
lead.enrichment_requested     -> n8n: context/enrichment + scrape          -> POST /apply/enrichment
lead.audit_requested          -> n8n: context/audit + scrape                -> POST /apply/audit
lead.offer_requested          -> n8n: context/offer                         -> POST /apply/offer
lead.draft_requested          -> n8n: context/draft                         -> POST /apply/draft -> creates messages QA_PENDING
```

Each `apply_*` in `services/pipeline.py` emits the next event deterministically.

---

## 3. Intent

```
intent_events ingestion -> job_queue.enqueue gtm_intent_process idempotency intent-process-{id} -> process_pending_events SKIP LOCKED claim -> reevaluate_lead per company/lead
```

---

## 4. Outreach

```
message created pending_approval -> gtm_lifecycle DISCOVERED..QA_PENDING -> GTM_QA sweep (900s/3600s via agents/scheduler) -> QA_PASSED -> COMPLIANCE_PENDING -> SEND_READY -> scheduler tick -> claim_for_send -> SENT
reply received -> kill_switch -> cancel outbound_messages + delete session_leads + alert
```

---

## 5. Dialer

```
POST /dialer/calls -> twilio_service.place_call -> TwiML conference -> POST /dialer/twilio-webhook (CallSid idempotent) -> calls record -> set_disposition
```

---

## 6. Contract invariants

- Backend never produces LLM JSON; n8n fetches `stage_context` then calls LLM/scrape.
- All external-effects carry idempotency (`send_attempts`, `CallSid`).
- Workspace scoping required on consumer: verify `payload.workspace_id` matches `GET`.
