"""HTTP server health checker using httpx.AsyncClient."""
from __future__ import annotations

import httpx
from urllib.parse import urlparse, urlunparse

from app.domain import constants as C
from app.domain.server import ServerCheckResult
from app.infrastructure.checkers.base import ServerChecker


class HttpChecker(ServerChecker):
    async def check(
        self,
        server_id: int,
        name: str,
        address: str,
        port: int | None,
    ) -> ServerCheckResult:
        url = address
        if port:
            parsed = urlparse(url)
            # Only inject port when the URL doesn't already specify one
            if not parsed.port:
                netloc = f"{parsed.hostname}:{port}"
                url = urlunparse(parsed._replace(netloc=netloc))

        try:
            async with httpx.AsyncClient(
                timeout=C.HTTP_TIMEOUT_SECONDS, follow_redirects=True
            ) as client:
                response = await client.get(url)
            is_up = 200 <= response.status_code < 400
            error = None if is_up else f"HTTP {response.status_code}"
        except Exception as exc:
            is_up = False
            error = str(exc)[:200]

        return ServerCheckResult(
            server_id=server_id,
            name=name,
            is_up=is_up,
            error=error,
        )
