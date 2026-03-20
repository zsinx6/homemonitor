"""TCP port connectivity checker.

Opens a TCP connection to host:port and closes it immediately.
Useful for services that don't speak HTTP or ICMP (databases, MQTT, custom
daemons).  Requires a port — validation is enforced in the API layer.
"""
from __future__ import annotations

import asyncio
import time

from app.domain import constants as C
from app.domain.server import ServerCheckResult
from app.infrastructure.checkers.base import ServerChecker


class TcpChecker(ServerChecker):
    async def check(
        self,
        server_id: int,
        name: str,
        address: str,
        port: int | None,
        check_params: dict | None = None,  # reserved for future options
    ) -> ServerCheckResult:
        if not port:
            return ServerCheckResult(
                server_id=server_id,
                name=name,
                is_up=False,
                error="TCP check requires a port number",
            )

        t0 = time.perf_counter()
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(address, port),
                timeout=C.TCP_TIMEOUT_SECONDS,
            )
            latency_ms = int((time.perf_counter() - t0) * 1000)
            writer.close()
            await writer.wait_closed()
            return ServerCheckResult(
                server_id=server_id, name=name, is_up=True, error=None, latency_ms=latency_ms
            )
        except asyncio.TimeoutError:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            return ServerCheckResult(
                server_id=server_id,
                name=name,
                is_up=False,
                error=f"TCP timeout connecting to {address}:{port}",
                latency_ms=latency_ms,
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            return ServerCheckResult(
                server_id=server_id,
                name=name,
                is_up=False,
                error=str(exc)[:200],
                latency_ms=latency_ms,
            )
