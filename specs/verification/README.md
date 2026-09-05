# VERIFICATION — How each requirement is tested

## Harnesses

- `backend/tests/` — `pytest` isolated `orbit_test` DB (`conftest.py:23`), recycles schema per test
- `frontend` — `tsc -b` + `vite build` (Explorer: 86 modules OK)
- `n8n` dry-run: `GET /api/pipeline/{lead}/context/{stage}` returns `system+user+required_keys` JSON for LLM, no real send
- Synthetic prospect `ABC HVAC` (`frontend/src/gtm/simulation.ts:46`) end-to-end

## Per-requirement verification

| Requirement | Test file:line | Scenario |
|-------------|----------------|----------|
| ICP 0-10 math | `tests/test_scoring.py` | 0,6,10 edge, /1.8 rounding |
| Priority tiers P1-P4 | `tests/test_scoring.py:priority_tier` | 85,65,40 thresholds |
| Offer-pain contract | `tests/test_pipeline_integration.py` | mismatch → PipelineError |
| Email gates verified required | `tests/test_email_gates.py` | syntax_ok not enough, verified blocks send |
| Kill switch before LLM durable | `tests/test_gtm_acceptance.py` durable reply | pause before classify |
| Outreach_ready gate both directions | `tests/test_gtm_acceptance` | approved↔blocked regression |
| QA rejection→rewrite→PASS, ceiling→HELD | `tests/test_gtm_acceptance.py` 12 scenarios §24 | `resubmit_copy` loop |
| Invalid signal invalidated | `tests/test_gtm_acceptance` | hiring_signals expired → WRONG_SIGNAL |

## Running

```bash
uv run pytest backend/tests/ -q   # baseline 195+ pass, 1 skipped expected
npm --prefix frontend run build    # Explorer must build
curl http://127.0.0.1:8100/api/gtm/leads/{id}/why | jq .contributions
```
