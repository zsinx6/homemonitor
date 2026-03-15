"""Pet state repository — async DB read/write for pet_state table."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from app.domain.pet import Pet


def _row_to_pet(row: aiosqlite.Row) -> Pet:
    def _parse_dt(val: Optional[str]) -> Optional[datetime]:
        if val is None:
            return None
        return datetime.fromisoformat(val).replace(tzinfo=timezone.utc)

    return Pet(
        id=row["id"],
        name=row["name"],
        level=row["level"],
        exp=row["exp"],
        max_exp=row["max_exp"],
        hp=row["hp"],
        is_dead=bool(row["is_dead"]),
        last_backup_date=_parse_dt(row["last_backup_date"]),
        last_interaction_date=_parse_dt(row["last_interaction_date"]),
        last_event=row["last_event"],
        last_updated=_parse_dt(row["last_updated"]) or datetime.now(timezone.utc),
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
            last_event = ?, last_updated = ?
           WHERE id = 1""",
        (
            pet.name, pet.level, pet.exp, pet.max_exp, pet.hp, int(pet.is_dead),
            _fmt(pet.last_backup_date), _fmt(pet.last_interaction_date),
            pet.last_event, _fmt(pet.last_updated),
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
