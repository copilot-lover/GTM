# LEARNING LOOP — Requirements

**Loop:** OUTCOME → INTERPRETATION → EVIDENCE → FUTURE ADJUSTMENT
**Status:** IMPLEMENTED foundation (scores history, audit_log, agent_runs) — PLANNED closed-loop prompt evolution.

---

## 1. Inputs

Replies, no-replies, positive/negative, meetings, no-shows, won/lost, wrong ICP, bad contacts, objections, unsubscribes, signal strength, source quality, message performance per variant/angle/source.

Examples:
- High response rate to signal → signal may be valuable
- High interest but low booking → transition may need improvement
- Poor qualification from source → downgrade source
- High positive from role → raise priority for role

---

## 2. Requirements

| ID | Requirement | Classification |
|----|-------------|----------------|
| LEARN-REQ-001 | System SHALL distinguish OBSERVATION vs INTERPRETATION vs LEARNING vs POLICY CHANGE and never silently rewrite behavior on one isolated outcome | IMPLEMENTED spec, `intent_engine.history` 10% weight |
| LEARN-REQ-002 | System SHALL require evidence-based, conservative updates (N observations before change) | PARTIALLY IMPLEMENTED history component present but no N threshold enforced |
| LEARN-REQ-003 | System SHALL support closed-loop email intelligence: outcome tracking, feature extraction, winner analysis, prompt optimization (FR-24) | PLANNED `control-plane/analytics` stub, audit_history 24h |
| LEARN-REQ-004 | System SHALL track per-source/vertical funnel conversion, not just aggregate | PARTIALLY IMPLEMENTED `routers/control_plane.py:overview` funnel |

---

## 3. Safety

Never let one isolated outcome silently rewrite system behavior. Learning is evidence-based and conservative.

---

## 4. Verification

- `routers/control_plane.py` analytics, `agent-docs` learning loop description, ABC HVAC LEARN stage simulation.
