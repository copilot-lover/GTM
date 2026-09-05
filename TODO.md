# TODO

## Weekend of 2026-09-12

- [ ] Vision upgrade for website audit stage (hybrid, audit only)
  - Keep deterministic pass (forms/phones/SSL/TTFB/tech_signals regex) as-is
  - Add screenshot via scrapling StealthyFetcher (supports screenshots)
  - New vision prompt variant: screenshot + deterministic findings + truncated HTML → merged JSON
  - Vision model on OpenRouter free tier (gemini-flash-free class), chain fallback handles rate limits
  - Scope: audit stage only; qualification/enrichment stay text-only
  - Value: catches JS-rendered booking/chat widgets, real cta_quality/mobile_quality judgment, trust signals
  - Watch: `website_score` unknown-rate before/after
