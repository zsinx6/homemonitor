"""Ping (ICMP) server health checker using asyncio subprocess."""
from __future__ import annotations

import asyncio
import sys

from app.domain import constants as C
from app.domain.server import ServerCheckResult
from app.infrastructure.checkers.base import ServerChecker


class PingChecker(ServerChecker):
    async def check(
        self,
        server_id: int,
        name: str,
        address: str,
        port: int | None,  # ignored for ICMP ping
        check_params: dict | None = None,  # ignored for ping
    ) -> ServerCheckResult:
        # Platform-specific ping flags
        if sys.platform == "win32":
            cmd = ["ping", "-n", "1", "-w", str(C.PING_TIMEOUT_SECONDS * 1000), address]
        else:
            cmd = ["ping", "-c", "1", "-W", str(C.PING_TIMEOUT_SECONDS), address]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.communicate(), timeout=C.PING_TIMEOUT_SECONDS + 2)
            is_up = proc.returncode == 0
            error = None if is_up else "No response to ping"
        except asyncio.TimeoutError:
            is_up = False
            error = "Ping timed out"
        except Exception as exc:
            is_up = False
            error = str(exc)[:200]

        return ServerCheckResult(
            server_id=server_id,
            name=name,
            is_up=is_up,
            error=error,
        )
