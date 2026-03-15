"""Abstract base for server health checkers."""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.server import ServerCheckResult


class ServerChecker(ABC):
    @abstractmethod
    async def check(self, server_id: int, name: str, address: str,
                    port: int | None) -> ServerCheckResult:
        """Perform a health check and return a result."""
