"""Background monitoring worker.

Uses an asyncio.Lock to prevent overlapping cycles.
Started and stopped via FastAPI lifespan.
"""
from __future__ import annotations

import asyncio
import logging

import aiosqlite

from app.domain import constants as C
from app.infrastructure.checkers.http_checker import HttpChecker
from app.infrastructure.checkers.ping_checker import PingChecker
from app.infrastructure.repositories import pet_repo, server_repo
from app.services.monitor_service import MonitorService

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()


def _build_monitor_service() -> MonitorService:
    class _PetRepo:
        async def get_pet(self, db): return await pet_repo.get_pet(db)
        async def save_pet(self, db, p): return await pet_repo.save_pet(db, p)
        async def clear_last_event(self, db): return await pet_repo.clear_last_event(db)

    class _ServerRepo:
        async def list_servers(self, db): return await server_repo.list_servers(db)
        async def update_server_check_result(self, db, *a): return await server_repo.update_server_check_result(db, *a)
        async def upsert_daily_stat(self, db, *a): return await server_repo.upsert_daily_stat(db, *a)

    return MonitorService(
        pet_repo=_PetRepo(),
        server_repo=_ServerRepo(),
        http_checker=HttpChecker(),
        ping_checker=PingChecker(),
    )


async def monitor_loop(db_path: str) -> None:
    """Runs forever until cancelled. Opened a fresh DB connection each cycle."""
    service = _build_monitor_service()
    while True:
        await asyncio.sleep(C.MONITOR_INTERVAL_SECONDS)
        if _lock.locked():
            logger.warning("Previous monitor cycle still running — skipping this tick.")
            continue
        async with _lock:
            try:
                async with aiosqlite.connect(db_path) as db:
                    await service.run_cycle(db)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Monitor cycle failed")
