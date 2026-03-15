"""Task service: create and complete task use cases."""
from __future__ import annotations

from typing import Optional

from app.domain.memory import MemoryType
from app.domain.pet import apply_complete_task


class TaskService:
    def __init__(self, pet_repo, task_repo, memory_repo=None) -> None:
        self._pet_repo = pet_repo
        self._task_repo = task_repo
        self._memory_repo = memory_repo

    async def complete_task(self, db, task_id: int) -> Optional[object]:
        """Mark a task done and grant pet EXP+HP in a single transaction."""
        task = await self._task_repo.complete_task(db, task_id, commit=False)
        if task is None:
            return None
        pet = await self._pet_repo.get_pet(db)
        updated_pet = apply_complete_task(pet)
        await self._pet_repo.save_pet(db, updated_pet, commit=False)
        await db.commit()
        # Record memories after successful commit
        if self._memory_repo:
            await self._memory_repo.add_memory(db, MemoryType.TASK_COMPLETE, task.task)
            if updated_pet.last_event:
                if updated_pet.last_event.startswith("digivolution:"):
                    species = updated_pet.last_event.split(":", 1)[1]
                    await self._memory_repo.add_memory(db, MemoryType.DIGIVOLUTION, species)
                elif updated_pet.last_event == "level_up":
                    await self._memory_repo.add_memory(db, MemoryType.LEVEL_UP, str(updated_pet.level))
        return task
