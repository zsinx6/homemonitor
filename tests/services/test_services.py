"""Tests for services using mock repos and mock checkers."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import AsyncMock

import pytest

from app.domain import constants as C
from app.domain.pet import Pet, derive_status
from app.domain.server import ServerCheckResult
from app.services.monitor_service import MonitorService
from app.services.pet_service import PetService
from app.services.task_service import TaskService


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _default_pet(**kwargs) -> Pet:
    defaults = dict(
        id=1, name="Agumon", level=1, exp=0, max_exp=C.INITIAL_MAX_EXP,
        hp=C.HP_MAX, last_backup_date=None, last_interaction_date=_now(),
        last_event=None, last_updated=_now(),
    )
    defaults.update(kwargs)
    return Pet(**defaults)


# ---------------------------------------------------------------------------
# Mock infrastructure
# ---------------------------------------------------------------------------

@dataclass
class MockPetRepo:
    pet: Pet = field(default_factory=_default_pet)
    saved: list[Pet] = field(default_factory=list)

    async def get_pet(self, db):
        return self.pet

    async def save_pet(self, db, pet: Pet, *, commit: bool = True):
        self.pet = pet
        self.saved.append(pet)

    async def clear_last_event(self, db):
        self.pet = replace(self.pet, last_event=None)

    async def rename_pet(self, db, name: str):
        self.pet = replace(self.pet, name=name)
        return self.pet


@dataclass
class MockServerRepo:
    servers: list = field(default_factory=list)
    check_updates: list = field(default_factory=list)

    async def list_servers(self, db):
        return self.servers

    async def get_server(self, db, server_id):
        return next((s for s in self.servers if s.id == server_id), None)

    async def update_server_check_result(self, db, server_id, is_up, error, checked_at, **kwargs):
        self.check_updates.append((server_id, is_up, error))

    async def upsert_daily_stat(self, db, server_id, date_str, is_up, **kwargs):
        pass

    async def update_server_check_params(self, db, server_id, params):
        pass

    async def update_ssl_warning_date(self, db, server_id, warned_at):
        for s in self.servers:
            if s.id == server_id:
                s.last_ssl_warning_date = warned_at
                break


@dataclass
class MockTaskRepo:
    tasks: list = field(default_factory=list)
    completed: list = field(default_factory=list)

    async def get_task(self, db, task_id: int):
        return next((t for t in self.tasks if t.id == task_id), None)

    async def complete_task(self, db, task_id: int, *, commit: bool = True):
        task = next((t for t in self.tasks if t.id == task_id), None)
        if task:
            self.completed.append(task_id)
        return task


@dataclass
class FakeServer:
    id: int
    name: str
    address: str
    port: Optional[int]
    type: str
    status: str = "UP"
    maintenance_mode: bool = False
    check_params: Optional[dict] = None
    last_ssl_warning_date: Optional[datetime] = None


@dataclass
class FakeTask:
    id: int
    task: str
    is_completed: bool = False
    created_at: datetime = field(default_factory=_now)
    completed_at: Optional[datetime] = None


class MockDb:
    """Minimal async-compatible DB stub for services that call db.commit() directly."""
    async def commit(self):
        pass


# ---------------------------------------------------------------------------
# MonitorService tests
# ---------------------------------------------------------------------------

class TestMonitorService:
    def _make_service(self, servers, check_results, initial_pet=None):
        pet_repo = MockPetRepo(pet=initial_pet or _default_pet())
        server_repo = MockServerRepo(servers=servers)
        checkers = {
            "http": AsyncMock(return_value=None),
            "ping": AsyncMock(return_value=None),
        }
        # Override check to return specific results
        result_map = {r.server_id: r for r in check_results}

        async def mock_check(server_id, name, address, port, check_params=None):
            return result_map.get(server_id, ServerCheckResult(server_id, name, True, None))

        checkers["http"].check = mock_check
        checkers["ping"].check = mock_check

        service = MonitorService(
            pet_repo=pet_repo,
            server_repo=server_repo,
            http_checker=checkers["http"],
            ping_checker=checkers["ping"],
        )
        return service, pet_repo, server_repo

    async def test_all_up_gains_exp(self):
        server = FakeServer(id=1, name="nginx", address="http://x", port=None, type="http")
        result = ServerCheckResult(server_id=1, name="nginx", is_up=True, error=None)
        service, pet_repo, _ = self._make_service([server], [result])
        await service.run_cycle(db=None)
        assert pet_repo.pet.exp == C.EXP_PER_HEALTHY_CYCLE

    async def test_any_down_loses_hp(self):
        server = FakeServer(id=1, name="db", address="http://x", port=None, type="http",
                            status="UP")
        result = ServerCheckResult(server_id=1, name="db", is_up=False, error="timeout")
        service, pet_repo, _ = self._make_service([server], [result])
        await service.run_cycle(db=None)
        assert pet_repo.pet.hp == C.HP_MAX - C.HP_LOSS_PER_DOWN_CYCLE

    async def test_server_updates_are_persisted(self):
        server = FakeServer(id=1, name="nginx", address="http://x", port=None, type="http")
        result = ServerCheckResult(server_id=1, name="nginx", is_up=True, error=None)
        service, _, server_repo = self._make_service([server], [result])
        await service.run_cycle(db=None)
        assert len(server_repo.check_updates) == 1
        assert server_repo.check_updates[0][1] is True

    async def test_empty_server_list_does_not_crash(self):
        service, pet_repo, _ = self._make_service([], [])
        await service.run_cycle(db=None)
        # No servers → all up → gains EXP
        assert pet_repo.pet.exp == C.EXP_PER_HEALTHY_CYCLE

    async def test_recovery_detected_when_server_was_down(self):
        """If a server was DOWN and is now UP, HP recovery fires."""
        pet = _default_pet(hp=5)
        server = FakeServer(id=1, name="nginx", address="http://x", port=None,
                            type="http", status="DOWN")
        result = ServerCheckResult(server_id=1, name="nginx", is_up=True, error=None)
        service, pet_repo, _ = self._make_service([server], [result], initial_pet=pet)
        await service.run_cycle(db=None)
        assert pet_repo.pet.hp >= 5 + C.HP_GAIN_ON_RECOVERY

    async def test_persistent_down_server_drains_hp_every_cycle(self):
        """A server that stays DOWN should drain HP on every cycle."""
        pet = _default_pet(hp=C.HP_MAX)
        server = FakeServer(id=1, name="db", address="http://x", port=None,
                            type="http", status="DOWN")
        result = ServerCheckResult(server_id=1, name="db", is_up=False, error="timeout")
        service, pet_repo, _ = self._make_service([server], [result], initial_pet=pet)

        await service.run_cycle(db=None)
        hp_after_first = pet_repo.pet.hp
        assert hp_after_first == C.HP_MAX - C.HP_LOSS_PER_DOWN_CYCLE

        await service.run_cycle(db=None)
        hp_after_second = pet_repo.pet.hp
        assert hp_after_second == C.HP_MAX - 2 * C.HP_LOSS_PER_DOWN_CYCLE

    async def test_persistent_down_does_not_repeat_server_down_event(self):
        """server_down event fires once on transition; NOT on subsequent down cycles."""
        pet = _default_pet(hp=C.HP_MAX)
        server = FakeServer(id=1, name="api", address="http://x", port=None,
                            type="http", status="DOWN")
        result = ServerCheckResult(server_id=1, name="api", is_up=False, error="timeout")
        service, pet_repo, _ = self._make_service([server], [result], initial_pet=pet)

        # First cycle: server was UP (FakeServer default status is "DOWN" here,
        # but previous_statuses is built from the live list before checks).
        # Server was DOWN in DB already → no transition → event should be None.
        await service.run_cycle(db=None)
        assert pet_repo.pet.last_event is None

    async def test_new_down_transition_fires_server_down_event(self):
        """A server transitioning UP→DOWN fires last_event encoding the server name."""
        pet = _default_pet(hp=C.HP_MAX)
        # Server is currently UP in DB
        server = FakeServer(id=1, name="web", address="http://x", port=None,
                            type="http", status="UP")
        # But the check returns DOWN (new failure)
        result = ServerCheckResult(server_id=1, name="web", is_up=False, error="timeout")
        service, pet_repo, _ = self._make_service([server], [result], initial_pet=pet)
        await service.run_cycle(db=None)
        assert pet_repo.pet.last_event is not None
        assert pet_repo.pet.last_event.startswith("server_down:")

    async def test_check_single_updates_check_result(self):
        """check_single() persists check result for the target server."""
        server = FakeServer(id=3, name="solo", address="http://solo", port=None, type="http")
        result = ServerCheckResult(server_id=3, name="solo", is_up=True, error=None, latency_ms=42)
        service, _, server_repo = self._make_service([server], [result])
        await service.check_single(db=None, server_id=3)
        assert len(server_repo.check_updates) == 1
        sid, is_up, _ = server_repo.check_updates[0]
        assert sid == 3
        assert is_up is True

    async def test_check_single_unknown_server_is_noop(self):
        """check_single() with an unknown server_id does nothing."""
        service, _, server_repo = self._make_service([], [])
        await service.check_single(db=None, server_id=999)
        assert server_repo.check_updates == []

    async def test_check_single_does_not_affect_pet_hp(self):
        """check_single() never modifies pet state even when server is down."""
        server = FakeServer(id=4, name="db", address="http://db", port=None, type="http")
        result = ServerCheckResult(server_id=4, name="db", is_up=False, error="timeout")
        service, pet_repo, _ = self._make_service([server], [result])
        hp_before = pet_repo.pet.hp
        await service.check_single(db=None, server_id=4)
        assert pet_repo.pet.hp == hp_before  # pet untouched


# ---------------------------------------------------------------------------
# PetService tests
# ---------------------------------------------------------------------------

class TestPetService:
    def _make_service(self, initial_pet=None):
        pet_repo = MockPetRepo(pet=initial_pet or _default_pet())
        service = PetService(pet_repo=pet_repo)
        return service, pet_repo

    async def test_interact_gains_exp(self):
        # Pet last interacted longer ago than the cooldown so EXP is granted
        old = _now() - timedelta(seconds=C.INTERACT_COOLDOWN_SECONDS + 5)
        service, repo = self._make_service(_default_pet(last_interaction_date=old))
        pet, on_cooldown = await service.interact(db=None)
        assert pet.exp == C.EXP_INTERACT
        assert on_cooldown is False

    async def test_interact_heals_hp(self):
        old = _now() - timedelta(seconds=C.INTERACT_COOLDOWN_SECONDS + 5)
        service, repo = self._make_service(_default_pet(hp=5, last_interaction_date=old))
        pet, _ = await service.interact(db=None)
        assert pet.hp == min(5 + C.HP_GAIN_INTERACT, C.HP_MAX)

    async def test_interact_updates_interaction_date(self):
        old = _now().__class__.min.replace(tzinfo=timezone.utc)
        service, repo = self._make_service(_default_pet(last_interaction_date=old))
        pet, _ = await service.interact(db=None)
        assert pet.last_interaction_date > old

    async def test_backup_gains_exp_and_hp(self):
        service, repo = self._make_service(_default_pet(hp=5))
        pet, on_cooldown = await service.backup(db=None)
        assert pet.exp == C.EXP_BACKUP
        assert pet.hp == min(5 + C.HP_GAIN_BACKUP, C.HP_MAX)
        assert on_cooldown is False

    async def test_backup_sets_backup_date(self):
        service, repo = self._make_service()
        pet, _ = await service.backup(db=None)
        assert pet.last_backup_date is not None


    async def test_interact_within_cooldown_does_not_grant_exp(self):
        """Second interact within the cooldown window returns unchanged pet."""
        recent = _now() - timedelta(seconds=C.INTERACT_COOLDOWN_SECONDS // 2)
        service, repo = self._make_service(_default_pet(last_interaction_date=recent))
        pet, on_cooldown = await service.interact(db=None)
        assert pet.exp == 0  # unchanged
        assert on_cooldown is True

    async def test_interact_after_cooldown_grants_exp(self):
        """Interact after the cooldown period grants EXP normally."""
        old = _now() - timedelta(seconds=C.INTERACT_COOLDOWN_SECONDS + 5)
        service, repo = self._make_service(_default_pet(last_interaction_date=old))
        pet, on_cooldown = await service.interact(db=None)
        assert pet.exp == C.EXP_INTERACT
        assert on_cooldown is False

    async def test_interact_with_none_interaction_date_grants_exp(self):
        """Pet that has never been interacted with has no cooldown."""
        service, repo = self._make_service(_default_pet(last_interaction_date=None))
        pet, on_cooldown = await service.interact(db=None)
        assert pet.exp == C.EXP_INTERACT
        assert on_cooldown is False

    async def test_backup_on_cooldown_if_recently_backed_up(self):
        """Backup within BACKUP_COOLDOWN_HOURS returns on_cooldown=True."""
        recent_backup = _now() - timedelta(minutes=5)
        service, repo = self._make_service(_default_pet(last_backup_date=recent_backup))
        pet, on_cooldown = await service.backup(db=None)
        assert on_cooldown is True
        assert pet.exp == 0  # unchanged

    async def test_backup_not_on_cooldown_after_cooldown_expires(self):
        """Backup after BACKUP_COOLDOWN_HOURS returns on_cooldown=False."""
        old_backup = _now() - timedelta(hours=C.BACKUP_COOLDOWN_HOURS + 1)
        service, repo = self._make_service(_default_pet(last_backup_date=old_backup))
        pet, on_cooldown = await service.backup(db=None)
        assert on_cooldown is False
        assert pet.exp == C.EXP_BACKUP


# ---------------------------------------------------------------------------
# TaskService tests
# ---------------------------------------------------------------------------

class TestTaskService:
    def _make_service(self, tasks=None, initial_pet=None):
        pet_repo = MockPetRepo(pet=initial_pet or _default_pet())
        task_repo = MockTaskRepo(tasks=tasks or [])
        service = TaskService(pet_repo=pet_repo, task_repo=task_repo)
        return service, pet_repo, task_repo

    def _mock_db(self):
        db = AsyncMock()
        return db

    async def test_complete_task_grants_exp(self):
        task = FakeTask(id=1, task="Fix nginx")
        service, pet_repo, _ = self._make_service(tasks=[task])
        await service.complete_task(db=self._mock_db(), task_id=1)
        assert pet_repo.pet.exp == C.EXP_COMPLETE_TASK

    async def test_complete_task_grants_hp(self):
        task = FakeTask(id=1, task="Fix nginx")
        service, pet_repo, _ = self._make_service(tasks=[task], initial_pet=_default_pet(hp=5))
        await service.complete_task(db=self._mock_db(), task_id=1)
        assert pet_repo.pet.hp == min(5 + C.HP_GAIN_COMPLETE_TASK, C.HP_MAX)

    async def test_complete_nonexistent_task_returns_none(self):
        service, pet_repo, _ = self._make_service(tasks=[])
        result = await service.complete_task(db=self._mock_db(), task_id=999)
        assert result is None
        assert pet_repo.pet.exp == 0  # no change

    async def test_complete_task_sets_task_done_event(self):
        task = FakeTask(id=1, task="Fix nginx")
        service, pet_repo, _ = self._make_service(tasks=[task])
        await service.complete_task(db=self._mock_db(), task_id=1)
        assert pet_repo.pet.last_event == "task_done"


# ---------------------------------------------------------------------------
# Domain edge case tests
# ---------------------------------------------------------------------------

class TestPetDomainEdgeCases:
    def _base_pet(self, **kwargs):
        return _default_pet(**kwargs)

    def test_multiple_servers_down_event_encodes_all_names(self):
        """All down server names should appear in the last_event (up to 3)."""
        from app.domain.pet import apply_monitor_cycle
        pet = self._base_pet()
        updated = apply_monitor_cycle(
            pet,
            down_server_names=["db", "cache", "nginx"],
            recovered_server_names=[],
        )
        assert updated.last_event is not None
        assert updated.last_event.startswith("server_down:")
        detail = updated.last_event.split(":", 1)[1]
        assert "db" in detail
        assert "cache" in detail
        assert "nginx" in detail

    def test_four_plus_servers_down_shows_overflow(self):
        """With 4+ servers down, the detail should mention overflow count."""
        from app.domain.pet import apply_monitor_cycle
        pet = self._base_pet()
        updated = apply_monitor_cycle(
            pet,
            down_server_names=["a", "b", "c", "d"],
            recovered_server_names=[],
        )
        detail = updated.last_event.split(":", 1)[1]
        assert "+1 more" in detail

    def test_single_server_down_event_has_name(self):
        """Single server down: event detail is just the server name."""
        from app.domain.pet import apply_monitor_cycle
        pet = self._base_pet()
        updated = apply_monitor_cycle(
            pet,
            down_server_names=["redis"],
            recovered_server_names=[],
        )
        assert updated.last_event == "server_down:redis"

    def test_hp_drain_scales_with_server_count(self):
        """Three servers down should drain 3x HP_LOSS_PER_DOWN_CYCLE per cycle."""
        from app.domain.pet import apply_monitor_cycle
        pet = self._base_pet(hp=C.HP_MAX)
        updated = apply_monitor_cycle(
            pet,
            down_server_names=["a", "b", "c"],
            recovered_server_names=[],
        )
        expected_hp = max(0, C.HP_MAX - 3 * C.HP_LOSS_PER_DOWN_CYCLE)
        assert updated.hp == expected_hp

    def test_dead_pet_frozen_during_monitor_cycle(self):
        """A dead pet should not gain or lose HP/EXP during a monitor cycle."""
        from app.domain.pet import apply_monitor_cycle
        from dataclasses import replace
        pet = replace(self._base_pet(), is_dead=True, hp=0)
        updated = apply_monitor_cycle(pet, down_server_names=["db"], recovered_server_names=[])
        assert updated.hp == 0
        assert updated.exp == 0
        assert updated.is_dead is True

    def test_backup_overdue_drain_applied_after_30_days(self):
        """Backup overdue: HP should drain every cycle after 30 days."""
        from datetime import timedelta
        from app.domain.pet import apply_monitor_cycle
        old_backup = datetime.now(timezone.utc) - timedelta(days=31)
        pet = self._base_pet(hp=C.HP_MAX, last_backup_date=old_backup,
                             last_interaction_date=datetime.now(timezone.utc))
        updated = apply_monitor_cycle(pet, down_server_names=[], recovered_server_names=[])
        assert updated.hp < C.HP_MAX  # drain applied

    def test_no_backup_overdue_drain_before_30_days(self):
        """Backup NOT overdue: no drain for recent backup."""
        from datetime import timedelta
        from app.domain.pet import apply_monitor_cycle
        recent_backup = datetime.now(timezone.utc) - timedelta(days=5)
        pet = self._base_pet(hp=C.HP_MAX, last_backup_date=recent_backup,
                             last_interaction_date=datetime.now(timezone.utc))
        updated = apply_monitor_cycle(pet, down_server_names=[], recovered_server_names=[])
        assert updated.hp == C.HP_MAX  # no drain (healthy cycle gains nothing for HP)

    def test_never_backed_up_no_drain(self):
        """Pet that has NEVER been backed up should NOT drain HP (incentive to do first backup)."""
        from app.domain.pet import apply_monitor_cycle
        pet = self._base_pet(hp=C.HP_MAX, last_backup_date=None,
                             last_interaction_date=datetime.now(timezone.utc))
        updated = apply_monitor_cycle(pet, down_server_names=[], recovered_server_names=[])
        assert updated.hp == C.HP_MAX  # no drain


class TestMonitorServiceMaintenanceRecovery:
    def _make_service(self, servers, check_results, initial_pet=None):
        pet_repo_inst = MockPetRepo(pet=initial_pet or _default_pet(hp=5))
        server_repo_inst = MockServerRepo(servers=servers)
        result_map = {r.server_id: r for r in check_results}

        async def mock_check(server_id, name, address, port, check_params=None):
            return result_map.get(server_id, ServerCheckResult(server_id, name, True, None))

        from unittest.mock import MagicMock
        http_checker = MagicMock()
        http_checker.check = mock_check
        ping_checker = MagicMock()
        ping_checker.check = mock_check

        service = MonitorService(
            pet_repo=pet_repo_inst,
            server_repo=server_repo_inst,
            http_checker=http_checker,
            ping_checker=ping_checker,
        )
        return service, pet_repo_inst

    async def test_maintenance_server_recovery_does_not_give_hp(self):
        """A maintenance server transitioning DOWN→UP should NOT trigger HP recovery."""
        pet = _default_pet(hp=5)
        # Maintenance server that was DOWN
        server = FakeServer(id=1, name="maint-db", address="192.168.1.5", port=None,
                            type="ping", status="DOWN", maintenance_mode=True)
        # Check returns UP (recovery transition)
        result = ServerCheckResult(server_id=1, name="maint-db", is_up=True, error=None)
        service, pet_repo = self._make_service([server], [result], initial_pet=pet)
        await service.run_cycle(db=None)
        # HP should NOT increase from maintenance server recovery
        assert pet_repo.pet.hp == 5  # unchanged (no recovery event, no EXP either since it was down)

    async def test_maintenance_server_down_does_not_drain_hp(self):
        """A maintenance server that is DOWN should not drain pet HP."""
        pet = _default_pet(hp=C.HP_MAX, last_interaction_date=datetime.now(timezone.utc))
        server = FakeServer(id=1, name="maint-db", address="192.168.1.5", port=None,
                            type="ping", status="UP", maintenance_mode=True)
        result = ServerCheckResult(server_id=1, name="maint-db", is_up=False, error="timeout")
        service, pet_repo = self._make_service([server], [result], initial_pet=pet)
        await service.run_cycle(db=None)
        # HP should not decrease because server is in maintenance
        assert pet_repo.pet.hp == C.HP_MAX


# ═══════════════════════════════════════════════════════════════════════════════
# Memory recording tests
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class MockMemoryRepo:
    """Collects add_memory calls for assertion."""
    calls: list = field(default_factory=list)

    async def add_memory(self, db, event_type, detail=None, occurred_at=None):
        self.calls.append({"event_type": event_type, "detail": detail})


class TestPetServiceMemoryRecording:
    def _make_service(self, pet, memory_repo):
        return PetService(pet_repo=MockPetRepo(pet=pet), memory_repo=memory_repo)

    async def test_backup_records_backup_memory(self):
        mem = MockMemoryRepo()
        svc = self._make_service(_default_pet(hp=C.HP_MAX), mem)
        await svc.backup(db=None)
        types = [c["event_type"] for c in mem.calls]
        assert "backup" in types

    async def test_revive_records_revival_memory(self):
        mem = MockMemoryRepo()
        pet = _default_pet(hp=0)
        pet = replace(pet, is_dead=True)
        svc = self._make_service(pet, mem)
        await svc.revive(db=None)
        types = [c["event_type"] for c in mem.calls]
        assert "revival" in types

    async def test_no_memory_when_no_repo(self):
        svc = self._make_service(_default_pet(), memory_repo=None)
        # Should not raise even without memory_repo
        await svc.backup(db=None)


class TestTaskServiceMemoryRecording:
    def _make_service(self, pet, memory_repo):
        task_repo = MockTaskRepo(tasks=[FakeTask(id=1, task="Deploy nginx", is_completed=False)])
        return TaskService(
            pet_repo=MockPetRepo(pet=pet),
            task_repo=task_repo,
            memory_repo=memory_repo,
        )

    async def test_complete_task_records_task_complete(self):
        mem = MockMemoryRepo()
        svc = self._make_service(_default_pet(), mem)
        await svc.complete_task(db=MockDb(), task_id=1)
        types = [c["event_type"] for c in mem.calls]
        assert "task_complete" in types
        details = [c["detail"] for c in mem.calls if c["event_type"] == "task_complete"]
        assert "Deploy nginx" in details

    async def test_no_memory_when_no_repo(self):
        svc = self._make_service(_default_pet(), memory_repo=None)
        await svc.complete_task(db=MockDb(), task_id=1)


class TestMonitorServiceMemoryRecording:
    def _make_service(self, servers, check_results, initial_pet=None, memory_repo=None):
        pet_repo_inst = MockPetRepo(pet=initial_pet or _default_pet())
        server_repo_inst = MockServerRepo(servers=servers)
        result_map = {r.server_id: r for r in check_results}

        async def mock_check(server_id, name, address, port, check_params=None):
            return result_map.get(server_id, ServerCheckResult(server_id, name, True, None))

        from unittest.mock import MagicMock
        http_checker = MagicMock()
        http_checker.check = mock_check
        ping_checker = MagicMock()
        ping_checker.check = mock_check

        svc = MonitorService(
            pet_repo=pet_repo_inst,
            server_repo=server_repo_inst,
            http_checker=http_checker,
            ping_checker=ping_checker,
            memory_repo=memory_repo,
        )
        return svc, pet_repo_inst

    async def test_server_down_records_memory(self):
        mem = MockMemoryRepo()
        server = FakeServer(id=1, name="nginx", address="http://x", port=80,
                            type="http", status="UP", maintenance_mode=False)
        result = ServerCheckResult(server_id=1, name="nginx", is_up=False, error="timeout")
        svc, _ = self._make_service([server], [result], memory_repo=mem)
        await svc.run_cycle(db=None)
        types = [c["event_type"] for c in mem.calls]
        assert "server_down" in types
        details = [c["detail"] for c in mem.calls if c["event_type"] == "server_down"]
        assert "nginx" in details

    async def test_server_recovery_records_memory(self):
        mem = MockMemoryRepo()
        server = FakeServer(id=1, name="nginx", address="http://x", port=80,
                            type="http", status="DOWN", maintenance_mode=False)
        result = ServerCheckResult(server_id=1, name="nginx", is_up=True, error=None)
        svc, _ = self._make_service([server], [result], memory_repo=mem)
        await svc.run_cycle(db=None)
        types = [c["event_type"] for c in mem.calls]
        assert "server_recovery" in types

    async def test_no_memory_when_no_repo(self):
        server = FakeServer(id=1, name="nginx", address="http://x", port=80,
                            type="http", status="UP", maintenance_mode=False)
        result = ServerCheckResult(server_id=1, name="nginx", is_up=False, error="timeout")
        svc, _ = self._make_service([server], [result], memory_repo=None)
        # Should not raise
        await svc.run_cycle(db=None)


# ═══════════════════════════════════════════════════════════════════════════════
# PetService dead-pet guard tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestPetServiceDeadGuards:
    def _dead_pet(self):
        return replace(_default_pet(hp=0), is_dead=True)

    async def test_interact_when_dead_returns_on_cooldown(self):
        """Dead pet cannot be interacted with — returns on_cooldown=True."""
        svc = PetService(pet_repo=MockPetRepo(pet=self._dead_pet()))
        pet, on_cooldown = await svc.interact(db=None)
        assert on_cooldown is True
        assert pet.exp == 0  # unchanged

    async def test_interact_when_dead_does_not_save(self):
        """Dead pet interact must not save any state change."""
        repo = MockPetRepo(pet=self._dead_pet())
        svc = PetService(pet_repo=repo)
        await svc.interact(db=None)
        assert len(repo.saved) == 0

    async def test_backup_when_dead_returns_on_cooldown(self):
        """Dead pet backup is blocked — returns on_cooldown=True."""
        svc = PetService(pet_repo=MockPetRepo(pet=self._dead_pet()))
        pet, on_cooldown = await svc.backup(db=None)
        assert on_cooldown is True

    async def test_backup_when_dead_does_not_save(self):
        """Dead pet backup must not save any state change."""
        repo = MockPetRepo(pet=self._dead_pet())
        svc = PetService(pet_repo=repo)
        await svc.backup(db=None)
        assert len(repo.saved) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# PetService rename + clear_last_event tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestPetServiceRename:
    async def test_rename_updates_name(self):
        repo = MockPetRepo(pet=_default_pet())
        # MockPetRepo.rename_pet must be wired
        repo.rename_pet = AsyncMock(return_value=replace(_default_pet(), name="Zippymon"))
        svc = PetService(pet_repo=repo)
        pet = await svc.rename(db=None, name="Zippymon")
        assert pet.name == "Zippymon"

    async def test_rename_records_rename_memory(self):
        mem = MockMemoryRepo()
        repo = MockPetRepo(pet=_default_pet())
        repo.rename_pet = AsyncMock(return_value=replace(_default_pet(), name="Zippymon"))
        svc = PetService(pet_repo=repo, memory_repo=mem)
        await svc.rename(db=None, name="Zippymon")
        types = [c["event_type"] for c in mem.calls]
        assert "rename" in types

    async def test_clear_last_event_delegates_to_repo(self):
        repo = MockPetRepo(pet=replace(_default_pet(), last_event="level_up"))
        svc = PetService(pet_repo=repo)
        await svc.clear_last_event(db=None)
        assert repo.pet.last_event is None


# ═══════════════════════════════════════════════════════════════════════════════
# TaskService edge case: already-completed task
# ═══════════════════════════════════════════════════════════════════════════════

class TestTaskServiceEdgeCases:
    def _make_service(self, tasks=None):
        pet_repo = MockPetRepo(pet=_default_pet())
        task_repo = MockTaskRepo(tasks=tasks or [])
        return TaskService(pet_repo=pet_repo, task_repo=task_repo), pet_repo, task_repo

    async def test_complete_already_completed_task_returns_none(self):
        """complete_task on an already-completed task returns None; pet unchanged."""
        task = FakeTask(id=1, task="done already", is_completed=True)
        # MockTaskRepo.complete_task returns None for already-completed tasks
        # because the underlying repo only returns the task if it finds it in `tasks`
        # We simulate: repo returns None (task not found or already done)
        task_repo = MockTaskRepo(tasks=[])  # not in pending list → returns None
        pet_repo = MockPetRepo(pet=_default_pet())
        svc = TaskService(pet_repo=pet_repo, task_repo=task_repo)
        result = await svc.complete_task(db=AsyncMock(), task_id=1)
        assert result is None
        assert pet_repo.pet.exp == 0  # no EXP granted

    async def test_complete_task_records_task_complete_memory(self):
        mem = MockMemoryRepo()
        task = FakeTask(id=1, task="Add monitoring")
        pet_repo = MockPetRepo(pet=_default_pet())
        task_repo = MockTaskRepo(tasks=[task])
        svc = TaskService(pet_repo=pet_repo, task_repo=task_repo, memory_repo=mem)
        await svc.complete_task(db=AsyncMock(), task_id=1)
        types = [c["event_type"] for c in mem.calls]
        assert "task_complete" in types


# ═══════════════════════════════════════════════════════════════════════════════
# MonitorService: checker raises exception
# ═══════════════════════════════════════════════════════════════════════════════

class TestMonitorServiceCheckerException:
    def _make_service_with_failing_checker(self, servers):
        pet_repo = MockPetRepo(pet=_default_pet())
        server_repo = MockServerRepo(servers=servers)

        async def failing_check(server_id, name, address, port, check_params=None):
            raise RuntimeError("network unreachable")

        from unittest.mock import MagicMock
        http_checker = MagicMock()
        http_checker.check = failing_check
        ping_checker = MagicMock()
        ping_checker.check = failing_check

        svc = MonitorService(
            pet_repo=pet_repo,
            server_repo=server_repo,
            http_checker=http_checker,
            ping_checker=ping_checker,
        )
        return svc, pet_repo

    async def test_checker_exception_treated_as_down(self):
        """If the checker raises, the server should be treated as DOWN (HP drains)."""
        server = FakeServer(id=1, name="flaky", address="http://x", port=None,
                            type="http", status="UP")
        svc, pet_repo = self._make_service_with_failing_checker([server])
        await svc.run_cycle(db=None)
        # Server treated as DOWN → HP should decrease
        assert pet_repo.pet.hp < C.HP_MAX


# ═══════════════════════════════════════════════════════════════════════════════
# TcpChecker unit tests
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestTcpChecker:
    async def test_no_port_returns_down(self):
        from app.infrastructure.checkers.tcp_checker import TcpChecker
        checker = TcpChecker()
        result = await checker.check(1, "db", "192.168.1.1", None)
        assert not result.is_up
        assert "port" in result.error.lower()

    async def test_connection_refused_returns_down(self):
        """Connecting to a closed port should return DOWN."""
        from app.infrastructure.checkers.tcp_checker import TcpChecker
        checker = TcpChecker()
        # Port 1 is almost certainly closed/refused
        result = await checker.check(1, "test", "127.0.0.1", 1)
        assert not result.is_up

    async def test_successful_connection_returns_up(self):
        """A listening server should return UP."""
        import asyncio
        from app.infrastructure.checkers.tcp_checker import TcpChecker

        async def _echo_handler(reader, writer):
            writer.close()

        server = await asyncio.start_server(_echo_handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        async with server:
            checker = TcpChecker()
            result = await checker.check(1, "test", "127.0.0.1", port)
        assert result.is_up


# ═══════════════════════════════════════════════════════════════════════════════
# HttpKeywordChecker unit tests
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestHttpKeywordChecker:
    async def test_keyword_found_returns_up(self):
        from unittest.mock import patch, AsyncMock, MagicMock
        from app.infrastructure.checkers.http_keyword_checker import HttpKeywordChecker

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "Welcome to Python"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("app.infrastructure.checkers.http_keyword_checker.httpx.AsyncClient",
                   return_value=mock_client):
            checker = HttpKeywordChecker()
            result = await checker.check(1, "site", "http://example.com", None,
                                         check_params={"keyword": "Python"})
        assert result.is_up

    async def test_keyword_not_found_returns_down(self):
        from unittest.mock import patch, AsyncMock, MagicMock
        from app.infrastructure.checkers.http_keyword_checker import HttpKeywordChecker

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "Under construction"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("app.infrastructure.checkers.http_keyword_checker.httpx.AsyncClient",
                   return_value=mock_client):
            checker = HttpKeywordChecker()
            result = await checker.check(1, "site", "http://example.com", None,
                                         check_params={"keyword": "Python"})
        assert not result.is_up
        assert "Python" in result.error

    async def test_http_error_returns_down(self):
        from unittest.mock import patch, AsyncMock, MagicMock
        from app.infrastructure.checkers.http_keyword_checker import HttpKeywordChecker

        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.text = "Service unavailable"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("app.infrastructure.checkers.http_keyword_checker.httpx.AsyncClient",
                   return_value=mock_client):
            checker = HttpKeywordChecker()
            result = await checker.check(1, "site", "http://example.com", None,
                                         check_params={"keyword": "OK"})
        assert not result.is_up
        assert "503" in result.error

    async def test_case_insensitive_match(self):
        from unittest.mock import patch, AsyncMock, MagicMock
        from app.infrastructure.checkers.http_keyword_checker import HttpKeywordChecker

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "PYTHON IS GREAT"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("app.infrastructure.checkers.http_keyword_checker.httpx.AsyncClient",
                   return_value=mock_client):
            checker = HttpKeywordChecker()
            result = await checker.check(1, "site", "http://example.com", None,
                                         check_params={"keyword": "python"})
        assert result.is_up

    async def test_no_keyword_accepts_any_2xx(self):
        from unittest.mock import patch, AsyncMock, MagicMock
        from app.infrastructure.checkers.http_keyword_checker import HttpKeywordChecker

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "anything"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("app.infrastructure.checkers.http_keyword_checker.httpx.AsyncClient",
                   return_value=mock_client):
            checker = HttpKeywordChecker()
            result = await checker.check(1, "site", "http://example.com", None,
                                         check_params={})
        assert result.is_up


# ═══════════════════════════════════════════════════════════════════════════════
# HttpChecker: expected_status param
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestHttpCheckerCheckParams:
    async def test_expected_status_match(self):
        from unittest.mock import patch, AsyncMock, MagicMock
        from app.infrastructure.checkers.http_checker import HttpChecker

        mock_response = MagicMock()
        mock_response.status_code = 301

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("app.infrastructure.checkers.http_checker.httpx.AsyncClient",
                   return_value=mock_client):
            checker = HttpChecker()
            result = await checker.check(1, "site", "http://example.com", None,
                                         check_params={"expected_status": [200, 301]})
        assert result.is_up

    async def test_expected_status_mismatch_returns_down(self):
        from unittest.mock import patch, AsyncMock, MagicMock
        from app.infrastructure.checkers.http_checker import HttpChecker

        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("app.infrastructure.checkers.http_checker.httpx.AsyncClient",
                   return_value=mock_client):
            checker = HttpChecker()
            result = await checker.check(1, "site", "http://example.com", None,
                                         check_params={"expected_status": [200, 201]})
        assert not result.is_up


# ─── check_single edge cases ────────────────────────────────────────────────

class TestCheckSingleEdgeCases:
    """Additional check_single scenarios: exception handling and maintenance mode."""

    def _make_service_with_raising_checker(self, servers, exc):
        pet_repo = MockPetRepo(pet=_default_pet())
        srv_repo = MockServerRepo(servers=servers)
        checker = AsyncMock(return_value=None)

        async def raising_check(server_id, name, address, port, check_params=None):
            raise exc

        checker.check = raising_check
        service = MonitorService(
            pet_repo=pet_repo,
            server_repo=srv_repo,
            http_checker=checker,
            ping_checker=checker,
        )
        return service, pet_repo, srv_repo

    async def test_checker_exception_marks_server_down(self):
        """If checker raises, check_single records DOWN; no unhandled error."""
        server = FakeServer(id=5, name="flaky", address="http://flaky", port=None, type="http")
        service, _, srv_repo = self._make_service_with_raising_checker(
            [server], RuntimeError("network unreachable")
        )
        await service.check_single(db=None, server_id=5)
        assert len(srv_repo.check_updates) == 1
        _, is_up, _ = srv_repo.check_updates[0]
        assert is_up is False

    async def test_checker_exception_pet_unchanged(self):
        """Checker exception must not modify pet HP or EXP."""
        server = FakeServer(id=6, name="ghost", address="http://ghost", port=None, type="http")
        service, pet_repo, _ = self._make_service_with_raising_checker(
            [server], ConnectionError("refused")
        )
        hp_before, exp_before = pet_repo.pet.hp, pet_repo.pet.exp
        await service.check_single(db=None, server_id=6)
        assert pet_repo.pet.hp == hp_before
        assert pet_repo.pet.exp == exp_before

    async def test_maintenance_server_check_single_pet_unchanged(self):
        """check_single on a maintenance_mode server never modifies pet state."""
        server = FakeServer(id=7, name="maint", address="http://m", port=None,
                            type="http", status="UP", maintenance_mode=True)
        result = ServerCheckResult(server_id=7, name="maint", is_up=False, error="down")
        pet_repo = MockPetRepo(pet=_default_pet())
        srv_repo = MockServerRepo(servers=[server])
        checker = AsyncMock(return_value=None)

        async def mock_check(server_id, name, address, port, check_params=None):
            return result

        checker.check = mock_check
        service = MonitorService(
            pet_repo=pet_repo,
            server_repo=srv_repo,
            http_checker=checker,
            ping_checker=checker,
        )
        hp_before = pet_repo.pet.hp
        await service.check_single(db=None, server_id=7)
        assert pet_repo.pet.hp == hp_before


# ═══════════════════════════════════════════════════════════════════════════════
# check_down_servers: fast recovery poller
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckDownServers:
    """Tests for MonitorService.check_down_servers() — the 0.5 s recovery poller."""

    def _make_service(
        self,
        servers,
        check_results,
        initial_pet=None,
        memory_repo=None,
        notifier=None,
        notify_on_recovery=False,
    ):
        pet_repo = MockPetRepo(pet=initial_pet or _default_pet())
        server_repo = MockServerRepo(servers=servers)
        result_map = {r.server_id: r for r in check_results}

        async def mock_check(server_id, name, address, port, check_params=None):
            return result_map.get(server_id, ServerCheckResult(server_id, name, True, None))

        from unittest.mock import MagicMock
        http_checker = MagicMock()
        http_checker.check = mock_check

        svc = MonitorService(
            pet_repo=pet_repo,
            server_repo=server_repo,
            http_checker=http_checker,
            memory_repo=memory_repo,
            notifier=notifier,
            notify_on_recovery=notify_on_recovery,
        )
        return svc, pet_repo, server_repo

    async def test_no_down_servers_is_noop(self):
        """When all servers are UP, check_down_servers does not call the checker."""
        server = FakeServer(id=1, name="nginx", address="http://x", port=None,
                            type="http", status="UP")
        svc, pet_repo, server_repo = self._make_service([server], [])
        hp_before = pet_repo.pet.hp
        await svc.check_down_servers(db=None)
        assert server_repo.check_updates == []
        assert pet_repo.pet.hp == hp_before

    async def test_down_server_stays_down_updates_db_but_not_pet(self):
        """A DOWN server that remains DOWN: DB is NOT updated (avoids stat inflation), pet unchanged."""
        server = FakeServer(id=1, name="db", address="http://x", port=None,
                            type="http", status="DOWN")
        result = ServerCheckResult(server_id=1, name="db", is_up=False, error="timeout")
        svc, pet_repo, server_repo = self._make_service([server], [result])
        hp_before = pet_repo.pet.hp
        await svc.check_down_servers(db=None)
        assert server_repo.check_updates == []  # still-DOWN servers are not written
        assert pet_repo.pet.hp == hp_before

    async def test_down_server_recovered_updates_db_and_restores_hp(self):
        """A DOWN server that comes back UP: DB updated and pet gains HP."""
        pet = _default_pet(hp=5)
        server = FakeServer(id=1, name="api", address="http://x", port=None,
                            type="http", status="DOWN")
        result = ServerCheckResult(server_id=1, name="api", is_up=True, error=None)
        svc, pet_repo, server_repo = self._make_service([server], [result], initial_pet=pet)
        await svc.check_down_servers(db=None)
        assert len(server_repo.check_updates) == 1
        _, is_up, _ = server_repo.check_updates[0]
        assert is_up is True
        assert pet_repo.pet.hp >= 5 + C.HP_GAIN_ON_RECOVERY

    async def test_maintenance_down_server_is_excluded(self):
        """Maintenance-mode DOWN servers are skipped entirely."""
        server = FakeServer(id=1, name="maint", address="http://x", port=None,
                            type="http", status="DOWN", maintenance_mode=True)
        svc, pet_repo, server_repo = self._make_service([server], [])
        hp_before = pet_repo.pet.hp
        await svc.check_down_servers(db=None)
        assert server_repo.check_updates == []
        assert pet_repo.pet.hp == hp_before

    async def test_only_down_servers_are_checked(self):
        """UP servers are never passed to the checker; only DOWN ones are.
        Only recovered servers (DOWN→UP) get a DB write."""
        up_server = FakeServer(id=1, name="up", address="http://x", port=None,
                               type="http", status="UP")
        down_server = FakeServer(id=2, name="down", address="http://y", port=None,
                                 type="http", status="DOWN")
        result = ServerCheckResult(server_id=2, name="down", is_up=False, error="timeout")
        svc, _, server_repo = self._make_service([up_server, down_server], [result])
        await svc.check_down_servers(db=None)
        # DOWN server that stays DOWN → no DB write (avoids stat inflation)
        assert server_repo.check_updates == []

    async def test_recovery_records_memory(self):
        """Recovery via check_down_servers records a SERVER_RECOVERY memory."""
        mem = MockMemoryRepo()
        server = FakeServer(id=1, name="nginx", address="http://x", port=None,
                            type="http", status="DOWN")
        result = ServerCheckResult(server_id=1, name="nginx", is_up=True, error=None)
        svc, _, _ = self._make_service([server], [result], memory_repo=mem)
        await svc.check_down_servers(db=None)
        types = [c["event_type"] for c in mem.calls]
        assert "server_recovery" in types

    async def test_no_memory_recorded_when_still_down(self):
        """No memory event when a DOWN server stays DOWN."""
        mem = MockMemoryRepo()
        server = FakeServer(id=1, name="db", address="http://x", port=None,
                            type="http", status="DOWN")
        result = ServerCheckResult(server_id=1, name="db", is_up=False, error="timeout")
        svc, _, _ = self._make_service([server], [result], memory_repo=mem)
        await svc.check_down_servers(db=None)
        assert mem.calls == []

    async def test_recovery_notification_sent_when_enabled(self):
        """Recovery notification is sent when notify_on_recovery=True."""
        from unittest.mock import AsyncMock as _AsyncMock
        notifier = _AsyncMock()
        notifier.notify = _AsyncMock()
        server = FakeServer(id=1, name="nginx", address="http://x", port=None,
                            type="http", status="DOWN")
        result = ServerCheckResult(server_id=1, name="nginx", is_up=True, error=None)
        svc, _, _ = self._make_service([server], [result],
                                       notifier=notifier, notify_on_recovery=True)
        await svc.check_down_servers(db=None)
        notifier.notify.assert_called_once()

    async def test_recovery_notification_suppressed_when_disabled(self):
        """Recovery notification is NOT sent when notify_on_recovery=False."""
        from unittest.mock import AsyncMock as _AsyncMock
        notifier = _AsyncMock()
        notifier.notify = _AsyncMock()
        server = FakeServer(id=1, name="nginx", address="http://x", port=None,
                            type="http", status="DOWN")
        result = ServerCheckResult(server_id=1, name="nginx", is_up=True, error=None)
        svc, _, _ = self._make_service([server], [result],
                                       notifier=notifier, notify_on_recovery=False)
        await svc.check_down_servers(db=None)
        notifier.notify.assert_not_called()

    async def test_multiple_recoveries_in_one_tick(self):
        """Multiple DOWN servers recovering simultaneously all gain HP and memory."""
        mem = MockMemoryRepo()
        pet = _default_pet(hp=3)
        servers = [
            FakeServer(id=1, name="api",   address="http://a", port=None, type="http", status="DOWN"),
            FakeServer(id=2, name="cache", address="http://b", port=None, type="http", status="DOWN"),
        ]
        results = [
            ServerCheckResult(server_id=1, name="api",   is_up=True, error=None),
            ServerCheckResult(server_id=2, name="cache", is_up=True, error=None),
        ]
        svc, pet_repo, _ = self._make_service(servers, results,
                                              initial_pet=pet, memory_repo=mem)
        await svc.check_down_servers(db=None)
        recovery_events = [c for c in mem.calls if c["event_type"] == "server_recovery"]
        assert len(recovery_events) == 2
        assert pet_repo.pet.hp >= 3 + 2 * C.HP_GAIN_ON_RECOVERY

    async def test_exp_not_awarded_when_other_servers_still_down(self):
        """Recovery of one server must not award EXP_PER_HEALTHY_CYCLE when others remain DOWN."""
        pet = _default_pet(hp=5, exp=0)
        servers = [
            FakeServer(id=1, name="api",   address="http://a", port=None, type="http", status="DOWN"),
            FakeServer(id=2, name="cache", address="http://b", port=None, type="http", status="DOWN"),
        ]
        results = [
            ServerCheckResult(server_id=1, name="api",   is_up=True,  error=None),   # recovered
            ServerCheckResult(server_id=2, name="cache", is_up=False, error="down"),  # still down
        ]
        svc, pet_repo, _ = self._make_service(servers, results, initial_pet=pet)
        await svc.check_down_servers(db=None)
        # HP gain for the recovered server is correct
        assert pet_repo.pet.hp >= 5 + C.HP_GAIN_ON_RECOVERY
        # But EXP must NOT be awarded — cache is still down
        assert pet_repo.pet.exp == 0

    async def test_dead_pet_hp_not_changed_on_recovery(self):
        """A dead pet's HP must not be modified even when a server recovers."""
        from dataclasses import replace as _replace
        dead_pet = _replace(_default_pet(hp=0), is_dead=True)
        server = FakeServer(id=1, name="api", address="http://x", port=None,
                            type="http", status="DOWN")
        result = ServerCheckResult(server_id=1, name="api", is_up=True, error=None)
        svc, pet_repo, _ = self._make_service([server], [result], initial_pet=dead_pet)
        await svc.check_down_servers(db=None)
        # Pet must stay dead and untouched
        assert pet_repo.pet.hp == 0
        assert pet_repo.pet.is_dead is True
        assert len(pet_repo.saved) == 0  # save_pet must not have been called

    async def test_dead_pet_memory_and_notification_still_fire(self):
        """Memory and notification still happen even when the pet is dead."""
        from dataclasses import replace as _replace
        from unittest.mock import AsyncMock as _AsyncMock
        mem = MockMemoryRepo()
        notifier = _AsyncMock()
        notifier.notify = _AsyncMock()
        dead_pet = _replace(_default_pet(hp=0), is_dead=True)
        server = FakeServer(id=1, name="api", address="http://x", port=None,
                            type="http", status="DOWN")
        result = ServerCheckResult(server_id=1, name="api", is_up=True, error=None)
        svc, _, _ = self._make_service([server], [result], initial_pet=dead_pet,
                                       memory_repo=mem, notifier=notifier,
                                       notify_on_recovery=True)
        await svc.check_down_servers(db=None)
        assert any(c["event_type"] == "server_recovery" for c in mem.calls)
        notifier.notify.assert_called_once()

    async def test_recovery_hp_clamped_at_hp_max(self):
        """HP gain from recovery is clamped and never exceeds HP_MAX."""
        pet = _default_pet(hp=C.HP_MAX)  # already full
        server = FakeServer(id=1, name="api", address="http://x", port=None,
                            type="http", status="DOWN")
        result = ServerCheckResult(server_id=1, name="api", is_up=True, error=None)
        svc, pet_repo, _ = self._make_service([server], [result], initial_pet=pet)
        await svc.check_down_servers(db=None)
        assert pet_repo.pet.hp == C.HP_MAX  # no overflow

    async def test_no_double_recovery_when_run_cycle_follows_fast_loop(self):
        """After fast loop marks a server UP, run_cycle must NOT apply recovery HP again.

        Simulates the state after check_down_servers has already written status=UP
        to DB: the server list shows UP, and the check also returns UP → no
        DOWN→UP transition → no extra HP recovery from run_cycle.
        """
        pet = _default_pet(hp=5)
        # Server already shows UP in DB (check_down_servers already ran)
        server = FakeServer(id=1, name="api", address="http://x", port=None,
                            type="http", status="UP")
        result = ServerCheckResult(server_id=1, name="api", is_up=True, error=None)
        service, pet_repo, _ = self._make_service([server], [result], initial_pet=pet)
        await service.run_cycle(db=None)
        # Healthy cycle: EXP awarded but no HP_GAIN_ON_RECOVERY
        assert pet_repo.pet.exp == C.EXP_PER_HEALTHY_CYCLE
        assert pet_repo.pet.hp == 5  # HP unchanged, no recovery applied


