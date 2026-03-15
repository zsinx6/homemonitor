"""Pydantic request and response models for the API."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Pet
# ---------------------------------------------------------------------------

class PetResponse(BaseModel):
    id: int
    name: str
    level: int
    exp: int
    max_exp: int
    hp: int
    hp_max: int
    status: str
    phrase: str
    last_event: Optional[str]
    last_backup_date: Optional[datetime]
    last_updated: datetime


class PetInteractResponse(BaseModel):
    exp: int
    phrase: str


class PetBackupResponse(BaseModel):
    exp: int
    hp: int
    phrase: str
    last_backup_date: datetime


# ---------------------------------------------------------------------------
# Servers
# ---------------------------------------------------------------------------

class DailyStatOut(BaseModel):
    date: str
    total_checks: int
    successful_checks: int
    uptime_percent: float


class ServerOut(BaseModel):
    id: int
    name: str
    address: str
    port: Optional[int]
    type: str
    status: str
    uptime_percent: float
    total_checks: int
    successful_checks: int
    last_error: Optional[str]
    last_checked: Optional[datetime]
    daily_stats: list[DailyStatOut] = Field(default_factory=list)


class ServerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    address: str = Field(..., min_length=1, max_length=500)
    port: Optional[int] = Field(None, ge=1, le=65535)
    type: str = Field(..., pattern="^(http|ping)$")


class ServerUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    address: str = Field(..., min_length=1, max_length=500)
    port: Optional[int] = Field(None, ge=1, le=65535)
    type: str = Field(..., pattern="^(http|ping)$")


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

class TaskOut(BaseModel):
    id: int
    task: str
    is_completed: bool
    created_at: datetime
    completed_at: Optional[datetime]


class TaskCreate(BaseModel):
    task: str = Field(..., min_length=1, max_length=500)
