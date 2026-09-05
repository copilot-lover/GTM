# DECISION RULES — Observable decision basis (never hidden chain-of-thought)

---

## 1. Philosophy

Orbit exposes *evidence + factors + rules + confidence + relevant state* — not model internal reasoning. Every “Explain why” panel cites checkable outputs: `outbound_gate.checks[]`, `scores.components.contributions[]`, `qa_runs.findings[]`, `hiring_signals`.

---

## 2. Key gates

### ICP fit (scoring.py)
`total = sum(+2..+3 per positive signal) + sum(-3..-4 per negative); score = clamp(round(total/1.8),0,10); threshold 6`

### Priority (scoring.py + intent_engine.py)
`priority = round((0.4*intent +0.3*fit +0.2*contact +0.1*history)*100)` → tier `P1 85-100 speed-to-lead, P2 65-84, P3 40-64, P4 <40 nurture`
`intent_engine.reevaluate` alternative: `base_icp*10 + sum(signal_contrib*recency) + count_bonus` with `MAX_SIGNAL_CONTRIBUTION=35`, `recency=1-age/30`

### Outbound gate (13 checks)
See `specs/requirements/04-outbound-gate.md`. Each check records `{name, passed, detail}` — `GET /api/outreach/messages/{id}/send-decision`.

### QA

Deterministic: word_count≥75 → `GENERIC_COPY` critical, banned_phrases hit → critical, 4-sentence violation → warning, claim without `evidence_refs` → `UNSUPPORTED_FACT` critical, expired signal → `WRONG_SIGNAL`, opted_out/suppressed/unverified → `COMPLIANCE_FAILURE`.

---

## 3. Example: Why ABC HVAC qualified?

ICP strong (HVAC, 3 areas, local, owner-visible) + Need strong (dispatcher + ads + weak booking) + Timing medium-high (hiring 3d fresh) + Contact verified (Apollo→ZeroBounce) + Service AI receptionist matches pain → medium-high confidence → HIGH-VALUE FIT (priority 78 P1). Evidence cites posting URL + website audit screenshot hashes, all auditable.
