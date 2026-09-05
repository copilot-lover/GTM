# Orbit GTM OS — Requirements Overview (Layer 1)

**Design influence:** MIL-STD-961 style. Not claimed as formally compliant.
**Source of truth:** Repository at `orbit/` — code > docs. If conflict, code governs and docs flag CONFLICTING.
**Version:** spec v2 + v3 (signal-driven engine, agent boundaries, independent QA)
**Date:** 2026-08-31
**Classification legend:** `IMPLEMENTED` | `PARTIALLY IMPLEMENTED` | `PLANNED` | `UNIMPLEMENTED` | `CONFLICTING` | `DEPRECATED`

---

## 1. Purpose

Orbit GTM OS is a one-person outbound sales operating system for Orbit (AI receptionist / missed-call recovery / booking automation sold to small, local, owner-operated home-services contractors: plumbers, HVAC, electricians, roofers).

It sources and qualifies leads against a strict ICP, detects timing signals (especially hiring for receptionist-like roles), drafts evidence-based outreach, gates sends deterministically, executes a behavior-reactive cadence, classifies replies, books meetings with a prepared handoff, and learns from outcomes.

---

## 2. Scope

Included:
- `orbit/backend` FastAPI core (lead state machine, scoring arithmetic, suppression, approvals, audit)
- `orbit/frontend` React/Vite/Tailwind dashboard + WebRTC dialer
- `orbit/db/migrations` 0001-0009 numbered SQL migrations; `scripts/migrate.sh` + `app/main.py:run_migrations` dual path
- `orbit/n8n/workflows` exported workflow JSONs — orchestration only, no business state
- Postgres outbox + `LISTEN orbit_events` event bus
- Deterministic QA layer, hard outbound gate, GTM message lifecycle FSM, intent engine

Explicitly out of scope (v1):
- Autonomous sending without human approval (hybrid mode only as configured)
- LinkedIn automation, cold SMS default channel, multi-line parallel dialing
- External CRM as system of record (HubSpot dropped per `ORBIT_MASTER_SPEC.md`)

---

## 3. Requirement ID scheme

```
GTM-XXX-NNN  (e.g., LEAD-REQ-001, INTENT-REQ-003, GATE-REQ-010)
```

Each requirement: Responsibility | Preconditions | Inputs | Functional requirement | Decision criteria | Outputs | State change | Interfaces | Invariants | Failure | Verification | Traceability.

---

## 4. Subsystem map

| Subsystem | Doc | Code |
|-----------|-----|------|
| GTM Leads (who to pursue) | `specs/requirements/01-gtm-leads.md` | `services/pipeline.py`, `services/scoring.py`, `services/enrichment.py`, `routers/leads.py` |
| GTM Intent (what is happening) | `specs/requirements/02-gtm-intent.md` | `services/hiring_signals.py`, `services/intent_engine.py`, `services/website_intel.py` |
| Opportunity | `specs/requirements/03-opportunity.md` | `services/research.py`, `services/opportunity.py`, `routers/opportunity.py` |
| Outbound gate | `specs/requirements/04-outbound-gate.md` | `services/outbound_gate.py`, `services/gtm_lifecycle.py` |
| Outreach / sequence | `specs/requirements/05-outreach.md` | `services/email_service.py`, `services/scheduler.py`, `services/sequences.py` |
| Response / conversation | `specs/requirements/06-response-conversation.md` | `services/sequences.py`, `routers/outreach.py` classify |
| Booking / handoff | `specs/requirements/07-booking.md` | `routers/leads.py` transitions, `services/opportunity.py` EMV |
| Learning loop | `specs/requirements/08-learning.md` | `services/intent_engine.py` history, `routers/control_plane.py` |
| State machines | `specs/requirements/09-state-machines.md` | `services/state_machine.py`, `services/gtm_lifecycle.py` |
| Platform / dialer | `specs/requirements/10-platform-dialer.md` | `routers/dialer.py`, `services/twilio_service.py` |

---

## 5. Global invariants (SHALL)

| ID | Invariant | Enforcement |
|----|-----------|-------------|
| INV-001 | Postgres is system of record; n8n never owns lead/message state | code: `PIPELINE` docstring `services/pipeline.py:1`, tests |
| INV-002 | No send without human approval (v1 hybrid) | `services/email_service.py:approve` → `claim_for_send` checks `outbound_gate.can_send` |
| INV-003 | Suppressed / opted-out / do_not_call never enters send path | `services/suppression.py` + `outbound_gate` checks `not_suppressed` + `contact_eligible` |
| INV-004 | `leads.status` only via `services/state_machine.py:transition` optimistic guard | `state_machine.TRANSITIONS` |
| INV-005 | `messages.gtm_stage` only via `services/gtm_lifecycle.py:transition_message` | `gtm_lifecycle.TRANSITIONS`, `AUTHORIZED_SEND_STAGES` |
| INV-006 | Backend never calls LLM directly (spec §10.3) | `services/pipeline.py:stage_context` returns prompt for n8n; `services/llm.py` stub only |
| INV-007 | Evidence before action: every qualification / audit / offer cites evidence text | `pipeline.apply_*` mandatory evidence fields + `qa_service.UNSUPPORTED_FACT` |
| INV-008 | Idempotency on all external effects | `send_attempts`, `calls.CallSid`, `messages` idempotency keys, session_leads PK |

---

## 6. Traceability matrix

See `specs/traceability/matrix.md` linking Requirement → Implementation file:line → Test file → Human doc → Agent doc → Mermaid diagram. Any `PLANNED` requirement shows missing implementation row.

---

## 7. Verification strategy

Each requirement lists a concrete verification in `specs/verification/`. Primary harnesses: `backend/tests/` (195 tests claimed), `scripts/migrate.sh` idempotency, `frontend` `vite build` + `tsc --noEmit`, n8n dry-run fixtures, synthetic prospect ABC HVAC.

---

## 8. Terminology (per `ORBIT_MASTER_SPEC.md` §3-4)

- **FACT** — observed business data (website text, posting URL, review count)
- **INFERENCE** — interpreted meaning (hiring dispatcher → call pressure)
- **OPPORTUNITY HYPOTHESIS** — reasoned profile combining WHO + WHAT HAPPENING + PROBLEM + WHY ORBIT + WHY NOW + WHO TO CONTACT + EVIDENCE + WHAT NOT TO ASSUME
- **SIGNAL** — detectable business change (hiring, ads, expansion) distinguishable from **OPPORTUNITY**

Do not treat a detected signal as qualified opportunity until GATE judges.

---

## 9. Change protocol

When GTM changes materially: 1 inspect implementation → 2 update spec → 3 human docs → 4 agent docs → 5 mermaid → 6 explorer (canonical.ts) → 7 examples → 8 tests/traceability → 9 drift audit. See `agent-docs/13-change-protocol.md`.

---

## 10. References

- Master spec: `docs/ORBIT_MASTER_SPEC.md` (version 1.0-draft, reconciles two architectural visions)
- Implementation constraints: `orbit/README.md` (self-hosted VM, Postgres on-VM, n8n, SMTP)
- Canonical content model: `orbit/frontend/src/gtm/canonical.ts` (12 stages + 2 brains + 7 principles)
- Simulation: `orbit/frontend/src/gtm/simulation.ts` (ABC HVAC end-to-end)
