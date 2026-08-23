#!/usr/bin/env bash
# Applies pending SQL migrations in db/migrations/ in filename order.
# Usage: scripts/migrate.sh [db_url]
#   db_url defaults to postgresql://orbit:<pass>@127.0.0.1:5432/orbit
# Reads POSTGRES_* from backend/.env if db_url not given.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ $# -ge 1 ]]; then
  DB_URL="$1"
else
  # shellcheck disable=SC1091
  source <(grep -E '^POSTGRES_' "$REPO_DIR/backend/.env" | sed 's/^/export /')
  DB_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"
fi

psql "$DB_URL" -v ON_ERROR_STOP=1 -q <<'SQL'
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);
SQL

shopt -s nullglob
applied=0
for f in "$REPO_DIR"/db/migrations/*.sql; do
  name="$(basename "$f")"
  already=$(psql "$DB_URL" -tA -c "SELECT 1 FROM schema_migrations WHERE filename='$name'")
  if [[ "$already" == "1" ]]; then
    continue
  fi
  echo "applying $name"
  psql "$DB_URL" -v ON_ERROR_STOP=1 -q -f "$f"
  psql "$DB_URL" -v ON_ERROR_STOP=1 -q -c "INSERT INTO schema_migrations (filename) VALUES ('$name')"
  applied=$((applied+1))
done
echo "migrations applied: $applied"
