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

# n8n workflows are edited in the UI, then exported to n8n/workflows/ and committed.
```

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
