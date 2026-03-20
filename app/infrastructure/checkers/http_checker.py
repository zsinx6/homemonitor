"""HTTP server health checker using httpx.AsyncClient."""
from __future__ import annotations

import asyncio
import ssl as ssl_module
import time
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse

import httpx

from app.domain import constants as C
from app.domain.server import ServerCheckResult
from app.infrastructure.checkers.base import ServerChecker


async def _fetch_ssl_expiry(hostname: str, port: int) -> str | None:
    """Return the ISO expiry datetime of the TLS cert at hostname:port, or None."""
    try:
        ctx = ssl_module.create_default_context()
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(hostname, port, ssl=ctx),
            timeout=5.0,
        )
        ssl_obj = writer.get_extra_info("ssl_object")
        cert = ssl_obj.getpeercert() if ssl_obj else None
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        if cert:
            not_after = cert.get("notAfter")
            if not_after:
                expiry = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(
                    tzinfo=timezone.utc
                )
                return expiry.isoformat()
    except Exception:
        pass
    return None


class HttpChecker(ServerChecker):
    async def check(
        self,
        server_id: int,
        name: str,
        address: str,
        port: int | None,
        check_params: dict | None = None,
    ) -> ServerCheckResult:
        url = address
        if port:
            parsed = urlparse(url)
            # Only inject port when the URL doesn't already specify one
            if not parsed.port:
                netloc = f"{parsed.hostname}:{port}"
                url = urlunparse(parsed._replace(netloc=netloc))

        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                timeout=C.HTTP_TIMEOUT_SECONDS, follow_redirects=True
            ) as client:
                response = await client.get(url)
            latency_ms = int((time.perf_counter() - t0) * 1000)
            # Allow caller to specify acceptable status codes via check_params
            expected = (check_params or {}).get("expected_status")
            if expected is not None:
                is_up = response.status_code in expected
            else:
                is_up = 200 <= response.status_code < 300
            error = None if is_up else f"HTTP {response.status_code}"
        except Exception as exc:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            is_up = False
            error = str(exc)[:200]

        # Fetch SSL cert expiry for HTTPS URLs (best-effort, non-blocking)
        ssl_expiry_date: str | None = None
        parsed_url = urlparse(url)
        if parsed_url.scheme == "https":
            host = parsed_url.hostname or ""
            cert_port = parsed_url.port or 443
            ssl_expiry_date = await _fetch_ssl_expiry(host, cert_port)

        return ServerCheckResult(
            server_id=server_id,
            name=name,
            is_up=is_up,
            error=error,
            latency_ms=latency_ms,
            ssl_expiry_date=ssl_expiry_date,
        )
