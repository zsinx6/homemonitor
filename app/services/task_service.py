"""Task service: create and complete task use cases."""
from __future__ import annotations

from typing import Optional

from app.domain.pet import apply_complete_task


class TaskService:
    def __init__(self, pet_repo, task_repo) -> None:
        self._pet_repo = pet_repo
        self._task_repo = task_repo

    async def complete_task(self, db, task_id: int) -> Optional[object]:
        """Mark a task done, grant pet EXP+HP. Returns completed task or None."""
        task = await self._task_repo.complete_task(db, task_id)
        if task is None:
            return None
        pet = await self._pet_repo.get_pet(db)
        updated_pet = apply_complete_task(pet)
        await self._pet_repo.save_pet(db, updated_pet)
        return task