# ─── Daily stats ON CONFLICT SQL math ───────────────────────────────────────

class TestDailyStatUpsert:
    """Verify upsert_daily_stat ON CONFLICT accumulation using a real in-memory DB."""

    async def _fresh_db(self):
        import aiosqlite
        from app.infrastructure.database import init_db
        conn = aiosqlite.connect(":memory:")
        db = await conn.__aenter__()
        db.row_factory = aiosqlite.Row
        await init_db(db)
        return conn, db

    async def test_accumulates_total_and_successful_checks(self):
        """Three upserts on same (server_id, date): total=3, successful=2."""
        from app.infrastructure.repositories.server_repo import (
            upsert_daily_stat, get_daily_stats, create_server,
        )
        conn, db = await self._fresh_db()
        try:
            srv = await create_server(db, "web", "http://x", None, "http", None)
            today = "2025-01-15"
            await upsert_daily_stat(db, srv.id, today, True,  latency_ms=10)
            await upsert_daily_stat(db, srv.id, today, True,  latency_ms=20)
            await upsert_daily_stat(db, srv.id, today, False, latency_ms=None)
            stats = await get_daily_stats(db, srv.id, limit=7)
            assert len(stats) == 1
            assert stats[0].total_checks == 3
            assert stats[0].successful_checks == 2
            assert abs(stats[0].uptime_percent - 66.67) < 0.5
        finally:
            await conn.__aexit__(None, None, None)

    async def test_avg_response_ms_rolling_average(self):
        """avg_response_ms is the rolling average of non-null latency values."""
        from app.infrastructure.repositories.server_repo import (
            upsert_daily_stat, get_daily_stats, create_server,
        )
        conn, db = await self._fresh_db()
        try:
            srv = await create_server(db, "api", "http://api", None, "http", None)
            today = "2025-01-15"
            await upsert_daily_stat(db, srv.id, today, True, latency_ms=100)
            await upsert_daily_stat(db, srv.id, today, True, latency_ms=200)
            stats = await get_daily_stats(db, srv.id, limit=7)
            assert stats[0].avg_response_ms is not None
            assert abs(stats[0].avg_response_ms - 150) < 1
        finally:
            await conn.__aexit__(None, None, None)

    async def test_get_daily_stats_empty_returns_empty_list(self):
        """No stat rows for a server returns an empty list."""
        from app.infrastructure.repositories.server_repo import (
            get_daily_stats, create_server,
        )
        conn, db = await self._fresh_db()
        try:
            srv = await create_server(db, "empty", "http://e", None, "http", None)
            assert await get_daily_stats(db, srv.id, limit=7) == []
        finally:
            await conn.__aexit__(None, None, None)


