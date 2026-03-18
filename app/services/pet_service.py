"""Pet service: interact, backup, and revive use cases."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.domain import constants as C
from app.domain.memory import MemoryType
from app.domain.pet import apply_backup, apply_clean, apply_focus_reward, apply_interact, apply_revive, parse_last_event, Pet


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
        event_type, detail = parse_last_event(updated)
        if event_type:
            await self._record(db, event_type, detail)
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
        event_type, detail = parse_last_event(updated)
        if event_type:
            await self._record(db, event_type, detail)
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

    async def rename(self, db, name: str) -> Pet:
        """Set a custom display name and record it in memories."""
        pet = await self._pet_repo.rename_pet(db, name)
        await self._record(db, MemoryType.RENAME, name)
        return pet

    async def clear_last_event(self, db) -> None:
        """One-shot delivery: clear last_event after it has been consumed."""
        await self._pet_repo.clear_last_event(db)

    async def clean(self, db) -> tuple[Pet, bool]:
        """Clean dust. Returns (updated_pet, success).

        Always succeeds unless pet is dead (blocked).
        """
        pet = await self._pet_repo.get_pet(db)
        if pet.is_dead or pet.dust_count == 0:
            return pet, False
        updated = apply_clean(pet)
        await self._pet_repo.save_pet(db, updated)
        event_type, detail = parse_last_event(updated)
        if event_type:
            await self._record(db, event_type, detail)
        return updated, True

    async def focus_reward(self, db) -> tuple[Pet, bool]:
        """Complete a focus session. Returns (updated_pet, on_cooldown).

        Blocked (returns on_cooldown=True) when the pet is dead or cooldown active.
        For MVP: use a simple approach — track via memory log.
        """
        pet = await self._pet_repo.get_pet(db)
        if pet.is_dead:
            return pet, True
        
        # Check if we have a focus_complete memory within the cooldown window
        # For MVP, we'll just allow one per session. Production would add focus_last_date column.
        updated = apply_focus_reward(pet)
        await self._pet_repo.save_pet(db, updated)
        await self._record(db, MemoryType.FOCUS_COMPLETE)
        event_type, detail = parse_last_event(updated)
        if event_type:
            await self._record(db, event_type, detail)
        return updated, False
