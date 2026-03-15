"""Pet service: interact, backup, and revive use cases."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.domain import constants as C
from app.domain.memory import MemoryType
from app.domain.pet import apply_backup, apply_interact, apply_revive, Pet


class PetService:
    def __init__(self, pet_repo, memory_repo=None) -> None:
        self._pet_repo = pet_repo
        self._memory_repo = memory_repo

    async def _record(self, db, event_type: str, detail: Optional[str] = None) -> None:
        if self._memory_repo:
            await self._memory_repo.add_memory(db, event_type, detail)

    async def interact(self, db) -> tuple[Pet, bool]:
        """Interact with the pet. Returns (updated_pet, on_cooldown).

        Blocked (returns on_cooldown=True) when the pet is dead.
        """
        pet = await self._pet_repo.get_pet(db)
        if pet.is_dead:
            return pet, True
        if pet.last_interaction_date is not None:
            elapsed = (datetime.now(timezone.utc) - pet.last_interaction_date).total_seconds()
            if elapsed < C.INTERACT_COOLDOWN_SECONDS:
                return pet, True
        updated = apply_interact(pet)
        await self._pet_repo.save_pet(db, updated)
        # Record level-up or digivolution if it occurred
        if updated.last_event:
            if updated.last_event.startswith("digivolution:"):
                await self._record(db, MemoryType.DIGIVOLUTION, updated.last_event.split(":", 1)[1])
            elif updated.last_event == "level_up":
                await self._record(db, MemoryType.LEVEL_UP, str(updated.level))
        return updated, False

    async def backup(self, db) -> tuple[Pet, bool]:
        """Run a backup. Returns (updated_pet, on_cooldown).

        Blocked (returns on_cooldown=True) when the pet is dead.
        """
        pet = await self._pet_repo.get_pet(db)
        if pet.is_dead:
            return pet, True
        if pet.last_backup_date is not None:
            hours_elapsed = (datetime.now(timezone.utc) - pet.last_backup_date).total_seconds() / 3600
            if hours_elapsed < C.BACKUP_COOLDOWN_HOURS:
                return pet, True
        updated = apply_backup(pet)
        await self._pet_repo.save_pet(db, updated)
        await self._record(db, MemoryType.BACKUP)
        # Also capture level-up if EXP gain from backup caused it
        if updated.last_event:
            if updated.last_event.startswith("digivolution:"):
                await self._record(db, MemoryType.DIGIVOLUTION, updated.last_event.split(":", 1)[1])
            elif updated.last_event == "level_up":
                await self._record(db, MemoryType.LEVEL_UP, str(updated.level))
        return updated, False

    async def revive(self, db) -> Pet:
        """Revive the dead pet. No-op (returns current pet) if pet is alive."""
        pet = await self._pet_repo.get_pet(db)
        if not pet.is_dead:
            return pet
        updated = apply_revive(pet)
        await self._pet_repo.save_pet(db, updated)
        await self._record(db, MemoryType.REVIVAL)
        return updated