# ═══════════════════════════════════════════════════════════════════════════════
# SSL warning throttle — persistence tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestSSLWarningThrottle:
    """SSL expiry warnings must be throttled per-server via DB (survives restarts)."""

    def _make_service(self, servers, check_results, memory_repo=None):
        pet_repo = MockPetRepo(pet=_default_pet())
        server_repo = MockServerRepo(servers=servers)
        result_map = {r.server_id: r for r in check_results}

        from unittest.mock import MagicMock
        checker = MagicMock()

        async def mock_check(server_id, name, address, port, check_params=None):
            return result_map.get(server_id, ServerCheckResult(server_id, name, True, None))

        checker.check = mock_check
        svc = MonitorService(
            pet_repo=pet_repo,
            server_repo=server_repo,
            http_checker=checker,
            memory_repo=memory_repo,
        )
        return svc, server_repo

    async def test_ssl_warning_fires_when_cert_near_expiry(self):
        """run_cycle fires SSL warning when cert expires within 30 days."""
        mem = MockMemoryRepo()
        soon = (_now() + timedelta(days=20)).isoformat()
        server = FakeServer(id=1, name="web", address="https://web", port=443,
                            type="http", status="UP")
        result = ServerCheckResult(server_id=1, name="web", is_up=True, error=None,
                                   ssl_expiry_date=soon)
        svc, srv_repo = self._make_service([server], [result], memory_repo=mem)
        await svc.run_cycle(db=None)
        types = [c["event_type"] for c in mem.calls]
        assert "ssl_expiry_warning" in types

    async def test_ssl_warning_not_repeated_within_24h(self):
        """When last_ssl_warning_date is recent, warning is suppressed."""
        mem = MockMemoryRepo()
        soon = (_now() + timedelta(days=20)).isoformat()
        # Server was warned just 1 hour ago
        recent_warned = _now() - timedelta(hours=1)
        server = FakeServer(id=1, name="web", address="https://web", port=443,
                            type="http", status="UP",
                            last_ssl_warning_date=recent_warned)
        result = ServerCheckResult(server_id=1, name="web", is_up=True, error=None,
                                   ssl_expiry_date=soon)
        svc, _ = self._make_service([server], [result], memory_repo=mem)
        await svc.run_cycle(db=None)
        types = [c["event_type"] for c in mem.calls]
        assert "ssl_expiry_warning" not in types

    async def test_ssl_warning_fires_after_24h_cooldown(self):
        """When last_ssl_warning_date is >24h ago, warning fires again."""
        mem = MockMemoryRepo()
        soon = (_now() + timedelta(days=20)).isoformat()
        old_warned = _now() - timedelta(hours=25)
        server = FakeServer(id=1, name="web", address="https://web", port=443,
                            type="http", status="UP",
                            last_ssl_warning_date=old_warned)
        result = ServerCheckResult(server_id=1, name="web", is_up=True, error=None,
                                   ssl_expiry_date=soon)
        svc, _ = self._make_service([server], [result], memory_repo=mem)
        await svc.run_cycle(db=None)
        types = [c["event_type"] for c in mem.calls]
        assert "ssl_expiry_warning" in types

    async def test_ssl_warning_persists_date_to_db(self):
        """After firing a warning, last_ssl_warning_date is written to the server repo."""
        mem = MockMemoryRepo()
        soon = (_now() + timedelta(days=20)).isoformat()
        server = FakeServer(id=1, name="web", address="https://web", port=443,
                            type="http", status="UP")
        result = ServerCheckResult(server_id=1, name="web", is_up=True, error=None,
                                   ssl_expiry_date=soon)
        svc, srv_repo = self._make_service([server], [result], memory_repo=mem)
        await svc.run_cycle(db=None)
        # The server's last_ssl_warning_date should be updated in the repo
        assert server.last_ssl_warning_date is not None

    async def test_ssl_warning_not_fired_for_cert_far_away(self):
        """No warning when cert expires in >30 days."""
        mem = MockMemoryRepo()
        far = (_now() + timedelta(days=60)).isoformat()
        server = FakeServer(id=1, name="web", address="https://web", port=443,
                            type="http", status="UP")
        result = ServerCheckResult(server_id=1, name="web", is_up=True, error=None,
                                   ssl_expiry_date=far)
        svc, _ = self._make_service([server], [result], memory_repo=mem)
        await svc.run_cycle(db=None)
        types = [c["event_type"] for c in mem.calls]
        assert "ssl_expiry_warning" not in types


