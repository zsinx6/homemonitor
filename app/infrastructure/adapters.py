"""Shared repository adapter classes.

These thin wrappers let services and the worker call module-level repository
functions through a consistent object interface without duplicating the
adapter definitions in multiple places.
"""
from __future__ import annotations

from app.infrastructure.repositories import memory_repo, pet_repo, server_repo, task_repo


class PetRepoAdapter:
    async def get_pet(self, db): return await pet_repo.get_pet(db)
    async def save_pet(self, db, p, *, commit: bool = True): await pet_repo.save_pet(db, p, commit=commit)
    async def clear_last_event(self, db): await pet_repo.clear_last_event(db)
    async def rename_pet(self, db, name): return await pet_repo.rename_pet(db, name)


class ServerRepoAdapter:
    async def list_servers(self, db): return await server_repo.list_servers(db)
    async def get_server(self, db, sid): return await server_repo.get_server(db, sid)
    async def update_server_check_result(self, db, *a, **kw): await server_repo.update_server_check_result(db, *a, **kw)
    async def upsert_daily_stat(self, db, *a, **kw): await server_repo.upsert_daily_stat(db, *a, **kw)
    async def update_server_check_params(self, db, sid, params): await server_repo.update_server_check_params(db, sid, params)
    async def update_ssl_warning_date(self, db, sid, warned_at): await server_repo.update_server_ssl_warning_date(db, sid, warned_at)


class TaskRepoAdapter:
    async def get_task(self, db, tid): return await task_repo.get_task(db, tid)
    async def complete_task(self, db, tid, *, commit: bool = True): return await task_repo.complete_task(db, tid, commit=commit)


class MemoryRepoAdapter:
    async def add_memory(self, db, event_type, detail=None, occurred_at=None):
        return await memory_repo.add_memory(db, event_type, detail, occurred_at)

