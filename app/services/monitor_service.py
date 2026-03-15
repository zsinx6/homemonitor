"""Monitor service: orchestrates server checks and pet state updates."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.domain.pet import apply_monitor_cycle
from app.domain.server import ServerCheckResult, detect_state_transitions
from app.infrastructure.checkers.base import ServerChecker


class MonitorService:
    def __init__(
        self,
        pet_repo,
        server_repo,
        http_checker: ServerChecker,
        ping_checker: ServerChecker,
    ) -> None:
        self._pet_repo = pet_repo
        self._server_repo = server_repo
        self._http_checker = http_checker
        self._ping_checker = ping_checker

    async def run_cycle(self, db) -> None:
        """Run one full monitoring cycle: check all servers, update pet state."""
        servers = await self._server_repo.list_servers(db)

        # Snapshot previous statuses for transition detection
        previous_statuses = {s.name: s.status for s in servers}

        # Run all checks in parallel
        tasks = [
            self._check_server(s.id, s.name, s.address, s.port, s.type)
            for s in servers
        ]
        results: list[ServerCheckResult] = await asyncio.gather(*tasks)

        # Persist check results and build current status snapshot
        checked_at = datetime.now(timezone.utc)
        date_str = checked_at.strftime("%Y-%m-%d")
        current_statuses: dict[str, str] = {}

        for result in results:
            await self._server_repo.update_server_check_result(
                db, result.server_id, result.is_up, result.error, checked_at
            )
            await self._server_repo.upsert_daily_stat(
                db, result.server_id, date_str, result.is_up
            )
            current_statuses[result.name] = "UP" if result.is_up else "DOWN"

        # Detect transitions
        newly_down, newly_recovered = detect_state_transitions(
            previous_statuses, current_statuses
        )

        # Update pet state
        pet = await self._pet_repo.get_pet(db)
        updated_pet = apply_monitor_cycle(
            pet,
            down_server_names=newly_down if newly_down else [
                name for name, status in current_statuses.items() if status == "DOWN"
            ],
            recovered_server_names=newly_recovered,
        )
        await self._pet_repo.save_pet(db, updated_pet)

    async def _check_server(
        self,
        server_id: int,
        name: str,
        address: str,
        port,
        server_type: str,
    ) -> ServerCheckResult:
        checker = self._http_checker if server_type == "http" else self._ping_checker
        return await checker.check(server_id, name, address, port)