# ═══════════════════════════════════════════════════════════════════════════════
# Dust drain double-apply guard tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestDustDrainThrottle:
    """Dust HP drain must only fire once per DUST_HP_DRAIN_CYCLE_MODULO intervals."""

    def _make_service(self, servers, check_results, initial_pet=None):
        pet_repo = MockPetRepo(pet=initial_pet or _default_pet())
        server_repo = MockServerRepo(servers=servers)
        result_map = {r.server_id: r for r in check_results}

        from unittest.mock import MagicMock
        checker = MagicMock()

        async def mock_check(server_id, name, address, port, check_params=None):
            return result_map.get(server_id, ServerCheckResult(server_id, name, True, None))

        checker.check = mock_check
        svc = MonitorService(
            pet_repo=pet_repo,
            server_repo=server_repo,
            http_checker=checker,
        )
        return svc, pet_repo

    async def test_dust_drain_not_applied_within_interval(self):
        """When last_dust_drain_at is recent, drain is skipped."""
        # Pet at max dust with a very recent drain
        recent_drain = _now() - timedelta(seconds=30)
        pet = replace(_default_pet(hp=C.HP_MAX),
                      dust_count=C.MAX_DUST,
                      last_dust_drain_at=recent_drain)
        server = FakeServer(id=1, name="web", address="http://web", port=80, type="http")
        result = ServerCheckResult(server_id=1, name="web", is_up=True, error=None)
        svc, pet_repo = self._make_service([server], [result], initial_pet=pet)
        hp_before = pet_repo.pet.hp
        await svc.run_cycle(db=None)
        assert pet_repo.pet.hp == hp_before  # no drain applied

    async def test_dust_drain_applied_when_overdue(self):
        """Dust drain fires when last_dust_drain_at is beyond the interval."""
        drain_interval = C.MONITOR_INTERVAL_SECONDS * C.DUST_HP_DRAIN_CYCLE_MODULO
        old_drain = _now() - timedelta(seconds=drain_interval + 60)
        pet = replace(_default_pet(hp=C.HP_MAX),
                      dust_count=C.MAX_DUST,
                      last_dust_drain_at=old_drain)
        server = FakeServer(id=1, name="web", address="http://web", port=80, type="http")
        result = ServerCheckResult(server_id=1, name="web", is_up=True, error=None)
        svc, pet_repo = self._make_service([server], [result], initial_pet=pet)
        hp_before = pet_repo.pet.hp
        await svc.run_cycle(db=None)
        assert pet_repo.pet.hp < hp_before  # drain was applied

    async def test_dust_drain_applied_when_never_drained(self):
        """Dust drain fires on first cycle when last_dust_drain_at is None."""
        pet = replace(_default_pet(hp=C.HP_MAX),
                      dust_count=C.MAX_DUST,
                      last_dust_drain_at=None)
        server = FakeServer(id=1, name="web", address="http://web", port=80, type="http")
        result = ServerCheckResult(server_id=1, name="web", is_up=True, error=None)
        svc, pet_repo = self._make_service([server], [result], initial_pet=pet)
        hp_before = pet_repo.pet.hp
        await svc.run_cycle(db=None)
        assert pet_repo.pet.hp < hp_before

    async def test_dust_drain_updates_last_dust_drain_at(self):
        """After drain fires, last_dust_drain_at on saved pet is updated."""
        drain_interval = C.MONITOR_INTERVAL_SECONDS * C.DUST_HP_DRAIN_CYCLE_MODULO
        old_drain = _now() - timedelta(seconds=drain_interval + 60)
        pet = replace(_default_pet(hp=C.HP_MAX),
                      dust_count=C.MAX_DUST,
                      last_dust_drain_at=old_drain)
        server = FakeServer(id=1, name="web", address="http://web", port=80, type="http")
        result = ServerCheckResult(server_id=1, name="web", is_up=True, error=None)
        svc, pet_repo = self._make_service([server], [result], initial_pet=pet)
        await svc.run_cycle(db=None)
        assert pet_repo.pet.last_dust_drain_at is not None
        assert pet_repo.pet.last_dust_drain_at > old_drain


