"""Monitor service: orchestrates server checks and pet state updates."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.domain.memory import MemoryType
from app.domain.pet import apply_monitor_cycle, parse_last_event
from app.domain.server import ServerCheckResult, detect_state_transitions
from app.infrastructure.checkers.base import ServerChecker
from app.infrastructure.notifier import NtfyNotifier

logger = logging.getLogger(__name__)

_SSL_WARN_DAYS = 30    # record memory event when cert expires within this many days
_SSL_NTFY_DAYS = 7     # send ntfy push when cert expires within this many days
_SSL_WARN_INTERVAL = timedelta(hours=24)  # minimum gap between repeated SSL warnings


class MonitorService:
    def __init__(
        self,
        pet_repo,
        server_repo,
        http_checker: ServerChecker | None = None,
        ping_checker: ServerChecker | None = None,
        memory_repo=None,
        notifier: Optional[NtfyNotifier] = None,
        notify_on_recovery: bool = False,
        notify_on_death: bool = True,
        checker_registry: dict[str, ServerChecker] | None = None,
    ) -> None:
        self._pet_repo = pet_repo
        self._server_repo = server_repo
        self._memory_repo = memory_repo
        self._notifier = notifier
        self._notify_on_recovery = notify_on_recovery
        self._notify_on_death = notify_on_death
        # Build unified registry from explicit registry + legacy checkers
        self._checker_registry: dict[str, ServerChecker] = {}
        if checker_registry:
            self._checker_registry.update(checker_registry)
        if http_checker is not None:
            self._checker_registry.setdefault("http", http_checker)
        if ping_checker is not None:
            self._checker_registry.setdefault("ping", ping_checker)
        # Per-server SSL warning throttle (server_id → last warned datetime)
        self._ssl_warned_at: dict[int, datetime] = {}

    async def _record(self, db, event_type: str, detail=None) -> None:
        if self._memory_repo:
            await self._memory_repo.add_memory(db, event_type, detail)

    async def run_cycle(self, db) -> None:
        """Run one full monitoring cycle: check all servers, update pet state."""
        servers = await self._server_repo.list_servers(db)

        id_to_name = {s.id: s.name for s in servers}
        previous_statuses = {s.id: s.status for s in servers}
        maintenance_ids = {s.id for s in servers if s.maintenance_mode}

        tasks = [
            self._check_server(s.id, s.name, s.address, s.port, s.type, s.check_params)
            for s in servers
        ]
        results: list[ServerCheckResult] = await asyncio.gather(*tasks)

        checked_at = datetime.now(timezone.utc)
        date_str = checked_at.strftime("%Y-%m-%d")
        current_statuses: dict[int, str] = {}

        for result in results:
            await self._server_repo.update_server_check_result(
                db, result.server_id, result.is_up, result.error, checked_at,
                latency_ms=result.latency_ms,
                ssl_expiry_date=result.ssl_expiry_date,
            )
            await self._server_repo.upsert_daily_stat(
                db, result.server_id, date_str, result.is_up,
                latency_ms=result.latency_ms,
            )
            current_statuses[result.server_id] = "UP" if result.is_up else "DOWN"

            # Handle public IP change detection
            if result.detected_ip is not None:
                server = next((s for s in servers if s.id == result.server_id), None)
                if server is not None:
                    params = dict(server.check_params or {})
                    last_ip = params.get("last_ip")
                    if last_ip is not None and last_ip != result.detected_ip:
                        await self._record(
                            db, MemoryType.PUBLIC_IP_CHANGED,
                            f"{last_ip} → {result.detected_ip}"
                        )
                        if self._notifier:
                            await self._notifier.notify(
                                title="🌐 Public IP changed",
                                message=f"{server.name}: {last_ip} → {result.detected_ip}",
                                priority="default",
                                tags=["globe_with_meridians"],
                            )
                    params["last_ip"] = result.detected_ip
                    await self._server_repo.update_server_check_params(db, result.server_id, params)

        newly_down_ids, newly_recovered_ids = detect_state_transitions(
            previous_statuses, current_statuses
        )

        newly_down_names = [
            id_to_name[i] for i in newly_down_ids
            if i in id_to_name and i not in maintenance_ids
        ]
        newly_recovered_names = [
            id_to_name[i] for i in newly_recovered_ids
            if i in id_to_name and i not in maintenance_ids
        ]

        all_currently_down_names = [
            id_to_name[sid]
            for sid, status in current_statuses.items()
            if status == "DOWN" and sid in id_to_name and sid not in maintenance_ids
        ]

        pet = await self._pet_repo.get_pet(db)

        # Apply monitor cycle first (HP gain/loss from servers)
        updated_pet = apply_monitor_cycle(
            pet,
            down_server_names=all_currently_down_names,
            recovered_server_names=newly_recovered_names,
        )

        # Suppress server_down event when no new failure occurred this cycle
        if (
            not newly_down_names
            and updated_pet.last_event is not None
            and updated_pet.last_event.startswith("server_down:")
        ):
            updated_pet = replace(updated_pet, last_event=None)

        # Apply V3 mechanics (dust spawn, mood rotation, dust HP drain)
        # Only apply if pet is alive to avoid state changes on dead pets
        if not updated_pet.is_dead:
            from app.domain.pet import apply_dust_spawn, apply_mood_rotation, apply_dust_hp_drain
            from app.domain import constants as C
            updated_pet = apply_dust_spawn(updated_pet)
            updated_pet = apply_mood_rotation(updated_pet)
            # Use epoch-seconds modulo as a restart-safe cycle throttle
            epoch_bucket = int(datetime.now(timezone.utc).timestamp()) // C.MONITOR_INTERVAL_SECONDS
            if epoch_bucket % C.DUST_HP_DRAIN_CYCLE_MODULO == 0:
                updated_pet = apply_dust_hp_drain(updated_pet)

            # Check death from dust drain
            if updated_pet.hp == 0 and not pet.is_dead:
                updated_pet = replace(updated_pet, is_dead=True, last_event="death")

        await self._pet_repo.save_pet(db, updated_pet)

        # Record memories for significant events this cycle
        if self._memory_repo:
            for name in newly_down_names:
                await self._record(db, MemoryType.SERVER_DOWN, name)
            for name in newly_recovered_names:
                await self._record(db, MemoryType.SERVER_RECOVERY, name)
            if updated_pet.is_dead and not pet.is_dead:
                await self._record(db, MemoryType.DEATH)
            event_type, detail = parse_last_event(updated_pet)
            if event_type:
                await self._record(db, event_type, detail)

        # SSL expiry warnings (throttled to once per 24 h per server)
        now = datetime.now(timezone.utc)
        for result in results:
            if result.ssl_expiry_date is None:
                continue
            try:
                expiry = datetime.fromisoformat(result.ssl_expiry_date)
                days_left = (expiry - now).days
            except Exception:
                continue
            if days_left > _SSL_WARN_DAYS:
                continue
            last_warned = self._ssl_warned_at.get(result.server_id)
            if last_warned and (now - last_warned) < _SSL_WARN_INTERVAL:
                continue
            self._ssl_warned_at[result.server_id] = now
            server_name = id_to_name.get(result.server_id, f"server {result.server_id}")
            await self._record(
                db, MemoryType.SSL_EXPIRY_WARNING,
                f"{server_name}: {days_left}d remaining"
            )
            if self._notifier and days_left <= _SSL_NTFY_DAYS:
                await self._notifier.notify(
                    title="⚠️ SSL cert expiring soon",
                    message=f"{server_name} cert expires in {days_left} day(s).",
                    priority="high",
                    tags=["lock", "warning"],
                )

        # Push notifications (fire-and-forget, never block)
        if self._notifier:
            for name in newly_down_names:
                await self._notifier.notify(
                    title="🔴 Server DOWN",
                    message=f"{name} is not responding on your homelab.",
                    priority="high",
                    tags=["warning", "skull"],
                )
            if self._notify_on_recovery:
                for name in newly_recovered_names:
                    await self._notifier.notify(
                        title="🟢 Server recovered",
                        message=f"{name} is back online.",
                        priority="default",
                        tags=["white_check_mark"],
                    )
            if self._notify_on_death and updated_pet.is_dead and not pet.is_dead:
                await self._notifier.notify(
                    title="💀 Your Digimon DIED",
                    message="Your homelab pet's HP hit zero. Open DigiMon(itor) to revive it!",
                    priority="high",
                    tags=["skull", "rotating_light"],
                )

    async def check_single(self, db, server_id: int) -> None:
        """Run an immediate check for one server and persist results.

        Unlike run_cycle, this does not affect pet HP or V3 mechanics.
        Safe to call concurrently with the background cycle.
        """
        server = await self._server_repo.get_server(db, server_id)
        if server is None:
            return
        result = await self._check_server(
            server.id, server.name, server.address, server.port,
            server.type, server.check_params,
        )
        checked_at = datetime.now(timezone.utc)
        date_str = checked_at.strftime("%Y-%m-%d")
        await self._server_repo.update_server_check_result(
            db, result.server_id, result.is_up, result.error, checked_at,
            latency_ms=result.latency_ms,
            ssl_expiry_date=result.ssl_expiry_date,
        )
        await self._server_repo.upsert_daily_stat(
            db, result.server_id, date_str, result.is_up,
            latency_ms=result.latency_ms,
        )
        # Public IP change detection
        if result.detected_ip is not None:
            params = dict(server.check_params or {})
            last_ip = params.get("last_ip")
            if last_ip is not None and last_ip != result.detected_ip:
                await self._record(
                    db, MemoryType.PUBLIC_IP_CHANGED,
                    f"{last_ip} → {result.detected_ip}",
                )
                if self._notifier:
                    await self._notifier.notify(
                        title="🌐 Public IP changed",
                        message=f"{server.name}: {last_ip} → {result.detected_ip}",
                        priority="default",
                        tags=["globe_with_meridians"],
                    )
            params["last_ip"] = result.detected_ip
            await self._server_repo.update_server_check_params(db, result.server_id, params)
        # SSL expiry warnings (throttled, same logic as run_cycle)
        if result.ssl_expiry_date is not None:
            now = datetime.now(timezone.utc)
            try:
                expiry = datetime.fromisoformat(result.ssl_expiry_date)
                days_left = (expiry - now).days
            except Exception:
                days_left = 999
            if days_left <= _SSL_WARN_DAYS:
                last_warned = self._ssl_warned_at.get(result.server_id)
                if not last_warned or (now - last_warned) >= _SSL_WARN_INTERVAL:
                    self._ssl_warned_at[result.server_id] = now
                    await self._record(
                        db, MemoryType.SSL_EXPIRY_WARNING,
                        f"{server.name}: {days_left}d remaining",
                    )
                    if self._notifier and days_left <= _SSL_NTFY_DAYS:
                        await self._notifier.notify(
                            title="⚠️ SSL cert expiring soon",
                            message=f"{server.name} cert expires in {days_left} day(s).",
                            priority="high",
                            tags=["lock", "warning"],
                        )

    async def _check_server(
        self,
        server_id: int,
        name: str,
        address: str,
        port,
        server_type: str,
        check_params: dict | None = None,
    ) -> ServerCheckResult:
        checker = self._checker_registry.get(server_type) or self._checker_registry.get("http")
        if checker is None:
            logger.warning("No checker found for type %r (server %r)", server_type, name)
            return ServerCheckResult(server_id=server_id, name=name, is_up=False,
                                     error=f"No checker registered for type '{server_type}'")
        try:
            return await checker.check(server_id, name, address, port, check_params)
        except Exception as exc:
            logger.warning("Checker raised for server %r (%s): %s", name, server_id, exc)
            return ServerCheckResult(server_id=server_id, name=name, is_up=False, error=str(exc))
