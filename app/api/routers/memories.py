"""Memories API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends

import aiosqlite

from app.api.dependencies import get_db
from app.api.models import MemoryListResponse, MemoryOut
from app.infrastructure.repositories import memory_repo

router = APIRouter()


@router.get("/memories", response_model=MemoryListResponse)
async def list_memories(
    db: aiosqlite.Connection = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
):
    """Return paginated pet memory log with event summary counts."""
    memories = await memory_repo.list_memories(db, limit=limit, offset=offset)
    total = await memory_repo.count_total(db)
    summary = await memory_repo.get_summary(db)
    return MemoryListResponse(
        memories=[
            MemoryOut(
                id=m.id,
                event_type=m.event_type,
                detail=m.detail,
                occurred_at=m.occurred_at,
            )
            for m in memories
        ],
        total=total,
        summary=summary,
    )