# ═══════════════════════════════════════════════════════════════════════════════
# Import deduplication NULL-safety tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestImportDedup:
    """POST /import must deduplicate memories correctly even when detail is NULL."""

    async def _fresh_db(self):
        import aiosqlite
        from app.infrastructure.database import init_db
        conn = aiosqlite.connect(":memory:")
        db = await conn.__aenter__()
        db.row_factory = aiosqlite.Row
        await init_db(db)
        return conn, db

    async def test_null_detail_not_duplicated(self):
        """Importing same event twice with NULL detail inserts only one row."""
        from app.infrastructure.repositories.memory_repo import add_memory, list_memories
        conn, db = await self._fresh_db()
        try:
            # Simulate what the import route does (after the NULL fix)
            occurred = "2025-01-01T00:00:00+00:00"
            await db.execute(
                """INSERT OR IGNORE INTO pet_memories (event_type, detail, occurred_at)
                   SELECT ?, ?, ?
                   WHERE NOT EXISTS (
                       SELECT 1 FROM pet_memories
                       WHERE occurred_at = ? AND event_type = ?
                         AND (detail IS ? OR detail = ?)
                   )""",
                ("server_down", None, occurred, occurred, "server_down", None, None),
            )
            await db.execute(
                """INSERT OR IGNORE INTO pet_memories (event_type, detail, occurred_at)
                   SELECT ?, ?, ?
                   WHERE NOT EXISTS (
                       SELECT 1 FROM pet_memories
                       WHERE occurred_at = ? AND event_type = ?
                         AND (detail IS ? OR detail = ?)
                   )""",
                ("server_down", None, occurred, occurred, "server_down", None, None),
            )
            await db.commit()
            mems = await list_memories(db, limit=10)
            null_downs = [m for m in mems if m.event_type == "server_down"]
            assert len(null_downs) == 1
        finally:
            await conn.__aexit__(None, None, None)

    async def test_empty_and_null_detail_stay_distinct(self):
        """NULL detail and empty-string detail are treated as distinct entries."""
        conn, db = await self._fresh_db()
        try:
            occurred = "2025-01-02T00:00:00+00:00"
            for detail in (None, ""):
                await db.execute(
                    """INSERT OR IGNORE INTO pet_memories (event_type, detail, occurred_at)
                       SELECT ?, ?, ?
                       WHERE NOT EXISTS (
                           SELECT 1 FROM pet_memories
                           WHERE occurred_at = ? AND event_type = ?
                             AND (detail IS ? OR detail = ?)
                       )""",
                    ("server_down", detail, occurred, occurred, "server_down", detail, detail),
                )
            await db.commit()
            async with db.execute(
                "SELECT COUNT(*) FROM pet_memories WHERE occurred_at = ? AND event_type = ?",
                (occurred, "server_down"),
            ) as cur:
                count = (await cur.fetchone())[0]
            assert count == 2
        finally:
            await conn.__aexit__(None, None, None)

    async def test_non_null_detail_deduplication(self):
        """Importing same event+detail twice inserts only one row."""
        conn, db = await self._fresh_db()
        try:
            occurred = "2025-01-03T00:00:00+00:00"
            for _ in range(2):
                await db.execute(
                    """INSERT OR IGNORE INTO pet_memories (event_type, detail, occurred_at)
                       SELECT ?, ?, ?
                       WHERE NOT EXISTS (
                           SELECT 1 FROM pet_memories
                           WHERE occurred_at = ? AND event_type = ?
                             AND (detail IS ? OR detail = ?)
                       )""",
                    ("server_down", "nginx", occurred, occurred, "server_down", "nginx", "nginx"),
                )
            await db.commit()
            async with db.execute(
                "SELECT COUNT(*) FROM pet_memories WHERE occurred_at = ? AND event_type = ?",
                (occurred, "server_down"),
            ) as cur:
                count = (await cur.fetchone())[0]
            assert count == 1
        finally:
            await conn.__aexit__(None, None, None)


