import asyncio
import logging
import os
import subprocess
import time
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

import app.db as db
from app.config import get_settings
from app.routers import routes
from app.routers.gtm import router as gtm_router

logger = logging.getLogger(__name__)

request_id_var: ContextVar[str] = ContextVar("request_id", default="")

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_migrations():
    """Run pending SQL migrations on startup."""
    migrations_dir = REPO_ROOT / "db" / "migrations"
    if not migrations_dir.exists():
        logger.warning("Migrations directory not found: %s", migrations_dir)
        return

    s = get_settings()
    db_url = (
        f"postgresql://{s.postgres_user}:{s.postgres_password}"
        f"@{s.postgres_host}:{s.postgres_port}/{s.postgres_db}"
    )

    # Create schema_migrations table if not exists
    init_sql = """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        filename text PRIMARY KEY,
        applied_at timestamptz NOT NULL DEFAULT now()
    );
    """
    with db.get_pool().connection() as conn:
        conn.execute(init_sql)

    applied = 0
    for f in sorted(migrations_dir.glob("*.sql")):
        name = f.name
        # Atomic check-and-insert using INSERT ... ON CONFLICT DO NOTHING
        with db.get_pool().connection() as conn:
            result = conn.execute(
                "INSERT INTO schema_migrations (filename) VALUES (%s) ON CONFLICT DO NOTHING", (name,)
            )
            if result.rowcount == 0:
                continue  # Already applied by another process
        logger.info("Applying migration: %s", name)
        try:
            # Use psql for proper SQL execution
            result = subprocess.run(
                ["psql", db_url, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(f)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                logger.error("Migration %s failed: %s", name, result.stderr)
                # Rollback the schema_migrations entry on failure
                with db.get_pool().connection() as conn:
                    conn.execute("DELETE FROM schema_migrations WHERE filename = %s", (name,))
                raise RuntimeError(f"Migration {name} failed: {result.stderr}")
            applied += 1
        except subprocess.TimeoutExpired:
            logger.error("Migration %s timed out", name)
            # Rollback on timeout
            with db.get_pool().connection() as conn:
                conn.execute("DELETE FROM schema_migrations WHERE filename = %s", (name,))
            raise
    if applied:
        logger.info("Applied %d migrations", applied)
    else:
        logger.info("No pending migrations")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """In-memory per-IP rate limiter with separate limits for auth endpoints."""

    AUTH_LIMIT = 10
    GENERAL_LIMIT = 60
    WINDOW = 60  # seconds

    _hits: dict[str, list[float]] = {}

    def __init__(self, app):
        super().__init__(app)
        self._cleanup_task: asyncio.Task | None = None

    @classmethod
    def reset(cls):
        cls._hits.clear()

    async def _periodic_cleanup(self):
        while True:
            await asyncio.sleep(60)
            now = time.monotonic()
            stale = [ip for ip, stamps in self._hits.items()
                     if not stamps or now - stamps[-1] > self.WINDOW * 2]
            for ip in stale:
                del self._hits[ip]

    def _get_limit(self, path: str) -> int:
        if path.startswith("/api/auth"):
            return self.AUTH_LIMIT
        return self.GENERAL_LIMIT

    async def dispatch(self, request: Request, call_next):
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.ensure_future(self._periodic_cleanup())

        ip = request.client.host if request.client else "unknown"
        limit = self._get_limit(request.url.path)
        now = time.monotonic()
        window_start = now - self.WINDOW

        stamps = self._hits.setdefault(ip, [])
        # drop timestamps outside the window
        self._hits[ip] = [t for t in stamps if t > window_start]
        stamps = self._hits[ip]

        if len(stamps) >= limit:
            retry_after = int(self.WINDOW - (now - stamps[0])) + 1
            return JSONResponse(
                status_code=429,
                content={"detail": "too many requests"},
                headers={"Retry-After": str(retry_after)},
            )

        stamps.append(now)
        return await call_next(request)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a UUID4 X-Request-ID to every request and response."""

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        request_id_var.set(rid)
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response


async def _telegram_poller():
    """Lightweight poller for Telegram getUpdates. Log-only for MVP."""
    import httpx
    from app.services.telegram import _get_settings, _decrypt_token

    offset = 0
    while True:
        try:
            ts = _get_settings()
            if not ts.get("enabled"):
                await asyncio.sleep(30)
                continue
            token = _decrypt_token(ts.get("bot_token_encrypted"))
            if not token:
                await asyncio.sleep(30)
                continue
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"https://api.telegram.org/bot{token}/getUpdates",
                    params={"offset": offset, "timeout": 5},
                )
                data = resp.json()
                if data.get("ok") and data.get("result"):
                    for update in data["result"]:
                        offset = update["update_id"] + 1
                        msg = update.get("message", {})
                        text = msg.get("text", "")
                        chat_id = msg.get("chat", {}).get("id")
                        logger.info("Telegram update: chat=%s text=%s", chat_id, text)
        except Exception as e:
            logger.debug("Telegram poller error: %s", e)
        await asyncio.sleep(10)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.get_pool()
    run_migrations()
    supervisor = None
    telegram_task = None
    settings = get_settings()
    if settings.workers_enabled:
        from app.services.job_queue import WorkerSupervisor

        supervisor = WorkerSupervisor()
        supervisor.start()
    if settings.app_secret:
        try:
            from app.services.telegram import _get_settings as _tg_settings

            ts = _tg_settings()
            if ts.get("enabled"):
                telegram_task = asyncio.create_task(_telegram_poller())
                logger.info("Telegram poller started")
        except Exception as e:
            logger.debug("Telegram poller skip: %s", e)
    yield
    if telegram_task is not None:
        telegram_task.cancel()
        try:
            await telegram_task
        except asyncio.CancelledError:
            pass
    if supervisor is not None:
        await supervisor.stop()
    db.close_pool()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Orbit GTM OS API", lifespan=lifespan)

    # --- Middleware (order matters: last added = first executed) ---
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    # --- Global exception handler ---
    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "internal server error"},
        )

    for router in routes:
        app.include_router(router, prefix="/api")
    app.include_router(gtm_router, prefix="/api")
    # Serve the built dashboard (single-VM deployment) — SPA fallback
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.exists():
        from fastapi.responses import FileResponse

        app.mount("/assets", StaticFiles(directory=str(dist / "assets")), name="assets")

        @app.get("/{full_path:path}")
        async def _spa_fallback(full_path: str):
            # Let /api already handled above; serve SPA for everything else
            candidate = dist / full_path
            if full_path and candidate.exists() and candidate.is_file():
                return FileResponse(str(candidate))
            # SPA entry — React Router handles /explorer, /leads/:id etc.
            index = dist / "index.html"
            if index.exists():
                return FileResponse(str(index))
            return JSONResponse(status_code=404, content={"detail": "Not Found"})

        # Also serve root explicitly (fallback covers it, but keep mount for icons)
        app.mount("/", StaticFiles(directory=str(dist), html=False), name="frontend-root")
    return app


app = create_app()
