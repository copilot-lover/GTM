from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import app.db as db
from app.config import get_settings
from app.routers import routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.get_pool()
    yield
    db.close_pool()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Orbit GTM OS API", lifespan=lifespan)
    for router in routes:
        app.include_router(router, prefix="/api")
    # Serve the built dashboard (single-VM deployment)
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")
    return app


app = create_app()
