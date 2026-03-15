"""Tests for services using mock repos and mock checkers."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
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

    async def save_pet(self, db, pet: Pet):
        self.pet = pet
        self.saved.append(pet)

    async def clear_last_event(self, db):
        self.pet = self.pet.__class__(**{**self.pet.__dict__, "last_event": None})


@dataclass
class MockServerRepo:
    servers: list = field(default_factory=list)
    check_updates: list = field(default_factory=list)

    async def list_servers(self, db):
        return self.servers

    async def update_server_check_result(self, db, server_id, is_up, error, checked_at):
        self.check_updates.append((server_id, is_up, error))

    async def upsert_daily_stat(self, db, server_id, date_str, is_up):
        pass


@dataclass
class MockTaskRepo:
    tasks: list = field(default_factory=list)
    completed: list = field(default_factory=list)

    async def get_task(self, db, task_id: int):
        return next((t for t in self.tasks if t.id == task_id), None)

    async def complete_task(self, db, task_id: int):
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


@dataclass
class FakeTask:
    id: int
    task: str
    is_completed: bool = False
    created_at: datetime = field(default_factory=_now)
    completed_at: Optional[datetime] = None


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

        async def mock_check(server_id, name, address, port):
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
        """A server transitioning UP→DOWN fires last_event = 'server_down'."""
        pet = _default_pet(hp=C.HP_MAX)
        # Server is currently UP in DB
        server = FakeServer(id=1, name="web", address="http://x", port=None,
                            type="http", status="UP")
        # But the check returns DOWN (new failure)
        result = ServerCheckResult(server_id=1, name="web", is_up=False, error="timeout")
        service, pet_repo, _ = self._make_service([server], [result], initial_pet=pet)
        await service.run_cycle(db=None)
        assert pet_repo.pet.last_event == "server_down"


# ---------------------------------------------------------------------------
# PetService tests
# ---------------------------------------------------------------------------

class TestPetService:
    def _make_service(self, initial_pet=None):
        pet_repo = MockPetRepo(pet=initial_pet or _default_pet())
        service = PetService(pet_repo=pet_repo)
        return service, pet_repo

    async def test_interact_gains_exp(self):
        service, repo = self._make_service()
        pet = await service.interact(db=None)
        assert pet.exp == C.EXP_INTERACT

    async def test_interact_updates_interaction_date(self):
        old = _now().__class__.min.replace(tzinfo=timezone.utc)
        service, repo = self._make_service(_default_pet(last_interaction_date=old))
        pet = await service.interact(db=None)
        assert pet.last_interaction_date > old

    async def test_backup_gains_exp_and_hp(self):
        service, repo = self._make_service(_default_pet(hp=5))
        pet = await service.backup(db=None)
        assert pet.exp == C.EXP_BACKUP
        assert pet.hp == min(5 + C.HP_GAIN_BACKUP, C.HP_MAX)

    async def test_backup_sets_backup_date(self):
        service, repo = self._make_service()
        pet = await service.backup(db=None)
        assert pet.last_backup_date is not None


# ---------------------------------------------------------------------------
# TaskService tests
# ---------------------------------------------------------------------------

class TestTaskService:
    def _make_service(self, tasks=None, initial_pet=None):
        pet_repo = MockPetRepo(pet=initial_pet or _default_pet())
        task_repo = MockTaskRepo(tasks=tasks or [])
        service = TaskService(pet_repo=pet_repo, task_repo=task_repo)
        return service, pet_repo, task_repo

    async def test_complete_task_grants_exp(self):
        task = FakeTask(id=1, task="Fix nginx")
        service, pet_repo, _ = self._make_service(tasks=[task])
        await service.complete_task(db=None, task_id=1)
        assert pet_repo.pet.exp == C.EXP_COMPLETE_TASK

    async def test_complete_task_grants_hp(self):
        task = FakeTask(id=1, task="Fix nginx")
        service, pet_repo, _ = self._make_service(tasks=[task], initial_pet=_default_pet(hp=5))
        await service.complete_task(db=None, task_id=1)
        assert pet_repo.pet.hp == min(5 + C.HP_GAIN_COMPLETE_TASK, C.HP_MAX)

    async def test_complete_nonexistent_task_returns_none(self):
        service, pet_repo, _ = self._make_service(tasks=[])
        result = await service.complete_task(db=None, task_id=999)
        assert result is None
        assert pet_repo.pet.exp == 0  # no change
