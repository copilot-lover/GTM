import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import app.db as db
from app.config import get_settings
from app.routers import routes
from app.routers.gtm import router as gtm_router

logger = logging.getLogger(__name__)


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
    for router in routes:
        app.include_router(router, prefix="/api")
    app.include_router(gtm_router, prefix="/api")
    # Serve the built dashboard (single-VM deployment)
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")
    return app


app = create_app()
