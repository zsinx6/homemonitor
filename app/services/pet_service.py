"""Pet service: interact and backup use cases."""
from __future__ import annotations

from datetime import datetime, timezone

from app.domain import constants as C
from app.domain.pet import apply_backup, apply_interact, Pet


class PetService:
    def __init__(self, pet_repo) -> None:
        self._pet_repo = pet_repo

    async def interact(self, db) -> Pet:
        pet = await self._pet_repo.get_pet(db)
        # Cooldown: return unchanged pet if interacted too recently
        if pet.last_interaction_date is not None:
            elapsed = (datetime.now(timezone.utc) - pet.last_interaction_date).total_seconds()
            if elapsed < C.INTERACT_COOLDOWN_SECONDS:
                return pet
        updated = apply_interact(pet)
        await self._pet_repo.save_pet(db, updated)
        return updated

    async def backup(self, db) -> Pet:
        pet = await self._pet_repo.get_pet(db)
        updated = apply_backup(pet)
        await self._pet_repo.save_pet(db, updated)
        return updated
