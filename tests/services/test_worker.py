"""Tests for the background worker coroutines (monitor_loop, fast_recovery_loop)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.domain.constants as C


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db_context():
    """Return a mock aiosqlite connection context manager."""
    mock_db = AsyncMock()
    mock_conn = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_db)
    mock_conn.__aexit__ = AsyncMock(return_value=None)
    return mock_conn


def _mock_service(check_down_impl=None):
    """Return a MagicMock MonitorService with check_down_servers wired."""
    svc = MagicMock()
    svc.check_down_servers = check_down_impl or AsyncMock()
    return svc


# ---------------------------------------------------------------------------
# fast_recovery_loop tests
# ---------------------------------------------------------------------------

class TestFastRecoveryLoop:
    """Tests for the fast_recovery_loop coroutine in app.worker."""

    async def test_calls_check_down_servers_each_tick(self):
        """Loop calls check_down_servers at least once when interval is 0."""
        call_count = 0

        async def fake_check_down(db):
            nonlocal call_count
            call_count += 1

        C.DOWN_SERVER_RECHECK_INTERVAL_SECONDS = 0  # autouse fixture restores this

        with (
            patch("app.worker._get_service", return_value=_mock_service(fake_check_down)),
            patch("app.worker.aiosqlite.connect", return_value=_mock_db_context()),
        ):
            from app.worker import fast_recovery_loop

            task = asyncio.create_task(fast_recovery_loop("fake.db"))
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert call_count > 0

    async def test_skips_tick_when_lock_held(self):
        """If the shared lock is held, the tick is skipped without calling check_down_servers."""
        call_count = 0

        async def fake_check_down(db):
            nonlocal call_count
            call_count += 1

        C.DOWN_SERVER_RECHECK_INTERVAL_SECONDS = 0

        with (
            patch("app.worker._get_service", return_value=_mock_service(fake_check_down)),
            patch("app.worker.aiosqlite.connect", return_value=_mock_db_context()),
        ):
            import app.worker as worker_mod
            from app.worker import fast_recovery_loop

            async with worker_mod._lock:
                task = asyncio.create_task(fast_recovery_loop("fake.db"))
                await asyncio.sleep(0.05)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        assert call_count == 0

    async def test_exception_does_not_crash_loop(self):
        """Exceptions from check_down_servers are logged and the loop continues."""
        call_count = 0

        async def raising_check(db):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("transient network error")

        C.DOWN_SERVER_RECHECK_INTERVAL_SECONDS = 0

        with (
            patch("app.worker._get_service", return_value=_mock_service(raising_check)),
            patch("app.worker.aiosqlite.connect", return_value=_mock_db_context()),
        ):
            from app.worker import fast_recovery_loop

            task = asyncio.create_task(fast_recovery_loop("fake.db"))
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Must have run more than once, proving the loop survived the exception
        assert call_count > 1

    async def test_loop_is_cancellable(self):
        """fast_recovery_loop can be cancelled cleanly via CancelledError."""
        C.DOWN_SERVER_RECHECK_INTERVAL_SECONDS = 100  # long sleep so cancel fires during sleep

        with (
            patch("app.worker._get_service", return_value=_mock_service()),
            patch("app.worker.aiosqlite.connect", return_value=_mock_db_context()),
        ):
            from app.worker import fast_recovery_loop

            task = asyncio.create_task(fast_recovery_loop("fake.db"))
            await asyncio.sleep(0)  # let the task start
            task.cancel()

            with pytest.raises(asyncio.CancelledError):
                await task
