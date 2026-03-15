"""FastAPI dependency injection: DB connection, services, phrase selector."""
from __future__ import annotations

from typing import AsyncGenerator

import aiosqlite
from fastapi import Request

from app.domain.phrases import PhraseSelector
from app.domain.static_phrase_service import StaticPhraseService
from app.infrastructure.repositories import pet_repo, server_repo, task_repo
from app.services.monitor_service import MonitorService
from app.services.pet_service import PetService
from app.services.task_service import TaskService

_phrase_selector: PhraseSelector = StaticPhraseService()


async def get_db(request: Request) -> AsyncGenerator[aiosqlite.Connection, None]:
    db_path = request.app.state.db_path
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        yield db


def get_phrase_selector() -> PhraseSelector:
    return _phrase_selector


class _PetRepoAdapter:
    async def get_pet(self, db): return await pet_repo.get_pet(db)
    async def save_pet(self, db, p): await pet_repo.save_pet(db, p)
    async def clear_last_event(self, db): await pet_repo.clear_last_event(db)


class _ServerRepoAdapter:
    async def list_servers(self, db): return await server_repo.list_servers(db)
    async def update_server_check_result(self, db, *a): await server_repo.update_server_check_result(db, *a)
    async def upsert_daily_stat(self, db, *a): await server_repo.upsert_daily_stat(db, *a)


class _TaskRepoAdapter:
    async def get_task(self, db, tid): return await task_repo.get_task(db, tid)
    async def complete_task(self, db, tid): return await task_repo.complete_task(db, tid)


def get_pet_service() -> PetService:
    return PetService(pet_repo=_PetRepoAdapter())


def get_task_service() -> TaskService:
    return TaskService(pet_repo=_PetRepoAdapter(), task_repo=_TaskRepoAdapter())
