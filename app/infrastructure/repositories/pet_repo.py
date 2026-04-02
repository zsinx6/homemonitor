"""Pet state repository — async DB read/write for pet_state table."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from app.domain.pet import Pet
from app.infrastructure.repositories.common import parse_datetime


def _row_to_pet(row: aiosqlite.Row) -> Pet:
    keys = row.keys()
    return Pet(
        id=row["id"],
        name=row["name"],
        level=row["level"],
        exp=row["exp"],
        max_exp=row["max_exp"],
        hp=row["hp"],
        is_dead=bool(row["is_dead"]),
        last_backup_date=parse_datetime(row["last_backup_date"]),
        last_interaction_date=parse_datetime(row["last_interaction_date"]),
        last_event=row["last_event"],
        last_updated=parse_datetime(row["last_updated"]) or datetime.now(timezone.utc),
        dust_count=row["dust_count"] if "dust_count" in keys else 0,
        last_dust_date=parse_datetime(row["last_dust_date"]) if "last_dust_date" in keys else None,
        current_mood=row["current_mood"] if "current_mood" in keys else "Energetic",
        last_mood_change=parse_datetime(row["last_mood_change"]) if "last_mood_change" in keys else None,
        last_focus_date=parse_datetime(row["last_focus_date"]) if "last_focus_date" in keys else None,
        last_dust_drain_at=parse_datetime(row["last_dust_drain_at"]) if "last_dust_drain_at" in keys else None,
    )


def _fmt(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.isoformat()


async def get_pet(db: aiosqlite.Connection) -> Pet:
    db.row_factory = aiosqlite.Row
    async with db.execute("SELECT * FROM pet_state WHERE id = 1") as cur:
        row = await cur.fetchone()
    if row is None:
        raise RuntimeError("Pet seed row missing — was init_db() called?")
    return _row_to_pet(row)


async def save_pet(db: aiosqlite.Connection, pet: Pet, *, commit: bool = True) -> None:
    await db.execute(
        """UPDATE pet_state SET
            name = ?, level = ?, exp = ?, max_exp = ?, hp = ?, is_dead = ?,
            last_backup_date = ?, last_interaction_date = ?,
            last_event = ?, last_updated = ?,
            dust_count = ?, last_dust_date = ?,
            current_mood = ?, last_mood_change = ?,
            last_focus_date = ?, last_dust_drain_at = ?
           WHERE id = 1""",
        (
            pet.name, pet.level, pet.exp, pet.max_exp, pet.hp, int(pet.is_dead),
            _fmt(pet.last_backup_date), _fmt(pet.last_interaction_date),
            pet.last_event, _fmt(pet.last_updated),
            pet.dust_count, _fmt(pet.last_dust_date),
            pet.current_mood, _fmt(pet.last_mood_change),
            _fmt(pet.last_focus_date), _fmt(pet.last_dust_drain_at),
        ),
    )
    if commit:
        await db.commit()


async def clear_last_event(db: aiosqlite.Connection) -> None:
    """One-shot delivery: clear last_event after it has been read."""
    await db.execute("UPDATE pet_state SET last_event = NULL WHERE id = 1")
    await db.commit()


async def rename_pet(db: aiosqlite.Connection, name: str) -> Pet:
    """Update the pet's display name."""
    await db.execute("UPDATE pet_state SET name = ? WHERE id = 1", (name,))
    await db.commit()
    return await get_pet(db)
