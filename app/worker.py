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
from app.infrastructure.checkers.http_keyword_checker import HttpKeywordChecker
from app.infrastructure.checkers.ping_checker import PingChecker
from app.infrastructure.checkers.public_ip_checker import PublicIpChecker
from app.infrastructure.checkers.tcp_checker import TcpChecker
from app.infrastructure.config import get_config
from app.infrastructure.notifier import build_notifier
from app.services.monitor_service import MonitorService

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()
_service: MonitorService | None = None


def _get_service() -> MonitorService:
    global _service
    if _service is None:
        cfg = get_config()
        registry = {
            "http": HttpChecker(),
            "ping": PingChecker(),
            "tcp": TcpChecker(),
            "http_keyword": HttpKeywordChecker(),
            "public_ip": PublicIpChecker(),
        }
        _service = MonitorService(
            pet_repo=PetRepoAdapter(),
            server_repo=ServerRepoAdapter(),
            checker_registry=registry,
            memory_repo=MemoryRepoAdapter(),
            notifier=build_notifier(cfg.ntfy_topic),
            notify_on_recovery=cfg.notify_on_recovery,
            notify_on_death=cfg.notify_on_death,
        )
    return _service


async def _run_one_cycle(db_path: str) -> None:
    """Run one full monitoring cycle under the shared lock."""
    if _lock.locked():
        logger.info("Monitor cycle already running — skipping triggered check.")
        return
    async with _lock:
        try:
            async with aiosqlite.connect(db_path) as db:
                await asyncio.wait_for(
                    _get_service().run_cycle(db),
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


async def trigger_cycle(db_path: str) -> None:
    """Request an immediate check cycle. Safe to call concurrently — skips if already running."""
    await _run_one_cycle(db_path)


def get_service() -> MonitorService:
    """Return the shared MonitorService singleton (creates it if needed)."""
    return _get_service()


async def monitor_loop(db_path: str) -> None:
    """Runs forever until cancelled. Opens a fresh DB connection each cycle."""
    _get_service()  # warm up singleton before first tick
    while True:
        await asyncio.sleep(C.MONITOR_INTERVAL_SECONDS)
        await _run_one_cycle(db_path)
