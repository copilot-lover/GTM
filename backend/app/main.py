from contextlib import asynccontextmanager

from fastapi import FastAPI

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
    return app


app = create_app()
