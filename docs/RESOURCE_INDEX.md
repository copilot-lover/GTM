# Resource Index — where GTM materials map into the project

Everything outside `orbit/` is reference material, not application code.

## prod-assets/prod-rec/
| File | Use |
|---|---|
| `50 N8N PROMPTS.pdf` | Prompt library for building n8n workflow nodes (Phase 2/5/6/7) |
| `Agents.md` | CLAUDE.md behavioral guidelines — merge into repo-level agent instructions |

## raw_resources_extracted/Raw_resources/

### Authoritative behavioral references (port into backend)
| Resource | Maps to |
|---|---|
| `old lead procspecting system/schema.py`, `schema.json` | Canonical lead schema → Phase 1 migrations + Pydantic models |
| `old lead procspecting system/pipeline.py` | Six-stage pipeline logic (fail-closed validation) → backend/app/services |
| `old lead procspecting system/email_verification.py` | Email verification gate → backend email service |
| `old lead procspecting system/prompts/*.md` (search, qualification, enrichment, website-audit, offer-selection, email-personalization) | Agent prompts A1–A6 → backend/app/agents/prompts (Phase 6) |
| `Daddy Dialer - Lovable Prompt.txt` (+ PDF guide) | Dialer module requirements → frontend dialer + Twilio/WebRTC backend (Phase 4) |

### Skills (copy rules & sourcing compliance — used at build time and in prompts)
| Skill | Use |
|---|---|
| `cold-email/SKILL.md` + references + evals | Copy rules: 75-word limit, 4-sentence structure, cadence day 0/3/7/14, banned phrases; eval JSON patterns for agent tests |
| `prospecting/SKILL.md` + references | Sourcing compliance guardrails (no CAPTCHA bypass, lineage requirements), local-SMB qualification signals. Scraping itself = Scrapling via app/services/scraping.py |
| `copywriting/SKILL.md` | Landing-page copy — future website work, not GTM-critical |

### Context / history (read once; superseded decisions inside are noted in spec §20)
| Resource | Status |
|---|---|
| `ai lead gen spec.md` | ICP weights, scoring, offer catalog — port numbers, ignore OpenClaw runtime |
| `Orbit-vs.-GTM-AI-Lead-Gen-Comparison.md` | Hermes rules (4-sentence emails, Telegram approvals, kill switch), priority scoring |
| `Migrate-AI-GTM-to-n8n.md` | 12-workflow breakdown, lead state machine, event-driven agents (HubSpot recs rejected) |
| `The Newbies Guide to Lead Scraping.pdf` | Compliance background; operational scraping = Scrapling adapters |
| `IMG_*.PNG` screenshots | Competitive inspiration only (trygtm.com, agent-carousel); not specs |
