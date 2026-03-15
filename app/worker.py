"""Background monitoring worker.

Uses an asyncio.Lock to prevent overlapping cycles.
Started and stopped via FastAPI lifespan.
"""
from __future__ import annotations

import asyncio
import logging

import aiosqlite

from app.domain import constants as C
from app.infrastructure.adapters import PetRepoAdapter, ServerRepoAdapter
from app.infrastructure.checkers.http_checker import HttpChecker
from app.infrastructure.checkers.ping_checker import PingChecker
from app.services.monitor_service import MonitorService

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()


def _build_monitor_service() -> MonitorService:
    return MonitorService(
        pet_repo=PetRepoAdapter(),
        server_repo=ServerRepoAdapter(),
        http_checker=HttpChecker(),
        ping_checker=PingChecker(),
    )


async def monitor_loop(db_path: str) -> None:
    """Runs forever until cancelled. Opens a fresh DB connection each cycle."""
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
