# Orbit GTM Knowledge System — How to use the docs

> Three layers describe the same underlying reality from different perspectives. They must never drift.

## For a new employee / human operator

1. Open `/explorer` (GTM Explorer) — click any of 12 stages. Start with `Start Learning` (1→12 guided).
2. Read progressively: L1 one-liner → L2 detailed → L3 how it works → L4 ABC HVAC example → L5 advanced.
3. Toggle `ABC HVAC story` to follow one business end-to-end; toggle `Simulation` to see reply variants.
4. Press `/` and ask: “How does qualification work?” “How does Orbit learn?” — relevant stage highlights.
5. Deep dive by folder: `docs/00-overview` through `docs/19-onboarding` (IETM-style: WHAT IS IT? → WHY? → WHAT GOES IN? → WHAT HAPPENS? → DECISIONS → OUT → EXAMPLE → WHAT CAN GO WRONG → EDGE CASES → WHAT NEXT → WHY MATTERS → DEEPER).

## For a developer

1. Read `specs/requirements/00-overview.md` for invariants and change protocol.
2. Per subsystem read `specs/requirements/01-gtm-leads.md`…`10-platform-dialer.md` (MIL-STD-961 style: SHALL with classification, verification, traceability).
3. Before touching code read `agent-docs/XX` for that subsystem: boundaries YOU MAY/MUST NOT, input/output/state contracts, COMMON PITFALLS.
4. State: `docs/12-state-machine/README.md` or `agent-docs/03-state-machine.md` — never write `leads.status` or `messages.gtm_stage` directly.
5. After modify: run checklist in `agent-docs/13-change-protocol.md` step 9.

## For an AI coding agent

1. Start `agent-docs/00-system-map.md` (one page system map).
2. Jump to subsystem doc: `04-gtm-leads`, `05-gtm-intent`, `06-qualification`, `07-opportunity`, `08-outbound`, `09-conversation`, `10-learning`.
3. Read WHAT THIS OWNS / DOES NOT OWN / CONTRACTS / VALID STATES / SAFE vs DANGEROUS / WHAT MUST BE TESTED.
4. Reference `frontend/src/gtm/canonical.ts:76` as canonical content model and `frontend/src/gtm/simulation.ts:46` as expected behavior example.
5. Preserve `specs/invariants/contracts.md` and update `specs/traceability/matrix.md` + drift audit after change.

## Mermaid

- `docs/18-mermaid/diagrams.md` — 10 focused diagrams (overall GTM, 2 brains, lead FSM, message FSM, gate tree, learning loop, layering, conversation sequence, opportunity synthesis, agent boundaries). Treat as documentation, not decoration. Regenerate from `canonical.ts` + `state_machine.py` / `gtm_lifecycle.py`.

## Explorer

- Route `/explorer` (`frontend/src/pages/GtmExplorer.tsx`): system map (table of contents) + node detail (chapter) + onboarding + simulation + decision “Explain why” (non-CoT). See `docs/19-onboarding/EXPLORER_VALIDATION.md`.

## Drift & audit

- `docs/DRIFT_REPORT.md` (code≠docs flagged explicitly) — rerun on every GTM change.
- `docs/QUALITY_AUDIT.md` — second-pass checklist.
- `specs/traceability/matrix.md` — Requirement→Implementation→Test→Human→Agent→Diagram.
