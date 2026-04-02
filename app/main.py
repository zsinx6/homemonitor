"""FastAPI application factory, lifespan, and static file mounting."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.infrastructure.config import get_config, load_config
from app.infrastructure.database import apply_initial_name_async, init_db
from app.worker import fast_recovery_loop, monitor_loop

logger = logging.getLogger(__name__)

DB_PATH = "digimon.db"


def create_app(db_path: str = DB_PATH) -> FastAPI:
    """Factory so tests can inject a custom DB path."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Load configuration (digimonitor.toml + env vars) before anything else
        load_config()
        # Startup: init DB and start background worker using the captured db_path
        async with aiosqlite.connect(db_path) as db:
            await init_db(db)
            await apply_initial_name_async(db, get_config().personality.initial_name)

        task = asyncio.create_task(monitor_loop(db_path))
        recovery_task = asyncio.create_task(fast_recovery_loop(db_path))
        app.state.monitor_task = task
        app.state.recovery_task = recovery_task
        logger.info("DigiMon(itor) started.")
        yield
        # Shutdown: cancel workers gracefully
        task.cancel()
        recovery_task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        try:
            await recovery_task
        except asyncio.CancelledError:
            pass
        logger.info("DigiMon(itor) stopped.")

    app = FastAPI(title="DigiMon(itor)", lifespan=lifespan)
    app.state.db_path = db_path

    # API routers (registered after import to avoid circular deps)
    from app.api.routers import pet, servers, tasks, chat, status, memories, export  # noqa: PLC0415
    app.include_router(pet.router, prefix="/api")
    app.include_router(servers.router, prefix="/api")
    app.include_router(tasks.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    app.include_router(status.router, prefix="/api")
    app.include_router(memories.router, prefix="/api")
    app.include_router(export.router, prefix="/api")

    # Serve the SPA
    static_dir = Path(__file__).parent.parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


app = create_app()
