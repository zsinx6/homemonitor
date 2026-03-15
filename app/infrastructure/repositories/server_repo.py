"""Server repository — async DB read/write for servers and server_daily_stats."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import aiosqlite


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


@dataclass
class DailyStatRow:
    date: str
    total_checks: int
    successful_checks: int
    uptime_percent: float


def _row_to_server(row: aiosqlite.Row) -> ServerRow:
    def _parse_dt(val: Optional[str]) -> Optional[datetime]:
        if val is None:
            return None
        return datetime.fromisoformat(val).replace(tzinfo=timezone.utc)

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
        last_checked=_parse_dt(row["last_checked"]),
    )


async def list_servers(db: aiosqlite.Connection) -> list[ServerRow]:
    db.row_factory = aiosqlite.Row
    async with db.execute("SELECT * FROM servers ORDER BY id") as cur:
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
) -> ServerRow:
    async with db.execute(
        "INSERT INTO servers (name, address, port, type) VALUES (?, ?, ?, ?)",
        (name, address, port, server_type),
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
) -> Optional[ServerRow]:
    await db.execute(
        "UPDATE servers SET name=?, address=?, port=?, type=? WHERE id=?",
        (name, address, port, server_type, server_id),
    )
    await db.commit()
    return await get_server(db, server_id)


async def delete_server(db: aiosqlite.Connection, server_id: int) -> bool:
    async with db.execute("DELETE FROM servers WHERE id = ?", (server_id,)) as cur:
        deleted = cur.rowcount > 0
    await db.commit()
    return deleted


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
           VALUES (?, ?, 1, ?, ?)
           ON CONFLICT(server_id, date) DO UPDATE SET
               total_checks = total_checks + 1,
               successful_checks = successful_checks + excluded.successful_checks,
               uptime_percent = ROUND((CAST(successful_checks + excluded.successful_checks AS REAL) /
                                (total_checks + 1)) * 100, 2)""",
        (server_id, date_str, int(is_up), 100.0 if is_up else 0.0),
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
