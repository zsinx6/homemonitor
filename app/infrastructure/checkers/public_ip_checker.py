"""Public IP checker.

Queries an IP-echo service (default: api.ipify.org) to determine the current
public IP address and whether the internet connection is reachable.

The detected IP is returned in the result so the monitor service can compare
it against the last known IP stored in check_params and fire an alert on change.

check_params (managed automatically):
    last_ip (str): last known public IP — updated by the monitor service
                   after each successful check.
"""
from __future__ import annotations

import time

import httpx

from app.domain.server import ServerCheckResult
from app.infrastructure.checkers.base import ServerChecker

_DEFAULT_IP_SERVICE = "https://api.ipify.org"


class PublicIpChecker(ServerChecker):
    async def check(
        self,
        server_id: int,
        name: str,
        address: str,
        port: int | None,
        check_params: dict | None = None,
    ) -> ServerCheckResult:
        service_url = (
            address.strip()
            if address.strip().startswith("http")
            else _DEFAULT_IP_SERVICE
        )

        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                response = await client.get(service_url)
            latency_ms = int((time.perf_counter() - t0) * 1000)

            if 200 <= response.status_code < 300:
                detected_ip = response.text.strip()
                return ServerCheckResult(
                    server_id=server_id,
                    name=name,
                    is_up=True,
                    error=None,
                    latency_ms=latency_ms,
                    detected_ip=detected_ip,
                )
            return ServerCheckResult(
                server_id=server_id,
                name=name,
                is_up=False,
                error=f"HTTP {response.status_code}",
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
