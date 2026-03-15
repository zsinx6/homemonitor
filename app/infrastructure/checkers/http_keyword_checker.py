"""HTTP keyword checker.

Performs an HTTP GET and verifies that a required keyword appears in the
response body.  Useful when a 2xx status alone is not enough (e.g. the server
returns 200 even for maintenance pages).

check_params:
    keyword (str, required): case-insensitive substring that must appear in
        the response body for the check to be considered UP.
"""
from __future__ import annotations

import httpx
from urllib.parse import urlparse, urlunparse

from app.domain import constants as C
from app.domain.server import ServerCheckResult
from app.infrastructure.checkers.base import ServerChecker


class HttpKeywordChecker(ServerChecker):
    async def check(
        self,
        server_id: int,
        name: str,
        address: str,
        port: int | None,
        check_params: dict | None = None,
    ) -> ServerCheckResult:
        keyword: str = str((check_params or {}).get("keyword", "")).strip()

        url = address
        if port:
            parsed = urlparse(url)
            if not parsed.port:
                netloc = f"{parsed.hostname}:{port}"
                url = urlunparse(parsed._replace(netloc=netloc))

        try:
            async with httpx.AsyncClient(
                timeout=C.HTTP_TIMEOUT_SECONDS, follow_redirects=True
            ) as client:
                response = await client.get(url)

            if not (200 <= response.status_code < 300):
                return ServerCheckResult(
                    server_id=server_id,
                    name=name,
                    is_up=False,
                    error=f"HTTP {response.status_code}",
                )

            if keyword and keyword.lower() not in response.text.lower():
                return ServerCheckResult(
                    server_id=server_id,
                    name=name,
                    is_up=False,
                    error=f"Keyword '{keyword}' not found in response",
                )

            return ServerCheckResult(server_id=server_id, name=name, is_up=True, error=None)
        except Exception as exc:
            return ServerCheckResult(
                server_id=server_id,
                name=name,
                is_up=False,
                error=str(exc)[:200],
            )
