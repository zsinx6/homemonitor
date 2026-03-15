"""Context service — aggregates pet, server, and task state into a single snapshot.

ContextSnapshot is the single source of truth passed to LLM services and
returned by GET /api/status. It is cheap to build (3-4 local SQLite queries).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from app.domain import constants as C
from app.domain.pet import Pet, derive_status, get_evolution
from app.infrastructure.repositories import pet_repo, server_repo, task_repo


@dataclass
class ContextSnapshot:
    # ── Pet ──────────────────────────────────────────────────────────────────
    pet_name: str
    pet_level: int
    pet_species: str
    pet_stage: str
    pet_hp: int
    pet_hp_max: int
    pet_exp: int
    pet_max_exp: int
    pet_status: str
    pet_is_dead: bool

    # ── Infrastructure ───────────────────────────────────────────────────────
    servers_total: int
    servers_up: int
    servers_down: int
    servers_maintenance: int
    down_server_names: list[str]
    overall_uptime_pct: float

    # ── Tasks ────────────────────────────────────────────────────────────────
    tasks_pending: int
    tasks_completed_total: int

    # ── Backup ───────────────────────────────────────────────────────────────
    days_since_backup: Optional[int]

    # ── Meta ─────────────────────────────────────────────────────────────────
    generated_at: datetime

    # Raw pet — not serialised; used internally to avoid re-querying
    _raw_pet: Pet = field(repr=False, compare=False, default=None)  # type: ignore[assignment]

    # ─────────────────────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """JSON-serialisable representation for GET /api/status."""
        return {
            "pet": {
                "name": self.pet_name,
                "level": self.pet_level,
                "species": self.pet_species,
                "stage": self.pet_stage,
                "hp": self.pet_hp,
                "hp_max": self.pet_hp_max,
                "exp": self.pet_exp,
                "max_exp": self.pet_max_exp,
                "status": self.pet_status,
                "is_dead": self.pet_is_dead,
            },
            "infrastructure": {
                "servers_total": self.servers_total,
                "servers_up": self.servers_up,
                "servers_down": self.servers_down,
                "servers_maintenance": self.servers_maintenance,
                "down_servers": self.down_server_names,
                "overall_uptime_pct": round(self.overall_uptime_pct, 2),
            },
            "tasks": {
                "pending": self.tasks_pending,
                "completed_total": self.tasks_completed_total,
            },
            "maintenance": {
                "days_since_backup": self.days_since_backup,
            },
            "generated_at": self.generated_at.isoformat(),
        }

    def to_prompt_text(self) -> str:
        """Single-paragraph summary suitable for LLM system prompts."""
        parts: list[str] = [
            f"Digimon: {self.pet_species} (Lv.{self.pet_level} {self.pet_stage}), "
            f"HP {self.pet_hp}/{self.pet_hp_max}, EXP {self.pet_exp}/{self.pet_max_exp}, "
            f"Status: {self.pet_status}"
            + (" [DEAD — awaiting revival]" if self.pet_is_dead else "") + ".",
        ]

        if self.servers_total == 0:
            parts.append("No servers monitored yet.")
        else:
            srv_line = (
                f"Servers: {self.servers_total} total — "
                f"{self.servers_up} UP, {self.servers_down} DOWN"
            )
            if self.down_server_names:
                srv_line += f" ({', '.join(self.down_server_names)})"
            if self.servers_maintenance:
                srv_line += f", {self.servers_maintenance} in maintenance"
            srv_line += f". Overall uptime: {self.overall_uptime_pct:.1f}%."
            parts.append(srv_line)

        parts.append(
            f"Tasks: {self.tasks_pending} pending, "
            f"{self.tasks_completed_total} completed total."
        )

        if self.days_since_backup is None:
            parts.append("Backup status: NEVER run — critical risk!")
        elif self.days_since_backup >= C.BACKUP_OVERDUE_DAYS:
            parts.append(
                f"Backup status: OVERDUE by {self.days_since_backup - C.BACKUP_OVERDUE_DAYS} days!"
            )
        elif self.days_since_backup >= 20:
            parts.append(
                f"Backup status: {self.days_since_backup} days ago — getting stale."
            )
        else:
            parts.append(f"Backup status: {self.days_since_backup} day(s) ago — healthy.")

        return " ".join(parts)


async def build_snapshot(db: aiosqlite.Connection) -> ContextSnapshot:
    """Aggregate all state into a ContextSnapshot (3–4 SQLite queries)."""
    pet = await pet_repo.get_pet(db)
    servers = await server_repo.list_servers(db)
    tasks = await task_repo.list_tasks(db)
    total_completed = await task_repo.count_completed(db)

    any_down = any(s.status == "DOWN" and not s.maintenance_mode for s in servers)
    status = derive_status(pet, any_server_down=any_down)
    species, stage = get_evolution(pet.level)

    servers_up = sum(1 for s in servers if s.status == "UP" or s.maintenance_mode)
    servers_down = sum(1 for s in servers if s.status == "DOWN" and not s.maintenance_mode)
    servers_maintenance = sum(1 for s in servers if s.maintenance_mode)
    down_names = [s.name for s in servers if s.status == "DOWN" and not s.maintenance_mode]

    overall_uptime = (
        sum(s.uptime_percent for s in servers) / len(servers) if servers else 0.0
    )

    tasks_pending = sum(1 for t in tasks if not t.is_completed)

    days_since_backup: Optional[int] = None
    if pet.last_backup_date is not None:
        delta = datetime.now(timezone.utc) - pet.last_backup_date
        days_since_backup = int(delta.total_seconds() // 86400)

    return ContextSnapshot(
        pet_name=pet.name,
        pet_level=pet.level,
        pet_species=species,
        pet_stage=stage,
        pet_hp=pet.hp,
        pet_hp_max=C.HP_MAX,
        pet_exp=pet.exp,
        pet_max_exp=pet.max_exp,
        pet_status=status,
        pet_is_dead=pet.is_dead,
        servers_total=len(servers),
        servers_up=servers_up,
        servers_down=servers_down,
        servers_maintenance=servers_maintenance,
        down_server_names=down_names,
        overall_uptime_pct=overall_uptime,
        tasks_pending=tasks_pending,
        tasks_completed_total=total_completed,
        days_since_backup=days_since_backup,
        generated_at=datetime.now(timezone.utc),
        _raw_pet=pet,
    )
