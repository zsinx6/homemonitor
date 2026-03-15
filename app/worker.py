"""Background monitoring worker.

Uses an asyncio.Lock to prevent overlapping cycles.
Started and stopped via FastAPI lifespan.
"""
from __future__ import annotations

import asyncio
import logging

import aiosqlite

from app.domain import constants as C
from app.infrastructure.adapters import MemoryRepoAdapter, PetRepoAdapter, ServerRepoAdapter
from app.infrastructure.checkers.http_checker import HttpChecker
from app.infrastructure.checkers.ping_checker import PingChecker
from app.infrastructure.config import get_config
from app.infrastructure.notifier import build_notifier
from app.services.monitor_service import MonitorService

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()


def _build_monitor_service() -> MonitorService:
    cfg = get_config()
    return MonitorService(
        pet_repo=PetRepoAdapter(),
        server_repo=ServerRepoAdapter(),
        http_checker=HttpChecker(),
        ping_checker=PingChecker(),
        memory_repo=MemoryRepoAdapter(),
        notifier=build_notifier(cfg.ntfy_topic),
        notify_on_recovery=cfg.notify_on_recovery,
        notify_on_death=cfg.notify_on_death,
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
                    await asyncio.wait_for(
                        service.run_cycle(db),
                        timeout=C.MONITOR_CYCLE_TIMEOUT_SECONDS,
                    )
            except asyncio.TimeoutError:
                logger.error(
                    "Monitor cycle exceeded %ds timeout — skipping this tick.",
                    C.MONITOR_CYCLE_TIMEOUT_SECONDS,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Monitor cycle failed")
