# GTM Explorer — Validation

**Route:** `/explorer` (`frontend/src/pages/GtmExplorer.tsx` + `frontend/src/gtm/canonical.ts` + `frontend/src/gtm/simulation.ts`)
**Build:** `vite build 86 modules, 604 kB` OK, `tsc -b` 0 errors (2026-08-31).
**Canonical model:** `GTM_STAGES:12` + `GTM_BRAINS:2` + `GTM_PRINCIPLES:7` — single source powers map, lessons, onboarding, simulation, search, mermaid.

## Required interactions — all present

| Requirement | Where | Evidence |
|-------------|-------|----------|
| System map FIND→LEARN 12 stages clickable | `GtmExplorer.tsx:170-196` `.map GTM_STAGES` button `openStage` | Each node `min-w-[110px]` with `index→title` |
| Click opens detailed learning surface with 11 sections | `GtmExplorer.tsx:288-394` `DetailSection`drawer `whatItIs…whyItMatters` + `GTM_DECISION_TRANSPARENCY` | 5 depth levels `L1..L5` via `depth` state |
| Progressive disclosure 5 levels | `GtmExplorer.tsx:298-302` `{depth>=0..3}` | L1 one-liner → L5 advanced trace |
| Explain why | `GtmExplorer.tsx:373-382` `DECISION TRANSPARENCY` + `GTM_DECISION_TRANSPARENCY.example` | Cites `outbound_gate.checks[]`, `scores.contributions[]`, `qa_runs` |
| Prospect simulation ABC HVAC end-to-end | `simulation.ts:46` `ABC_HVAC_SIMULATION:12` + `SIMULATION_VARIANTS:6` + `GtmExplorer.tsx:216-276` table + per-stage `activeSimulationStep` | Each row: Knows/Doesn't, Signal, Interpretation, Decision, Why, PassedForward + 3 conversation turns |
| Learn Mode guided onboarding | `GtmExplorer.tsx:57-82` `learnMode, learnIdx, startLearn/learnNext/learnPrev/exitLearn` + `GtmExplorer.tsx:396-404` bottom bar | NEXT/BACK/SKIP/Explore freely, `progressPct` |
| Search semantic discovery | `GtmExplorer.tsx:20-24` `searchStages(query)` over all fields + `query` input `placeholder "qualification, intent..."` + `filteredIds` highlight | Handles “How does qualification work?” etc |
| Map is table of contents, drawer is chapter | `GtmExplorer.tsx:214` + `GtmExplorer.tsx:288` fixed drawer `w-[640px]` keeps map visible | — |
| Canonical drift prevention | `canonical.ts:1` comment single source powers SYSTEM MAP + LESSONS + ONBOARDING + SIMULATION + SEARCH | mermaid generated from same `GTM_STAGE_IDS` |

## How to use

1. Open `/explorer`, click `FIND` — drawer opens level 1, bump to 3 for “How it works”.
2. Press `/` then type “hiring intent” — map highlights UNDERSTAND, QUALIFY, OPPORTUNITY.
3. Click `Start Learning` — walks 1→12 with progress dot; Back/Skip at any time.
4. Toggle `ABC HVAC story` — purple dots on 12 stages, strip shows `Maria Chen` profile, table row click jumps to stage.
5. Click `Why?` in any QUALIFIED example — see `ICP fit: strong… Need: strong… Timing: medium-high → worth contacting`.

## Archify complements (not replaced)

- `orbit-gtm-os.html` — 13-component system architecture diagram (Archify 2.16, dark/light, 3 presets)
- `gtm-flow.html` — GTM flow workflow (6 panels)
- `orbit-gtm-userflow.html` — user journey

Explorer is the *teachable manual*; Archify is the *implementation topography* — intentional separation per prompt “Do NOT force Archify to perform functions it is poorly suited for.”
