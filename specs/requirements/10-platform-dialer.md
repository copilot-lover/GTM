# PLATFORM / DIALER — Requirements

**Stack:** React + Vite + TS + Tailwind, WebRTC via Twilio Voice SDK, TwiML conference, health-gated mailboxes.

---

## 1. Responsibilities

| ID | Requirement | Classification |
|----|-------------|----------------|
| PLAT-REQ-001 | System SHALL provide browser power dialer: sessions (filter → ordered queue), sequential dial, floating widget, persistent DTMF keypad, mic picker, ringback tone | IMPLEMENTED `frontend/src/pages/Dialer.tsx`, `routers/dialer.py`, `services/twilio_service.py` |
| PLAT-REQ-002 | System SHALL log `calls` (CallSid idempotent webhook, duration_seconds, recording_url, disposition editable post hoc, CalledAt) | IMPLEMENTED `routers/dialer.py:twilio_webhook` idempotent by CallSid |
| PLAT-REQ-003 | System SHALL enforce dispositions snake_case chips: connected_dm/gk/other, voicemail, busy, no_answer, bad_number, not_interested, do_not_call, callback_requested, appointment_set, dialed | IMPLEMENTED `Dialer.tsx:DISPOSITIONS` |
| PLAT-REQ-004 | System SHALL support calling sessions derived from filters; server-side ordering by queue_order, per-lead last_disposition correlated subquery | IMPLEMENTED `routers/dialer.py:session_queue` |
| PLAT-REQ-005 | System SHALL provide in-process job queue with pools `ai:2,enrichment:2,verification:2,outbound:2,discovery:1,meeting:1` | IMPLEMENTED `services/job_queue.py:WorkerSupervisor`, `config.py:workers_enabled` default false |
| PLAT-REQ-006 | System SHALL guard Twilio webhooks via HMAC-SHA1 signature validation | IMPLEMENTED `routers/dialer.py:50-73` (with ORBIT_ENV=test bypass noted) |
| PLAT-REQ-007 | System SHALL NOT perform outbound sends while Telegram poller/extra scaffolding is inline — event-driven only | IMPLEMENTED `services/telegram.py` lightweight poller log-only MVP |

---

## 2. Verification

- `tests/test_api.py:TestWebhooksIdempotent` dialer webhook idempotency
- Frontend `ProviderDashboard`, `MailboxManager`, `AlertsCenter`
