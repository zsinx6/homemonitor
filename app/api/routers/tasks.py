"""Tasks API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

import aiosqlite

from app.api.dependencies import get_db, get_task_service
from app.api.models import TaskCreate, TaskOut
from app.infrastructure.repositories import task_repo

router = APIRouter()


def _task_out(t) -> TaskOut:
    return TaskOut(
        id=t.id,
        task=t.task,
        is_completed=t.is_completed,
        created_at=t.created_at,
        completed_at=t.completed_at,
    )


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(db: aiosqlite.Connection = Depends(get_db)):
    tasks = await task_repo.list_tasks(db)
    return [_task_out(t) for t in tasks]


@router.post("/tasks", response_model=TaskOut, status_code=201)
async def create_task(
    body: TaskCreate,
    db: aiosqlite.Connection = Depends(get_db),
):
    task = await task_repo.create_task(db, body.task)
    return _task_out(task)


@router.put("/tasks/{task_id}/complete", response_model=TaskOut)
async def complete_task(
    task_id: int,
    db: aiosqlite.Connection = Depends(get_db),
    task_service=Depends(get_task_service),
):
    task = await task_service.complete_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found or already completed")
    return _task_out(task)


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(
    task_id: int,
    db: aiosqlite.Connection = Depends(get_db),
):
    deleted = await task_repo.delete_task(db, task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Task not found")
    return Response(status_code=204)
