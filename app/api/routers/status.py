"""Status endpoint — returns a full system snapshot as structured JSON.

Useful for monitoring dashboards, manual inspection, and as LLM context.
"""
from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, Depends

from app.api.dependencies import get_db
from app.services import context_service

router = APIRouter()


@router.get("/status")
async def get_status(db: aiosqlite.Connection = Depends(get_db)):
    """Return a full system snapshot: pet stats, server health, task counts, backup status."""
    snapshot = await context_service.build_snapshot(db)
    return snapshot.to_dict()
