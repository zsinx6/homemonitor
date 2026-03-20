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

EXPORT_VERSION = "2.0"

_VALID_SERVER_TYPES = ("http", "ping", "tcp", "http_keyword", "public_ip")


class ImportPayload(BaseModel):
    servers: list[dict] = []
    tasks: list[dict] = []
    pet: dict | None = None
    memories: list[dict] = []


@router.get("/export", summary="Export complete data backup (pet, servers, tasks, memories)")
async def export_data(db: aiosqlite.Connection = Depends(get_db)) -> dict[str, Any]:
    """Return a complete JSON snapshot of all application state.

    Includes all V3 pet fields, full server check state, all tasks, and all
    memory events.  Suitable for migrating to a new host or disaster recovery.
    """
    pet = await pet_repo.get_pet(db)
    servers = await server_repo.list_servers(db)
    tasks = await task_repo.list_tasks(db)
    # Fetch all memories (no arbitrary limit)
    memories = await memory_repo.list_memories(db, limit=10_000, offset=0)

    # --- daily stats per server ---
    daily: dict[int, list[dict]] = {}
    for s in servers:
        stats = await server_repo.get_daily_stats(db, s.id, limit=90)
        daily[s.id] = [
            {
                "date": st.date,
                "total_checks": st.total_checks,
                "successful_checks": st.successful_checks,
                "uptime_percent": st.uptime_percent,
                "avg_response_ms": st.avg_response_ms,
            }
            for st in stats
        ]

    def _fmt(dt: datetime | None) -> str | None:
        return dt.isoformat() if dt else None

    return {
        "version": EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "pet": {
            "name": pet.name,
            "level": pet.level,
            "exp": pet.exp,
            "max_exp": pet.max_exp,
            "hp": pet.hp,
            "is_dead": pet.is_dead,
            "dust_count": pet.dust_count,
            "current_mood": pet.current_mood,
            "last_dust_date": _fmt(pet.last_dust_date),
            "last_mood_change": _fmt(pet.last_mood_change),
            "last_focus_date": _fmt(pet.last_focus_date),
            "last_interaction_date": _fmt(pet.last_interaction_date),
            "last_backup_date": _fmt(pet.last_backup_date),
            "last_updated": _fmt(pet.last_updated),
        },
        "servers": [
            {
                "name": s.name,
                "address": s.address,
                "port": s.port,
                "type": s.type,
                "position": s.position,
                "check_params": s.check_params,
                "maintenance_mode": s.maintenance_mode,
                "status": s.status,
                "total_checks": s.total_checks,
                "successful_checks": s.successful_checks,
                "uptime_percent": s.uptime_percent,
                "last_checked": _fmt(s.last_checked),
                "last_error": s.last_error,
                "last_response_ms": s.last_response_ms,
                "ssl_expiry_date": s.ssl_expiry_date,
                "daily_stats": daily.get(s.id, []),
            }
            for s in servers
        ],
        "tasks": [
            {
                "task": t.task,
                "priority": t.priority,
                "is_completed": t.is_completed,
                "created_at": _fmt(t.created_at),
                "completed_at": _fmt(t.completed_at),
            }
            for t in tasks
        ],
        "memories": [
            {
                "event_type": m.event_type,
                "detail": m.detail,
                "occurred_at": _fmt(m.occurred_at),
            }
            for m in memories
        ],
    }


