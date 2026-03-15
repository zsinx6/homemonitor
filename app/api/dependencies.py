"""FastAPI dependency injection: DB connection, services, phrase selector."""
from __future__ import annotations

from typing import AsyncGenerator

import aiosqlite
from fastapi import Request

from app.domain.phrases import PhraseSelector
from app.domain.static_phrase_service import StaticPhraseService
from app.infrastructure.adapters import PetRepoAdapter, ServerRepoAdapter, TaskRepoAdapter
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


def get_pet_service() -> PetService:
    return PetService(pet_repo=PetRepoAdapter())


def get_task_service() -> TaskService:
    return TaskService(pet_repo=PetRepoAdapter(), task_repo=TaskRepoAdapter())
