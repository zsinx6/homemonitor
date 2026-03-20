"""Task repository — async DB read/write for tasks table."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from app.domain import constants as C
from app.infrastructure.repositories.common import parse_datetime

_PRIORITY_ORDER = {"high": 0, "normal": 1, "low": 2}


@dataclass
class TaskRow:
    id: int
    task: str
    is_completed: bool
    created_at: datetime
    completed_at: Optional[datetime]
    priority: str = "normal"


def _row_to_task(row: aiosqlite.Row) -> TaskRow:
    keys = row.keys() if hasattr(row, "keys") else {}
    return TaskRow(
        id=row["id"],
        task=row["task"],
        is_completed=bool(row["is_completed"]),
        created_at=parse_datetime(row["created_at"]),
        completed_at=parse_datetime(row["completed_at"]),
        priority=row["priority"] if "priority" in keys else "normal",
    )


async def list_tasks(db: aiosqlite.Connection) -> list[TaskRow]:
    """Return pending tasks (high→normal→low, newest within tier) then last 20 completed."""
    db.row_factory = aiosqlite.Row
    async with db.execute(
        "SELECT * FROM tasks WHERE is_completed = 0 ORDER BY created_at DESC"
    ) as cur:
        pending = [_row_to_task(r) for r in await cur.fetchall()]

    # Sort pending by priority tier, preserve newest-first within tier
    pending.sort(key=lambda t: _PRIORITY_ORDER.get(t.priority, 1))

    async with db.execute(
        "SELECT * FROM tasks WHERE is_completed = 1 ORDER BY completed_at DESC LIMIT ?",
        (C.COMPLETED_TASKS_DISPLAY_CAP,),
    ) as cur:
        completed = [_row_to_task(r) for r in await cur.fetchall()]

    return pending + completed


async def get_task(db: aiosqlite.Connection, task_id: int) -> Optional[TaskRow]:
    db.row_factory = aiosqlite.Row
    async with db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)) as cur:
        row = await cur.fetchone()
    return _row_to_task(row) if row else None


async def create_task(
    db: aiosqlite.Connection,
    task_text: str,
    priority: str = "normal",
) -> TaskRow:
    now = datetime.now(timezone.utc).isoformat()
    async with db.execute(
        "INSERT INTO tasks (task, is_completed, created_at, priority) VALUES (?, 0, ?, ?)",
        (task_text, now, priority),
    ) as cur:
        task_id = cur.lastrowid
    await db.commit()
    return await get_task(db, task_id)


async def complete_task(
    db: aiosqlite.Connection, task_id: int, *, commit: bool = True
) -> Optional[TaskRow]:
    """Mark a task complete. Returns None if task not found or already complete."""
    task = await get_task(db, task_id)
    if task is None or task.is_completed:
        return None
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "UPDATE tasks SET is_completed = 1, completed_at = ? WHERE id = ?",
        (now, task_id),
    )
    if commit:
        await db.commit()
    return await get_task(db, task_id)


async def count_completed(db: aiosqlite.Connection) -> int:
    """Return the total number of completed tasks."""
    async with db.execute(
        "SELECT COUNT(*) FROM tasks WHERE is_completed = 1"
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row else 0


async def delete_task(db: aiosqlite.Connection, task_id: int) -> bool:
    """Delete a task by ID. Returns True if deleted, False if not found."""
    async with db.execute("DELETE FROM tasks WHERE id = ?", (task_id,)) as cur:
        deleted = cur.rowcount > 0
    await db.commit()
    return deleted
