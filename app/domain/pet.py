"""Pet domain entity and pure business logic.

No I/O, no database, no FastAPI. All functions are pure transformations
that take a Pet and return a new Pet (immutable style via dataclass replace).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.domain import constants as C


@dataclass(frozen=True)
class Pet:
    id: int
    name: str
    level: int
    exp: int
    max_exp: int
    hp: int
    last_backup_date: Optional[datetime]
    last_interaction_date: Optional[datetime]
    last_event: Optional[str]
    last_updated: datetime


@dataclass(frozen=True)
class LevelUpResult:
    """Returned when a level-up occurs during an EXP gain."""
    new_level: int
    carried_exp: int
    new_max_exp: int


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _apply_exp_gain(pet: Pet, amount: int) -> Pet:
    """Add EXP, handle level-up with carry-over, return updated Pet."""
    new_exp = max(C.EXP_MIN, pet.exp + amount)
    level = pet.level
    max_exp = pet.max_exp
    last_event = pet.last_event

    while new_exp >= max_exp:
        new_exp -= max_exp
        level += 1
        max_exp = round(max_exp * C.LEVEL_UP_SCALE)
        last_event = "level_up"

    return replace(pet, exp=new_exp, level=level, max_exp=max_exp, last_event=last_event)


def _is_backup_overdue(pet: Pet) -> bool:
    if pet.last_backup_date is None:
        return False  # never backed up — no drain until first backup attempt
    cutoff = _now() - timedelta(days=C.BACKUP_OVERDUE_DAYS)
    return pet.last_backup_date < cutoff


def _has_interacted_recently(pet: Pet) -> bool:
    if pet.last_interaction_date is None:
        return False
    cutoff = _now() - timedelta(hours=C.LONELINESS_HOURS)
    return pet.last_interaction_date >= cutoff


def derive_status(pet: Pet, any_server_down: bool) -> str:
    """Derive the pet's display status from current state.

    Priority order: critical > injured > sad > lonely > happy.
    Status is never stored — always computed at read time.
    """
    if pet.hp == 0:
        return "critical"
    if pet.hp <= 3:
        return "injured"
    if any_server_down or pet.hp < C.HP_HAPPY_THRESHOLD:
        return "sad"
    if not _has_interacted_recently(pet):
        return "lonely"
    return "happy"


def apply_monitor_cycle(
    pet: Pet,
    down_server_names: list[str],
    recovered_server_names: list[str],
) -> Pet:
    """Apply one monitoring cycle's worth of EXP/HP changes.

    Called after every 60-second check cycle.
    """
    updated = replace(pet, last_updated=_now(), last_event=None)

    any_down = len(down_server_names) > 0

    # HP changes from downed servers
    if any_down:
        new_hp = _clamp(updated.hp - C.HP_LOSS_PER_DOWN_CYCLE, C.HP_MIN, C.HP_MAX)
        # Encode first downed server name so the router can use it for phrases
        updated = replace(updated, hp=new_hp, last_event=f"server_down:{down_server_names[0]}")

    # HP recovery from servers that came back up
    if recovered_server_names:
        recovery_hp = len(recovered_server_names) * C.HP_GAIN_ON_RECOVERY
        new_hp = _clamp(updated.hp + recovery_hp, C.HP_MIN, C.HP_MAX)
        # Encode first recovered server name so the router can use it for phrases
        updated = replace(updated, hp=new_hp, last_event=f"recovery:{recovered_server_names[0]}")

    # Passive HP drain when pet has not been interacted with recently
    if not _has_interacted_recently(updated):
        new_hp = _clamp(updated.hp - C.HP_DRAIN_LONELY, C.HP_MIN, C.HP_MAX)
        updated = replace(updated, hp=new_hp)

    # Backup overdue passive drain
    if _is_backup_overdue(updated):
        new_hp = _clamp(updated.hp - C.HP_DRAIN_BACKUP_OVERDUE, C.HP_MIN, C.HP_MAX)
        updated = replace(updated, hp=new_hp)

    # EXP gain only when all servers are up
    if not any_down:
        updated = _apply_exp_gain(updated, C.EXP_PER_HEALTHY_CYCLE)

    return updated


def apply_interact(pet: Pet) -> Pet:
    """Player pets the Digimon: gain EXP, update interaction timestamp."""
    updated = replace(pet, last_interaction_date=_now())
    return _apply_exp_gain(updated, C.EXP_INTERACT)


def apply_complete_task(pet: Pet) -> Pet:
    """Player completes a sysadmin task: gain EXP and restore HP."""
    new_hp = _clamp(pet.hp + C.HP_GAIN_COMPLETE_TASK, C.HP_MIN, C.HP_MAX)
    # Set task_done event before EXP gain — level_up will override if it triggers
    updated = replace(pet, hp=new_hp, last_event="task_done")
    return _apply_exp_gain(updated, C.EXP_COMPLETE_TASK)


def apply_backup(pet: Pet) -> Pet:
    """Player runs a backup: big EXP + HP gain, record backup date."""
    new_hp = _clamp(pet.hp + C.HP_GAIN_BACKUP, C.HP_MIN, C.HP_MAX)
    updated = replace(pet, hp=new_hp, last_backup_date=_now(), last_event="backup")
    return _apply_exp_gain(updated, C.EXP_BACKUP)
