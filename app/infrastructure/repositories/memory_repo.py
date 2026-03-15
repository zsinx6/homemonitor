"""Memory repository — async DB read/write for pet_memories table."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from app.domain.memory import Memory


def _row_to_memory(row: aiosqlite.Row) -> Memory:
    return Memory(
        id=row["id"],
        event_type=row["event_type"],
        detail=row["detail"],
        occurred_at=datetime.fromisoformat(row["occurred_at"]).replace(tzinfo=timezone.utc),
    )


async def add_memory(
    db: aiosqlite.Connection,
    event_type: str,
    detail: Optional[str] = None,
    occurred_at: Optional[datetime] = None,
) -> Memory:
    if occurred_at is None:
        occurred_at = datetime.now(timezone.utc)
    async with db.execute(
        "INSERT INTO pet_memories (event_type, detail, occurred_at) VALUES (?, ?, ?)",
        (event_type, detail, occurred_at.isoformat()),
    ) as cur:
        row_id = cur.lastrowid
    await db.commit()
    return Memory(id=row_id, event_type=event_type, detail=detail, occurred_at=occurred_at)


async def list_memories(
    db: aiosqlite.Connection,
    limit: int = 50,
    offset: int = 0,
) -> list[Memory]:
    db.row_factory = aiosqlite.Row
    async with db.execute(
        "SELECT * FROM pet_memories ORDER BY occurred_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ) as cur:
        rows = await cur.fetchall()
    return [_row_to_memory(r) for r in rows]


async def get_recent(db: aiosqlite.Connection, limit: int = 10) -> list[Memory]:
    return await list_memories(db, limit=limit, offset=0)


async def count_total(db: aiosqlite.Connection) -> int:
    async with db.execute("SELECT COUNT(*) FROM pet_memories") as cur:
        row = await cur.fetchone()
    return row[0] if row else 0


async def get_summary(db: aiosqlite.Connection) -> dict[str, int]:
    """Returns {event_type: count} for all recorded memories."""
    db.row_factory = aiosqlite.Row
    async with db.execute(
        "SELECT event_type, COUNT(*) as cnt FROM pet_memories GROUP BY event_type"
    ) as cur:
        rows = await cur.fetchall()
    return {r["event_type"]: r["cnt"] for r in rows}
