# Recovery procedures

## Git recovery

The repo at `/home/ubuntu/GTM/orbit` is the source of truth for all code,
migrations, and n8n workflow exports. To rebuild from git:

```bash
git clone <remote> orbit && cd orbit
sudo scripts/setup_db.sh          # DB role + extensions
scripts/migrate.sh                # schema to latest

# Backend deps + env
cp .env.example backend/.env        # fill in POSTGRES_PASSWORD, JWT_SECRET, etc.

# Frontend build (API serves frontend/dist)
cd frontend && npm install && npm run build && cd ..

# Orchestration
npm install -g n8n                 # import n8n/workflows/*.json via the n8n UI at :5678
                                   # (deploy unit sets N8N_USER_FOLDER=orbit/n8n/data)

sudo cp deploy/*.service /etc/systemd/system/ && sudo systemctl daemon-reload
sudo systemctl enable --now postgresql orbit-api orbit-n8n
curl http://127.0.0.1:8100/api/health   # must return ok/ok
```

Test database (for running the suite): see docs/RUNBOOK.md provisioning commands.

## Database restore

```bash
# pick newest dump
ls -1t backups/*.sql.gz | head -1
scripts/restore_db.sh backups/<stamp>.sql.gz
```

Restore rehearsal must be done once before go-live (spec §19.7).

## Secrets

Secrets live only in `backend/.env` (and `.env.prod` in production). If lost:
rotate credentials at each provider, regenerate DB password with
`ALTER ROLE orbit PASSWORD ...`, update env file, restart services.
Never re-add secrets into git history.
