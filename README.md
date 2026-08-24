# Orbit GTM OS

One-person AI outbound sales operating system for Orbit (Seth's agency selling
AI receptionist / missed-call recovery / booking automation to local home-services
contractors).

Authoritative docs:

- Master spec: `../docs/ORBIT_MASTER_SPEC.md` (Supabase references superseded by the
  implementation constraints below)
- Implementation constraints (authoritative for infrastructure):
  self-hosted VM, PostgreSQL on-VM, n8n orchestration, SMTP email, own dialer.

## Layout

```
orbit/
├── backend/          FastAPI core API (Python 3.12) — lead state machine,
│                     scoring, suppression, approvals, audit. Scrapling-based
│                     scraping service lives in app/services/scraping.py.
├── frontend/         React + Vite + TS + Tailwind dashboard/dialer (Phase 3+)
├── db/migrations/    Numbered SQL migrations applied by scripts/migrate.sh
├── n8n/workflows/    Exported n8n workflow JSONs — version controlled.
│                     n8n holds NO business state; Postgres is the truth.
├── scripts/          migrate.sh, setup_db.sh, backup_db.sh, restore_db.sh
├── deploy/           systemd unit files
├── docs/             RUNBOOK.md, RECOVERY.md, RESOURCE_INDEX.md
└── backups/          DB dumps (gitignored)
```

## Stack decisions

| Concern   | Choice | Why |
|-----------|--------|-----|
| Scraping  | [Scrapling](https://github.com/D4Vinci/Scrapling) | Requested; anti-bot capable fetchers + parsing |
| API       | FastAPI (Python) | Same language as Scrapling + old prospecting pipeline being ported |
| Realtime/services | Node/TypeScript services where needed (dialer signaling) | Split-stack decision |
| DB        | PostgreSQL on VM | Authoritative source of truth |
| Orchestration | n8n (self-hosted) | ALL external work: LLM calls (OpenRouter), Scrapling scraping, SMTP transport, retries, DLQ |
| Event bus | Postgres outbox + LISTEN/NOTIFY | State changes push `orbit_events`; n8n reacts, applies results back |
| Email     | SMTP behind an `EmailProvider` abstraction | Constraints: no Instantly yet |

## Quick start (dev)

```bash
# 1. Provision database (once, needs sudo for extensions)
sudo scripts/setup_db.sh

# 2. Apply migrations
scripts/migrate.sh

# 3. Run API
cd backend && ~/.local/bin/uv run uvicorn app.main:app --port 8100 --reload

# Health check: curl http://127.0.0.1:8100/api/health
```

## Secrets policy

Never commit `.env*`. `.env.example` documents every variable. Backups and logs
are gitignored too.
