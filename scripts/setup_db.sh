#!/usr/bin/env bash
# One-time DB provisioning. Run with sudo: sudo scripts/setup_db.sh
# Creates the orbit role + database + extensions (extensions need superuser on PG12).
# Idempotent: safe to re-run.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_DIR/backend/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing $ENV_FILE — copy .env.example and fill in POSTGRES_* first" >&2
  exit 1
fi

# shellcheck disable=SC1091
source <(grep -E '^POSTGRES_' "$ENV_FILE" | sed 's/^/export /')

sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${POSTGRES_USER}') THEN
    CREATE ROLE ${POSTGRES_USER} LOGIN PASSWORD '${POSTGRES_PASSWORD}';
  END IF;
END \$\$;
SELECT 'CREATE DATABASE ${POSTGRES_DB} OWNER ${POSTGRES_USER}'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${POSTGRES_DB}')\gexec
SQL

sudo -u postgres psql -q -d "${POSTGRES_DB}" -v ON_ERROR_STOP=1 <<'SQL'
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;
GRANT ALL ON SCHEMA public TO orbit;
SQL

echo "database ready"
