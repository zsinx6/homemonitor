"""Pydantic request and response models for the API."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


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
    is_dead: bool
    status: str
    phrase: str
    evolution: str
    evolution_stage: str
    evolution_next_level: Optional[int]
    last_event: Optional[str]
    last_backup_date: Optional[datetime]
    last_interaction_date: Optional[datetime]
    last_updated: datetime
    backup_cooldown_remaining_seconds: int = 0
    days_since_backup: Optional[int] = None


class PetInteractResponse(BaseModel):
    exp: int
    phrase: str
    on_cooldown: bool = False


class PetBackupResponse(BaseModel):
    exp: int
    hp: int
    phrase: str
    on_cooldown: bool = False
    last_backup_date: Optional[datetime]


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
    maintenance_mode: bool = False


class _ServerBase(BaseModel):
    """Shared fields and validators for server create/update."""
    name: str = Field(..., min_length=1, max_length=100)
    address: str = Field(..., min_length=1, max_length=500)
    port: Optional[int] = Field(None, ge=1, le=65535)
    type: str = Field(..., pattern="^(http|ping)$")

    @field_validator("name", "address", mode="before")
    @classmethod
    def strip_and_require_non_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank or whitespace-only")
        return v

    @model_validator(mode="after")
    def validate_ping_address(self):
        if self.type == "ping" and "://" in self.address:
            raise ValueError(
                "Ping address must be a hostname or IP — remove the URL scheme (e.g. http://)"
            )
        if self.type == "ping" and self.port is not None:
            raise ValueError("Ping checks do not use ports — remove the port value")
        return self


class ServerCreate(_ServerBase):
    pass


class ServerUpdate(_ServerBase):
    pass


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

class TaskOut(BaseModel):
    id: int
    task: str
    is_completed: bool
    created_at: datetime
    completed_at: Optional[datetime]


class TaskListResponse(BaseModel):
    tasks: list[TaskOut]
    total_completed: int


class TaskCreate(BaseModel):
    task: str = Field(..., min_length=1, max_length=500)

    @field_validator("task", mode="before")
    @classmethod
    def strip_and_require_non_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank or whitespace-only")
        return v


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)

    @field_validator("message", mode="before")
    @classmethod
    def strip_message(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank or whitespace-only")
        return v


class ChatResponse(BaseModel):
    response: str


class PetRenameRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)

    @field_validator("name", mode="before")
    @classmethod
    def strip_and_require_non_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank or whitespace-only")
        return v


# ---------------------------------------------------------------------------
# Memories
# ---------------------------------------------------------------------------

class MemoryOut(BaseModel):
    id: int
    event_type: str
    detail: Optional[str]
    occurred_at: datetime


class MemoryListResponse(BaseModel):
    memories: list[MemoryOut]
    total: int
    summary: dict[str, int] = Field(default_factory=dict)
