# Recovery procedures

## Git recovery

The repo at `/home/ubuntu/GTM/orbit` is the source of truth for all code,
migrations, and n8n workflow exports. To rebuild from git:

```bash
git clone <remote> orbit && cd orbit
sudo scripts/setup_db.sh          # DB role + extensions
scripts/migrate.sh                # schema to latest
cd backend && ~/.local/bin/uv sync # python deps
npm install -g n8n                 # orchestration
sudo cp ../deploy/*.service /etc/systemd/system/ && sudo systemctl daemon-reload
sudo systemctl enable --now postgresql orbit-api orbit-n8n
```

If no remote exists yet, recover from the local clone + latest backup (below).

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
