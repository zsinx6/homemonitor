"""Pet service: interact, backup, and revive use cases."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from app.domain import constants as C
from app.domain.memory import MemoryType
from app.domain.pet import apply_backup, apply_clean, apply_focus_reward, apply_interact, apply_revive, parse_last_event, Pet

# Single asyncio lock shared across all PetService instances (new instance per request).
# Prevents concurrent requests from bypassing cooldowns via read-check-write races.
_pet_action_lock = asyncio.Lock()


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
        Lock prevents concurrent requests from bypassing the cooldown.
        """
        async with _pet_action_lock:
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
        Lock prevents concurrent requests from bypassing the cooldown.
        """
        async with _pet_action_lock:
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

        Returns success=False if the pet is dead or there is no dust.
        Lock prevents concurrent requests from cleaning the same dust twice.
        """
        async with _pet_action_lock:
            pet = await self._pet_repo.get_pet(db)
            if pet.is_dead or pet.dust_count == 0:
                return pet, False
            # Record DUST_CLEANED memory *before* EXP gain so a concurrent level-up
            # does not overwrite the dust_cleaned last_event in parse_last_event.
            await self._record(db, MemoryType.DUST_CLEANED)
            updated = apply_clean(pet)
            await self._pet_repo.save_pet(db, updated)
            # Still capture any level-up / digivolution that EXP triggered
            event_type, detail = parse_last_event(updated)
            if event_type:
                await self._record(db, event_type, detail)
            return updated, True

    async def focus_reward(self, db) -> tuple[Pet, bool]:
        """Complete a focus session. Returns (updated_pet, on_cooldown).

        Blocked (returns on_cooldown=True) when the pet is dead or within the
        FOCUS_COOLDOWN_MINUTES window since the last completed session.
        Lock prevents concurrent requests from bypassing the cooldown.
        """
        async with _pet_action_lock:
            pet = await self._pet_repo.get_pet(db)
            if pet.is_dead:
                return pet, True

            # Enforce cooldown using last_focus_date persisted on the pet row
            if pet.last_focus_date is not None:
                elapsed = (datetime.now(timezone.utc) - pet.last_focus_date).total_seconds()
                if elapsed < C.FOCUS_COOLDOWN_MINUTES * 60:
                    return pet, True

            # Record FOCUS_COMPLETE memory before EXP gain (level-up must not overwrite it)
            await self._record(db, MemoryType.FOCUS_COMPLETE)
            updated = apply_focus_reward(pet)
            await self._pet_repo.save_pet(db, updated)
            # Capture any level-up / digivolution triggered by the EXP gain
            event_type, detail = parse_last_event(updated)
            if event_type:
                await self._record(db, event_type, detail)
            return updated, False
