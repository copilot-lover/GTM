# Runbook — daily operation

## Services

| Service | How it runs | Port |
|---|---|---|
| PostgreSQL 12 | systemd (`postgresql`) | 5432 |
| Orbit API (FastAPI) | `deploy/orbit-api.service` | 8100 |
| n8n | `deploy/orbit-n8n.service` | 5678 |

### Install services after a fresh checkout

```bash
sudo cp deploy/orbit-api.service deploy/orbit-n8n.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now postgresql orbit-api orbit-n8n
```

## Common operations

```bash
# Tests (uses isolated orbit_test DB; provision once: see setup_db.sh)
sudo -u postgres psql -c "ALTER ROLE orbit CREATEDB;"
cd backend && ~/.local/bin/uv run pytest tests/

# Provision test database (once)
sudo -u postgres createdb -O orbit orbit_test
sudo -u postgres psql -d orbit_test -c "CREATE EXTENSION IF NOT EXISTS pgcrypto; CREATE EXTENSION IF NOT EXISTS citext;"

# Health
curl http://127.0.0.1:8100/api/health
systemctl status postgresql orbit-api orbit-n8n --no-pager

# Apply new migrations (after pulling)
scripts/migrate.sh

# Manual backup / restore
scripts/backup_db.sh
scripts/restore_db.sh backups/<file>.sql.gz

# API logs
journalctl -u orbit-api -f

# Frontend: edit in frontend/, then rebuild (API serves frontend/dist)
cd frontend && npm run build

# n8n workflows are edited in the UI, then exported to n8n/workflows/ and committed.
```

## Service tokens for n8n

n8n workflows authenticate to the API with a service user's JWT
(`ORBIT_SERVICE_TOKEN` env var in n8n). Create a dedicated operator account for
automation rather than reusing Seth's login.

## Nightly backups

Crontab entry (installed on VM):

```
15 3 * * * /home/ubuntu/GTM/orbit/scripts/backup_db.sh >> /home/ubuntu/GTM/orbit/backups/backup.log 2>&1
```

Retention: last 14 dumps.

## Scraping

All scraping goes through Scrapling via the backend (`POST /api/scrape`, or
import `app.services.scraping`). Stealth mode requires browser binaries:

```bash
cd backend && ~/.local/bin/uv run scrapling install
```

## n8n orchestration (wired)

n8n runs the schedules; the API holds all logic. Active workflows:

| Workflow | Schedule | Does |
|---|---|---|
| Follow-up Cadence | every 30 min | POST /api/outreach/process-cadence (sends approved messages, idempotent) |
| Daily Digest & Health | 7 AM daily | health check, alerts on degradation |
| Morning Lead Batch | manual | POST /api/pipeline/run with sourced lead ids |

Auth: workflows use `ORBIT_SERVICE_TOKEN` (10-yr JWT for automation@orbit.local,
injected into the systemd unit via orbit-n8n.service.d/token.conf). The service
user is admin in every workspace. Regenerate: `backend/uv run python scripts/create_service_token.py`.

Re-import workflows after editing exports:
`N8N_USER_FOLDER=/home/ubuntu/GTM/orbit/n8n/data n8n import:workflow --input=<file>`

## Architecture boundaries after the 10.3 refactor

| Layer | Owns | Never does |
|---|---|---|
| Postgres | state machine, scoring math, gates, audit, **event outbox (pg_notify `orbit_events`)** | external calls |
| FastAPI | deterministic validation, apply endpoints, approval/suppression gates, idempotent claims | LLM, scraping, SMTP |
| n8n | stage contexts → Scrapling → LLM (OpenRouter) → apply; email transport; reply classification; retries w/ backoff; DLQ via record_failure | business state |

Event chain: `lead.qualification_requested → (n8n: LLM) → apply/qualification →
lead.enrichment_requested → (n8n: Scrapling + LLM) → apply/enrichment →
lead.audit_requested → … → apply/draft → approval → message.approved →
(n8n SMTP) → apply/send-result. Replies: durable intake → reply.received →
(n8n LLM) → apply/classification.

n8n needs env: `ORBIT_SERVICE_TOKEN` (injected via systemd drop-in),
`OPENROUTER_API_KEY` (set in the n8n unit or UI), and SMTP credentials
configured once in the n8n UI for the Email Transport workflow.
