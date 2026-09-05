# BOOKING / HUMAN HANDOFF — Requirements

**Flow:** INTEREST → QUALIFIED CONVERSATION → OPPORTUNITY → BOOKING → PREPARED HUMAN HANDOFF
**Status:** IMPLEMENTED minimal (lead state transitions) — PARTIALLY for real calendar provider, pre-call brief.

---

## 1. Requirements

| ID | Requirement | Classification |
|----|-------------|----------------|
| BOOK-REQ-001 | System SHALL represent booking intent via `qualified_conversation → meeting_booked → meeting_held → proposal → won/lost` transitions | IMPLEMENTED `services/state_machine.py:TRANSITIONS` |
| BOOK-REQ-002 | System SHALL produce handoff packet containing company summary, contact, trigger/signal, likely problem, history, intent, objections, qualification notes, meeting context (THE HUMAN RECEIVES PREPARED OPPORTUNITY) | PARTIALLY IMPLEMENTED `simulation.ts:book` packet modeled; `routers/opportunity.py` shallow |
| BOOK-REQ-003 | System SHALL log meeting records in `meetings` and `opportunities` tables with scheduled_at, timezone, status booked/held/no_show, calendar_link, brief | PLANNED `meetings` migration exists but FixtureCalendar only |
| BOOK-REQ-004 | System SHALL support booking via Cal.com-style embed + pre-call brief generation | PLANNED FixtureCalendar not overridden |
| BOOK-REQ-005 | System SHALL correctly handle BOOKED vs QUALIFIED NOT READY vs NOT A FIT outcomes and route to nurture/suppress/learn respectively | IMPLEMENTED via state machine + `sequences` later detection |

---

## 2. Verification

- `services/state_machine.py` transitions for `meeting_booked`, `won`, `lost`, `archived`
