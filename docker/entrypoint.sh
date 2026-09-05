#!/usr/bin/env bash
# Entrypoint script for Orbit GTM OS container
# Runs migrations and starts the application

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${REPO_DIR}/backend"
FRONTEND_DIR="${REPO_DIR}/frontend"

# Source environment variables
if [[ -f "${BACKEND_DIR}/.env" ]]; then
  # shellcheck disable=SC1091
  source <(grep -E '^(POSTGRES_|JWT_|ORBIT_)' "${BACKEND_DIR}/.env" | sed 's/^/export /')
fi

DB_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"

echo "=== Orbit GTM OS Starting ==="
echo "Database: ${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"

# Wait for database to be ready
echo "Waiting for database..."
for i in {1..30}; do
  if pg_isready -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; then
    echo "Database is ready"
    break
  fi
  echo "  waiting... (${i}/30)"
  sleep 2
done

# Check if onboarding is needed (migrations run automatically in app startup)
ONBOARDING_STATUS=$(psql "${DB_URL}" -tA -c "
  SELECT onboarding_completed FROM workspaces ORDER BY created_at DESC LIMIT 1
" 2>/dev/null || echo "error")

if [[ "${ONBOARDING_STATUS}" == "f" ]] || [[ "${ONBOARDING_STATUS}" == "error" ]]; then
  echo "Onboarding not complete - will show wizard on first access"
else
  echo "Onboarding already complete"
fi

# Build frontend if not already built
if [[ ! -d "${FRONTEND_DIR}/dist" ]]; then
  echo "Building frontend..."
  cd "${FRONTEND_DIR}"
  npm ci
  npm run build
fi

# Start the application
echo "Starting Orbit GTM OS on port ${APP_PORT:-8100}..."
cd "${BACKEND_DIR}"
exec uv run uvicorn app.main:app --host "${APP_HOST:-0.0.0.0}" --port "${APP_PORT:-8100}" --workers 2