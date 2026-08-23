#!/usr/bin/env bash
# Nightly DB backup: pg_dump -> backups/YYYYMMDD-HHMMSS.sql.gz
# Keeps the last N backups (default 14). Cron example:
#   15 3 * * * /home/ubuntu/GTM/orbit/scripts/backup_db.sh >> /home/ubuntu/GTM/orbit/backups/backup.log 2>&1
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="$REPO_DIR/backups"
RETENTION="${ORBIT_BACKUP_RETENTION:-14}"

mkdir -p "$BACKUP_DIR"

# shellcheck disable=SC1091
source <(grep -E '^POSTGRES_' "$REPO_DIR/backend/.env" | sed 's/^/export /')

STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$BACKUP_DIR/$STAMP.sql.gz"

pg_dump "postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}" \
  | gzip > "$OUT"

echo "$(date -Is) wrote $OUT ($(du -h "$OUT" | cut -f1))"

ls -1t "$BACKUP_DIR"/[0-9]*.sql.gz | tail -n +"$((RETENTION + 1))" | xargs -r rm --
