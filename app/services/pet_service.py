"""Pet service: interact and backup use cases."""
from __future__ import annotations

from datetime import datetime, timezone

from app.domain import constants as C
from app.domain.pet import apply_backup, apply_interact, Pet


class PetService:
    def __init__(self, pet_repo) -> None:
        self._pet_repo = pet_repo

    async def interact(self, db) -> tuple[Pet, bool]:
        """Interact with the pet. Returns (updated_pet, on_cooldown)."""
        pet = await self._pet_repo.get_pet(db)
        if pet.last_interaction_date is not None:
            elapsed = (datetime.now(timezone.utc) - pet.last_interaction_date).total_seconds()
            if elapsed < C.INTERACT_COOLDOWN_SECONDS:
                return pet, True
        updated = apply_interact(pet)
        await self._pet_repo.save_pet(db, updated)
        return updated, False

    async def backup(self, db) -> tuple[Pet, bool]:
        """Run a backup. Returns (updated_pet, on_cooldown)."""
        pet = await self._pet_repo.get_pet(db)
        if pet.last_backup_date is not None:
            hours_elapsed = (datetime.now(timezone.utc) - pet.last_backup_date).total_seconds() / 3600
            if hours_elapsed < C.BACKUP_COOLDOWN_HOURS:
                return pet, True
        updated = apply_backup(pet)
        await self._pet_repo.save_pet(db, updated)
        return updated, False
