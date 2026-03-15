"""Export / import routes for full data backup and restore."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import aiosqlite

from app.api.dependencies import get_db
from app.infrastructure.repositories import server_repo, task_repo, memory_repo, pet_repo

router = APIRouter()

EXPORT_VERSION = "1.0"


class ImportPayload(BaseModel):
    servers: list[dict] = []
    tasks: list[dict] = []


@router.get("/export", summary="Export all servers, tasks, and recent memories")
async def export_data(db: aiosqlite.Connection = Depends(get_db)) -> dict[str, Any]:
    """Return a full JSON snapshot of servers, tasks, and recent memories."""
    servers = await server_repo.list_servers(db)
    tasks = await task_repo.list_tasks(db)
    memories = await memory_repo.get_recent(db, limit=200)
    pet = await pet_repo.get_pet(db)

    return {
        "version": EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "pet": {
            "name": pet.name if pet else None,
            "level": pet.level if pet else None,
            "exp": pet.exp if pet else None,
            "hp": pet.hp if pet else None,
        },
        "servers": [
            {
                "name": s.name,
                "address": s.address,
                "port": s.port,
                "type": s.type,
                "position": s.position,
                "check_params": s.check_params,
            }
            for s in servers
        ],
        "tasks": [
            {
                "task": t.task,
                "priority": t.priority,
                "is_completed": t.is_completed,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            }
            for t in tasks
        ],
        "memories": [
            {
                "event_type": m.event_type,
                "detail": m.detail,
                "occurred_at": m.occurred_at.isoformat() if m.occurred_at else None,
            }
            for m in memories
        ],
    }


@router.post("/import", status_code=200, summary="Restore servers and pending tasks from export")
async def import_data(
    body: ImportPayload,
    db: aiosqlite.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Import servers and pending tasks from an export payload.

    * Servers: clears all existing servers and re-creates them in the given order.
    * Tasks: only pending tasks are imported; already-completed tasks are skipped.
    * Pet state and memories are intentionally NOT modified to avoid data loss.
    """
    if not body.servers and not body.tasks:
        raise HTTPException(status_code=422, detail="Import payload is empty")

    imported_servers = 0
    imported_tasks = 0

    if body.servers:
        # Clear existing servers before importing
        await db.execute("DELETE FROM servers")
        await db.commit()

        for i, s in enumerate(body.servers):
            name = (s.get("name") or "").strip()
            address = (s.get("address") or "").strip()
            srv_type = s.get("type", "http")
            port = s.get("port")
            check_params = s.get("check_params")
            if not name or not address:
                continue
            if srv_type not in ("http", "ping", "tcp", "http_keyword"):
                srv_type = "http"
            params_json = json.dumps(check_params) if check_params else None
            await db.execute(
                "INSERT INTO servers (name, address, port, type, position, check_params)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (name, address, port, srv_type, i, params_json),
            )
            imported_servers += 1
        await db.commit()

    if body.tasks:
        for t in body.tasks:
            if t.get("is_completed"):
                continue  # skip completed tasks
            task_text = (t.get("task") or "").strip()
            priority = t.get("priority", "normal")
            if not task_text:
                continue
            if priority not in ("high", "normal", "low"):
                priority = "normal"
            await task_repo.create_task(db, task_text, priority)
            imported_tasks += 1

    return {
        "imported_servers": imported_servers,
        "imported_tasks": imported_tasks,
    }