# ═══════════════════════════════════════════════════════════════════════════════
# Race condition lock tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestPetServiceRaceLock:
    """Concurrent requests must not bypass cooldown checks via the module-level lock."""

    async def test_concurrent_interact_only_one_succeeds(self):
        """Two concurrent interact() calls: only one bypasses the cooldown."""
        import asyncio
        # Pet with no prior interaction so first call succeeds
        pet = replace(_default_pet(), last_interaction_date=None)
        svc = PetService(pet_repo=MockPetRepo(pet=pet))
        results = await asyncio.gather(
            svc.interact(db=None),
            svc.interact(db=None),
        )
        non_cooldown = [r for r in results if not r[1]]  # r[1] is on_cooldown
        assert len(non_cooldown) == 1, (
            "Exactly one interact() should succeed; the other must hit cooldown"
        )

    async def test_concurrent_backup_only_one_succeeds(self):
        """Two concurrent backup() calls: only the first one succeeds."""
        import asyncio
        pet = replace(_default_pet(), last_backup_date=None)
        svc = PetService(pet_repo=MockPetRepo(pet=pet))
        results = await asyncio.gather(
            svc.backup(db=None),
            svc.backup(db=None),
        )
        non_cooldown = [r for r in results if not r[1]]  # r[1] is on_cooldown
        assert len(non_cooldown) == 1, (
            "Exactly one backup() should succeed; the other must hit cooldown"
        )
