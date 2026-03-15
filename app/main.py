"""FastAPI application factory, lifespan, and static file mounting."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.infrastructure.database import init_db
from app.worker import monitor_loop

logger = logging.getLogger(__name__)

DB_PATH = "digimon.db"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: init DB and start background worker
    async with aiosqlite.connect(DB_PATH) as db:
        await init_db(db)

    task = asyncio.create_task(monitor_loop(DB_PATH))
    app.state.monitor_task = task
    logger.info("DigiMon(itor) started.")
    yield
    # Shutdown: cancel worker gracefully
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("DigiMon(itor) stopped.")


def create_app(db_path: str = DB_PATH) -> FastAPI:
    """Factory so tests can inject a custom DB path."""
    app = FastAPI(title="DigiMon(itor)", lifespan=lifespan)
    app.state.db_path = db_path

    # API routers (registered after import to avoid circular deps)
    from app.api.routers import pet, servers, tasks  # noqa: PLC0415
    app.include_router(pet.router, prefix="/api")
    app.include_router(servers.router, prefix="/api")
    app.include_router(tasks.router, prefix="/api")

    # Serve the SPA
    static_dir = Path(__file__).parent.parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


app = create_app()
