"""Server repository — async DB read/write for servers and server_daily_stats."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from app.infrastructure.repositories.common import parse_datetime


@dataclass
class ServerRow:
    id: int
    name: str
    address: str
    port: Optional[int]
    type: str
    status: str
    uptime_percent: float
    total_checks: int
    successful_checks: int
    last_error: Optional[str]
    last_checked: Optional[datetime]
    maintenance_mode: bool = False
    position: int = 0
    check_params: Optional[dict] = None


@dataclass
class DailyStatRow:
    date: str
    total_checks: int
    successful_checks: int
    uptime_percent: float


def _row_to_server(row: aiosqlite.Row) -> ServerRow:
    raw_params = row["check_params"] if "check_params" in row.keys() else None
    return ServerRow(
        id=row["id"],
        name=row["name"],
        address=row["address"],
        port=row["port"],
        type=row["type"],
        status=row["status"],
        uptime_percent=row["uptime_percent"],
        total_checks=row["total_checks"],
        successful_checks=row["successful_checks"],
        last_error=row["last_error"],
        last_checked=parse_datetime(row["last_checked"]),
        maintenance_mode=bool(row["maintenance_mode"]),
        position=row["position"] if "position" in row.keys() else 0,
        check_params=json.loads(raw_params) if raw_params else None,
    )


async def list_servers(db: aiosqlite.Connection) -> list[ServerRow]:
    db.row_factory = aiosqlite.Row
    async with db.execute("SELECT * FROM servers ORDER BY position, id") as cur:
        rows = await cur.fetchall()
    return [_row_to_server(r) for r in rows]


async def get_server(db: aiosqlite.Connection, server_id: int) -> Optional[ServerRow]:
    db.row_factory = aiosqlite.Row
    async with db.execute("SELECT * FROM servers WHERE id = ?", (server_id,)) as cur:
        row = await cur.fetchone()
    return _row_to_server(row) if row else None


async def create_server(
    db: aiosqlite.Connection,
    name: str,
    address: str,
    port: Optional[int],
    server_type: str,
    check_params: Optional[dict] = None,
) -> ServerRow:
    # New servers go to the end of the list
    async with db.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM servers") as cur:
        row = await cur.fetchone()
        next_pos = row[0] if row else 1
    params_json = json.dumps(check_params) if check_params else None
    async with db.execute(
        "INSERT INTO servers (name, address, port, type, position, check_params)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (name, address, port, server_type, next_pos, params_json),
    ) as cur:
        server_id = cur.lastrowid
    await db.commit()
    return await get_server(db, server_id)


async def update_server(
    db: aiosqlite.Connection,
    server_id: int,
    name: str,
    address: str,
    port: Optional[int],
    server_type: str,
    check_params: Optional[dict] = None,
) -> Optional[ServerRow]:
    params_json = json.dumps(check_params) if check_params else None
    await db.execute(
        "UPDATE servers SET name=?, address=?, port=?, type=?, check_params=? WHERE id=?",
        (name, address, port, server_type, params_json, server_id),
    )
    await db.commit()
    return await get_server(db, server_id)


async def delete_server(db: aiosqlite.Connection, server_id: int) -> bool:
    async with db.execute("DELETE FROM servers WHERE id = ?", (server_id,)) as cur:
        deleted = cur.rowcount > 0
    await db.commit()
    return deleted


async def toggle_maintenance(db: aiosqlite.Connection, server_id: int) -> Optional[ServerRow]:
    """Toggle maintenance_mode for a server. Returns updated row or None if not found."""
    server = await get_server(db, server_id)
    if server is None:
        return None
    new_mode = 0 if server.maintenance_mode else 1
    await db.execute(
        "UPDATE servers SET maintenance_mode = ? WHERE id = ?",
        (new_mode, server_id),
    )
    await db.commit()
    return await get_server(db, server_id)


async def move_server(
    db: aiosqlite.Connection,
    server_id: int,
    direction: str,
) -> Optional[ServerRow]:
    """Swap the position of server_id with its neighbour ('up' or 'down').

    Returns the updated server row, or None if not found / already at boundary.
    """
    server = await get_server(db, server_id)
    if server is None:
        return None

    db.row_factory = aiosqlite.Row
    if direction == "up":
        # Find the server with the largest position that is still < server.position
        query = (
            "SELECT * FROM servers WHERE position < ? ORDER BY position DESC LIMIT 1",
            (server.position,),
        )
    else:
        query = (
            "SELECT * FROM servers WHERE position > ? ORDER BY position ASC LIMIT 1",
            (server.position,),
        )

    async with db.execute(query[0], query[1]) as cur:
        neighbour_row = await cur.fetchone()
    if neighbour_row is None:
        return server  # already at boundary — no-op

    neighbour = _row_to_server(neighbour_row)
    # Swap positions
    await db.execute("UPDATE servers SET position = ? WHERE id = ?", (neighbour.position, server_id))
    await db.execute("UPDATE servers SET position = ? WHERE id = ?", (server.position, neighbour.id))
    await db.commit()
    return await get_server(db, server_id)


async def update_server_check_result(
    db: aiosqlite.Connection,
    server_id: int,
    is_up: bool,
    error: Optional[str],
    checked_at: datetime,
) -> None:
    """Update status, check counts, uptime %, and last_checked after a check."""
    status = "UP" if is_up else "DOWN"
    await db.execute(
        """UPDATE servers SET
            status = ?,
            total_checks = total_checks + 1,
            successful_checks = successful_checks + ?,
            uptime_percent = ROUND((CAST(successful_checks + ? AS REAL) /
                              (total_checks + 1)) * 100, 2),
            last_error = ?,
            last_checked = ?
           WHERE id = ?""",
        (status, int(is_up), int(is_up), error, checked_at.isoformat(), server_id),
    )
    await db.commit()


async def upsert_daily_stat(
    db: aiosqlite.Connection,
    server_id: int,
    date_str: str,
    is_up: bool,
) -> None:
    """Upsert today's daily stats row for the given server."""
    await db.execute(
        """INSERT INTO server_daily_stats (server_id, date, total_checks, successful_checks, uptime_percent)
           VALUES (?, ?, 1, ?, ROUND(CAST(? AS REAL) * 100, 2))
           ON CONFLICT(server_id, date) DO UPDATE SET
               total_checks = total_checks + 1,
               successful_checks = successful_checks + excluded.successful_checks,
               uptime_percent = ROUND((CAST(successful_checks + excluded.successful_checks AS REAL) /
                                (total_checks + 1)) * 100, 2)""",
        (server_id, date_str, int(is_up), int(is_up)),
    )
    await db.commit()


async def get_daily_stats(
    db: aiosqlite.Connection,
    server_id: int,
    limit: int = 7,
) -> list[DailyStatRow]:
    """Return up to ``limit`` most recent daily stat rows for a server."""
    db.row_factory = aiosqlite.Row
    async with db.execute(
        """SELECT date, total_checks, successful_checks, uptime_percent
           FROM server_daily_stats
           WHERE server_id = ?
           ORDER BY date DESC
           LIMIT ?""",
        (server_id, limit),
    ) as cur:
        rows = await cur.fetchall()
    return [
        DailyStatRow(
            date=r["date"],
            total_checks=r["total_checks"],
            successful_checks=r["successful_checks"],
            uptime_percent=r["uptime_percent"],
        )
        for r in rows
    ]
