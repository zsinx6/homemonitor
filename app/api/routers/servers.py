"""Servers API routes (CRUD)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

import aiosqlite

from app.api.dependencies import get_db
from app.api.models import DailyStatOut, MoveServerRequest, ServerCreate, ServerOut, ServerUpdate
from app.domain.memory import MemoryType
from app.infrastructure.repositories import memory_repo, server_repo

router = APIRouter()


async def _server_with_stats(db, srv) -> ServerOut:
    daily = await server_repo.get_daily_stats(db, srv.id, limit=7)
    return ServerOut(
        id=srv.id,
        name=srv.name,
        address=srv.address,
        port=srv.port,
        type=srv.type,
        status=srv.status,
        uptime_percent=srv.uptime_percent,
        total_checks=srv.total_checks,
        successful_checks=srv.successful_checks,
        last_error=srv.last_error,
        last_checked=srv.last_checked,
        maintenance_mode=srv.maintenance_mode,
        position=srv.position,
        check_params=srv.check_params,
        daily_stats=[
            DailyStatOut(
                date=d.date,
                total_checks=d.total_checks,
                successful_checks=d.successful_checks,
                uptime_percent=d.uptime_percent,
            )
            for d in daily
        ],
    )


@router.get("/servers", response_model=list[ServerOut])
async def list_servers(db: aiosqlite.Connection = Depends(get_db)):
    servers = await server_repo.list_servers(db)
    return [await _server_with_stats(db, s) for s in servers]


@router.post("/servers", response_model=ServerOut, status_code=201)
async def create_server(
    body: ServerCreate,
    db: aiosqlite.Connection = Depends(get_db),
):
    srv = await server_repo.create_server(
        db, body.name, body.address, body.port, body.type, body.check_params
    )
    return await _server_with_stats(db, srv)


@router.put("/servers/{server_id}", response_model=ServerOut)
async def update_server(
    server_id: int,
    body: ServerUpdate,
    db: aiosqlite.Connection = Depends(get_db),
):
    srv = await server_repo.update_server(
        db, server_id, body.name, body.address, body.port, body.type, body.check_params
    )
    if srv is None:
        raise HTTPException(status_code=404, detail="Server not found")
    return await _server_with_stats(db, srv)


@router.delete("/servers/{server_id}", status_code=204)
async def delete_server(
    server_id: int,
    db: aiosqlite.Connection = Depends(get_db),
):
    deleted = await server_repo.delete_server(db, server_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Server not found")


@router.patch("/servers/{server_id}/maintenance", response_model=ServerOut)
async def toggle_maintenance(
    server_id: int,
    db: aiosqlite.Connection = Depends(get_db),
):
    """Toggle maintenance mode for a server. Maintenance servers are monitored
    but excluded from pet HP damage."""
    srv = await server_repo.toggle_maintenance(db, server_id)
    if srv is None:
        raise HTTPException(status_code=404, detail="Server not found")
    mem_type = MemoryType.MAINTENANCE_ON if srv.maintenance_mode else MemoryType.MAINTENANCE_OFF
    await memory_repo.add_memory(db, mem_type, srv.name)
    return await _server_with_stats(db, srv)


@router.patch("/servers/{server_id}/move", response_model=list[ServerOut])
async def move_server(
    server_id: int,
    body: MoveServerRequest,
    db: aiosqlite.Connection = Depends(get_db),
):
    """Move a server up or down in the display order. Returns the full updated list."""
    srv = await server_repo.get_server(db, server_id)
    if srv is None:
        raise HTTPException(status_code=404, detail="Server not found")
    await server_repo.move_server(db, server_id, body.direction)
    servers = await server_repo.list_servers(db)
    return [await _server_with_stats(db, s) for s in servers]