@router.post("/import", status_code=200, summary="Restore full backup (servers, tasks, pet, memories)")
async def import_data(
    body: ImportPayload,
    db: aiosqlite.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Import a backup payload produced by GET /export.

    * **Servers** — clears existing servers, recreates with full check state.
    * **Tasks** — appends ALL tasks (including completed) preserving timestamps.
    * **Pet** — restores full V3 pet state when ``pet`` key is present.
    * **Memories** — appends memories not already present (dedup by occurred_at + event_type).
    """
    if not body.servers and not body.tasks and not body.pet and not body.memories:
        raise HTTPException(status_code=422, detail="Import payload is empty")

    imported_servers = 0
    imported_tasks = 0
    imported_memories = 0

    # --- Servers ---
    if body.servers:
        await db.execute("DELETE FROM server_daily_stats")
        await db.execute("DELETE FROM servers")
        await db.commit()

        for i, s in enumerate(body.servers):
            name = (s.get("name") or "").strip()
            address = (s.get("address") or "").strip()
            if not name or not address:
                continue
            srv_type = s.get("type", "http")
            if srv_type not in _VALID_SERVER_TYPES:
                srv_type = "http"
            port = s.get("port")
            check_params = s.get("check_params")
            params_json = json.dumps(check_params) if check_params else None
            maintenance = int(bool(s.get("maintenance_mode", False)))
            status = s.get("status", "UP")
            total = int(s.get("total_checks") or 0)
            successful = int(s.get("successful_checks") or 0)
            uptime = float(s.get("uptime_percent") or 0.0)
            last_checked = s.get("last_checked")
            last_error = s.get("last_error")
            last_response_ms = s.get("last_response_ms")
            ssl_expiry_date = s.get("ssl_expiry_date")
            position = int(s.get("position") or i)

            cur = await db.execute(
                """INSERT INTO servers
                   (name, address, port, type, position, check_params, maintenance_mode,
                    status, total_checks, successful_checks, uptime_percent,
                    last_checked, last_error, last_response_ms, ssl_expiry_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (name, address, port, srv_type, position, params_json, maintenance,
                 status, total, successful, uptime,
                 last_checked, last_error, last_response_ms, ssl_expiry_date),
            )
            server_id = cur.lastrowid
            imported_servers += 1

            for stat in s.get("daily_stats", []):
                date = stat.get("date")
                if not date:
                    continue
                await db.execute(
                    """INSERT OR REPLACE INTO server_daily_stats
                       (server_id, date, total_checks, successful_checks, uptime_percent, avg_response_ms)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (server_id, date,
                     int(stat.get("total_checks") or 0),
                     int(stat.get("successful_checks") or 0),
                     float(stat.get("uptime_percent") or 0.0),
                     stat.get("avg_response_ms")),
                )
        await db.commit()

    # --- Tasks ---
    if body.tasks:
        for t in body.tasks:
            task_text = (t.get("task") or "").strip()
            if not task_text:
                continue
            priority = t.get("priority", "normal")
            if priority not in ("high", "normal", "low"):
                priority = "normal"
            is_completed = int(bool(t.get("is_completed", False)))
            created_at = t.get("created_at") or datetime.now(timezone.utc).isoformat()
            completed_at = t.get("completed_at")
            await db.execute(
                """INSERT INTO tasks (task, priority, is_completed, created_at, completed_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (task_text, priority, is_completed, created_at, completed_at),
            )
            imported_tasks += 1
        await db.commit()

    # --- Pet ---
    if body.pet:
        p = body.pet
        await db.execute(
            """UPDATE pet_state SET
                name = ?, level = ?, exp = ?, max_exp = ?, hp = ?, is_dead = ?,
                dust_count = ?, current_mood = ?,
                last_dust_date = ?, last_mood_change = ?, last_focus_date = ?,
                last_interaction_date = ?, last_backup_date = ?, last_updated = ?
               WHERE id = 1""",
            (
                (p.get("name") or "Bitmon"),
                int(p.get("level") or 1),
                int(p.get("exp") or 0),
                int(p.get("max_exp") or 100),
                int(p.get("hp") or 100),
                int(bool(p.get("is_dead", False))),
                int(p.get("dust_count") or 0),
                p.get("current_mood") or "Energetic",
                p.get("last_dust_date"),
                p.get("last_mood_change"),
                p.get("last_focus_date"),
                p.get("last_interaction_date"),
                p.get("last_backup_date"),
                p.get("last_updated") or datetime.now(timezone.utc).isoformat(),
            ),
        )
        await db.commit()

    # --- Memories (dedup by occurred_at + event_type) ---
    if body.memories:
        for m in body.memories:
            event_type = m.get("event_type") or ""
            detail = m.get("detail") or ""
            occurred_at = m.get("occurred_at")
            if not event_type or not occurred_at:
                continue
            await db.execute(
                """INSERT OR IGNORE INTO pet_memories (event_type, detail, occurred_at)
                   SELECT ?, ?, ?
                   WHERE NOT EXISTS (
                       SELECT 1 FROM pet_memories
                       WHERE occurred_at = ? AND event_type = ?
                   )""",
                (event_type, detail, occurred_at, occurred_at, event_type),
            )
            imported_memories += 1
        await db.commit()

    return {
        "imported_servers": imported_servers,
        "imported_tasks": imported_tasks,
        "imported_memories": imported_memories,
        "pet_restored": body.pet is not None,
    }
