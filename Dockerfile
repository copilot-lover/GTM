# Orbit GTM OS - Multi-stage Docker build
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim AS backend-builder

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock* ./
RUN pip install --no-cache-dir uv && uv sync --frozen


FROM python:3.12-slim AS runtime

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create app user
RUN useradd -m -u 1000 orbit

WORKDIR /app

# Copy backend
COPY --from=backend-builder /app/backend/.venv /app/backend/.venv
COPY backend/ /app/backend/

# Copy frontend build
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Copy migrations and entrypoint
COPY db/migrations/ /app/db/migrations/
COPY scripts/ /app/scripts/
COPY docker/entrypoint.sh /app/entrypoint.sh

# Set permissions
RUN chmod +x /app/entrypoint.sh /app/scripts/migrate.sh && \
    chown -R orbit:orbit /app

USER orbit

ENV PATH="/app/backend/.venv/bin:$PATH"
ENV PYTHONPATH="/app/backend"

EXPOSE 8100

ENTRYPOINT ["/app/entrypoint.sh"]