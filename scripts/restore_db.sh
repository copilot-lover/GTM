#!/usr/bin/env bash
# Restore a backup produced by backup_db.sh into a database.
# Usage: scripts/restore_db.sh <backup-file> [target_db_url]
# WARNING: restores into the target DB configured in backend/.env unless a URL is given.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FILE="${1:?usage: restore_db.sh <backup-file> [db_url]}"

if [[ $# -ge 2 ]]; then
  DB_URL="$2"
else
  # shellcheck disable=SC1091
  source <(grep -E '^POSTGRES_' "$REPO_DIR/backend/.env" | sed 's/^/export /')
  DB_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"
fi

echo "restoring $FILE"
gunzip -c "$FILE" | psql "$DB_URL" -v ON_ERROR_STOP=1
echo "restore complete"
