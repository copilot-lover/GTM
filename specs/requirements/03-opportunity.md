# OPPORTUNITY — Requirements

**Model:** WHO? + WHAT HAPPENING? + WHAT PROBLEM MIGHT EXIST? + WHY ORBIT? + WHY NOW? + WHO TO CONTACT? + EVIDENCE + WHAT NOT TO ASSUME
**Status:** IMPLEMENTED (research + opportunity service) — PARTIALLY wired to GTM lifecycle.

---

## 1. Purpose

Combine business identity, decision maker, signals, evidence, timing, likely problem, relevant Orbit service, previous interactions, contact history, and confidence into a single evidence-based hypothesis that downstream DECIDE cites verbatim.

---

## 2. Inputs

- `companies` (tech_signals, reviews, owner_visibility)
- `contacts` (verified email, verification_provider, notes)
- `hiring_signals` / `job_postings` / `intent_events`
- `leads.website_findings` (pain_points, findings)
- `leads.primary_pain`, `secondary_pain`, `recommended_offer` (if already set)

---

## 3. Responsibilities

| ID | Requirement | Classification |
|----|-------------|----------------|
| OPP-REQ-001 | System SHALL synthesize inputs into `research_reports` row with citations (`evidence[].source_ref + claim`) via `_call_llm_research` (strong tier) with one repair loop on validation failure | IMPLEMENTED `services/research.py:assemble` |
| OPP-REQ-002 | System SHALL compute opportunity 0-100 composite via 6 components: `icp_fit/intent/severity/contactability/recency/history` + tier `A+/A/B/C/D` + EMV `p_reply*p_meeting*value` | IMPLEMENTED `services/opportunity.py:compute` |
| OPP-REQ-003 | System SHALL map strongest pain deterministically via `PAIN_TO_OFFER` hints and `OFFER_CATALOG` check; mismatch → `PipelineError` contract error | IMPLEMENTED `services/pipeline.py:PAIN_TO_OFFER`, `apply_offer:362` |
| OPP-REQ-004 | System SHALL explicitly list `avoid_assumptions[]` (what not to claim) to prevent hallucination downstream | IMPLEMENTED `research.py` `avoid_assumptions`, simulation |
| OPP-REQ-005 | System SHALL provide `GET /api/opportunity/{lead_id}/why` equivalent enriched profile for BOOK handoff packet | PARTIALLY IMPLEMENTED `routers/opportunity.py` exists but shallow; `GET /api/gtm/leads/{id}/why` is primary |
| OPP-REQ-006 | System SHALL fail-closed: no evidence → no hypothesis; low confidence → gate-held | IMPLEMENTED `research._validate_research_report` + `outbound_gate` checks |

---

## 4. Invariants

- Every offer must address recorded primary/secondary pain (hard rule #4).
- Citations must cover claims: `research._validate_research_report` checks `claim → evidence` substring overlap; unsupported → repair or generic fallback (known drift: fallback violates fail-closed if LLM down).

---

## 5. Verification

- `POST /api/pipeline/{lead}/apply/research` flow, `test_gtm_acceptance` research QA
