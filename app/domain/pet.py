"""Pet domain entity and pure business logic.

No I/O, no database, no FastAPI. All functions are pure transformations
that take a Pet and return a new Pet (immutable style via dataclass replace).
"""
from __future__ import annotations

import random
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
    is_dead: bool = False
    dust_count: int = 0
    last_dust_date: Optional[datetime] = None
    current_mood: str = "Energetic"
    last_mood_change: Optional[datetime] = None
    last_focus_date: Optional[datetime] = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _apply_exp_gain(pet: Pet, amount: int) -> Pet:
    """Add EXP, handle level-up with carry-over, return updated Pet.

    Emits ``last_event = "level_up"`` on a regular level-up.
    Emits ``last_event = "digivolution:<species>"`` when the level-up
    crosses a tier boundary (species name changes), so the router can
    display a special digivolution phrase.

    On any level-up the pet's name is synced to the new species.
    """
    new_exp = max(C.EXP_MIN, pet.exp + amount)
    level = pet.level
    max_exp = pet.max_exp
    last_event = pet.last_event
    name = pet.name

    while new_exp >= max_exp:
        new_exp -= max_exp
        old_species, _ = get_evolution(level)
        level += 1
        max_exp = round(max_exp * C.LEVEL_UP_SCALE)
        new_species, _ = get_evolution(level)
        name = new_species
        if new_species != old_species:
            last_event = f"digivolution:{new_species}"
        else:
            last_event = "level_up"

    return replace(pet, exp=new_exp, level=level, max_exp=max_exp,
                   last_event=last_event, name=name)


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

    Priority order: dead > critical > injured > sad > lonely > happy.
    Status is never stored — always computed at read time.
    """
    if pet.is_dead:
        return "dead"
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
    Dead pets do not accumulate EXP or HP changes — they wait for revival.
    """
    updated = replace(pet, last_updated=_now(), last_event=None)

    # Dead pets are frozen — no changes until revived
    if pet.is_dead:
        return updated

    any_down = len(down_server_names) > 0

    # HP loss scales with the number of downed servers
    if any_down:
        total_loss = len(down_server_names) * C.HP_LOSS_PER_DOWN_CYCLE
        new_hp = _clamp(updated.hp - total_loss, C.HP_MIN, C.HP_MAX)
        names_str = ", ".join(down_server_names[:3])
        if len(down_server_names) > 3:
            names_str += f" (+{len(down_server_names) - 3} more)"
        updated = replace(updated, hp=new_hp, last_event=f"server_down:{names_str}")

    # HP recovery from servers that came back up
    if recovered_server_names:
        recovery_hp = len(recovered_server_names) * C.HP_GAIN_ON_RECOVERY
        new_hp = _clamp(updated.hp + recovery_hp, C.HP_MIN, C.HP_MAX)
        updated = replace(updated, hp=new_hp, last_event=f"recovery:{recovered_server_names[0]}")

    # Passive HP drain when pet has not been interacted with recently
    if not _has_interacted_recently(updated):
        new_hp = _clamp(updated.hp - C.HP_DRAIN_LONELY, C.HP_MIN, C.HP_MAX)
        updated = replace(updated, hp=new_hp)

    # Backup overdue passive drain
    if _is_backup_overdue(updated):
        new_hp = _clamp(updated.hp - C.HP_DRAIN_BACKUP_OVERDUE, C.HP_MIN, C.HP_MAX)
        updated = replace(updated, hp=new_hp)

    # Death: HP just hit 0 this cycle
    if updated.hp == 0 and not pet.is_dead:
        return replace(updated, is_dead=True, last_event="death")

    # EXP gain only when all servers are up
    if not any_down:
        updated = _apply_exp_gain(updated, C.EXP_PER_HEALTHY_CYCLE)

    return updated


def apply_interact(pet: Pet) -> Pet:
    """Player pets the Digimon: gain EXP and HP, update interaction timestamp."""
    new_hp = _clamp(pet.hp + C.HP_GAIN_INTERACT, C.HP_MIN, C.HP_MAX)
    updated = replace(pet, last_interaction_date=_now(), hp=new_hp)
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


def apply_revive(pet: Pet) -> Pet:
    """Revive a dead pet: restore HP, reset EXP, clear death flag and dust.

    Keeps level as-is so progression isn't fully wiped, but EXP resets to 0
    as a meaningful penalty. HP is restored to HP_REVIVE (not full) so the
    player still needs to care for the pet after revival. Dust is cleared so
    the pet doesn't immediately resume taking dust-drain damage after revival.
    """
    return replace(
        pet,
        hp=C.HP_REVIVE,
        exp=0,
        is_dead=False,
        dust_count=0,
        last_event="revival",
        last_updated=_now(),
    )


def apply_clean(pet: Pet) -> Pet:
    """Player cleans dust: reset dust_count, gain EXP.

    The dust_cleaned event is recorded via a direct memory call in the service
    layer before EXP is applied, so a level-up cannot overwrite it.
    """
    updated = replace(pet, dust_count=0)
    return _apply_exp_gain(updated, C.EXP_CLEAN_REWARD)


def apply_focus_reward(pet: Pet) -> Pet:
    """Player completes a focus session: gain EXP and HP.

    The focus_complete event is recorded via a direct memory call in the
    service layer before EXP is applied, so a level-up cannot overwrite it.
    """
    new_hp = _clamp(pet.hp + C.HP_FOCUS_REWARD, C.HP_MIN, C.HP_MAX)
    updated = replace(pet, hp=new_hp, last_focus_date=_now())
    return _apply_exp_gain(updated, C.EXP_FOCUS_REWARD)


def apply_dust_spawn(pet: Pet) -> Pet:
    """Attempt to spawn dust. Called once per monitor cycle.
    
    Dust spawns at most once per DUST_SPAWN_HOURS. Each spawn = +1 dust count.
    Max dust is capped at MAX_DUST.
    Returns updated Pet with dust_count and last_dust_date set, or unchanged if no spawn.
    """
    now = _now()
    
    # Check if enough time has passed since last dust spawn
    if pet.last_dust_date is not None:
        elapsed = now - pet.last_dust_date
        if elapsed < timedelta(hours=C.DUST_SPAWN_HOURS):
            return pet
    
    # Can we spawn?
    if pet.dust_count >= C.MAX_DUST:
        return pet
    
    # Spawn dust
    new_dust = pet.dust_count + 1
    return replace(pet, dust_count=new_dust, last_dust_date=now)


def apply_mood_rotation(pet: Pet) -> Pet:
    """Attempt to rotate the pet's mood. Called once per monitor cycle.

    Mood rotates at most once per 24 hours. Guarantees a *different* mood is
    selected so the change is always visible to the user.
    Returns unchanged if not time for rotation yet.
    """
    now = _now()

    # Check if enough time has passed since last mood change
    if pet.last_mood_change is not None:
        elapsed = now - pet.last_mood_change
        if elapsed < timedelta(hours=24):
            return pet

    # Rotate to a different mood than current
    available = [m for m in C.MOODS if m != pet.current_mood]
    new_mood = random.choice(available) if available else pet.current_mood
    return replace(pet, current_mood=new_mood, last_mood_change=now)


def apply_dust_hp_drain(pet: Pet) -> Pet:
    """Apply HP drain if at max dust. Drains C.HP_DRAIN_MAX_DUST HP.

    The caller (monitor_service) is responsible for throttling this to once
    every DUST_HP_DRAIN_CYCLE_MODULO cycles using a deterministic timestamp check.

    Returns:
        Updated Pet with reduced HP, or unchanged if dust not at max.
    """
    if pet.dust_count < C.MAX_DUST:
        return pet

    new_hp = _clamp(pet.hp - C.HP_DRAIN_MAX_DUST, C.HP_MIN, C.HP_MAX)
    return replace(pet, hp=new_hp)


def get_evolution(level: int) -> tuple[str, str]:
    """Return (species_name, stage_name) for the given level.

    Uses EVOLUTION_TIERS from constants; falls back to the highest tier.
    """
    for tier in C.EVOLUTION_TIERS:
        if tier["min_level"] <= level <= tier["max_level"]:
            return tier["species"], tier["stage"]
    last = C.EVOLUTION_TIERS[-1]
    return last["species"], last["stage"]


def get_next_evolution_level(level: int) -> int | None:
    """Return the level at which the next evolution occurs, or None if at max tier."""
    for i, tier in enumerate(C.EVOLUTION_TIERS):
        if tier["min_level"] <= level <= tier["max_level"]:
            if i + 1 < len(C.EVOLUTION_TIERS):
                return C.EVOLUTION_TIERS[i + 1]["min_level"]
            return None  # already at highest tier
    return None


def parse_last_event(pet: Pet) -> tuple[str | None, str | None]:
    """Extract a recordable memory event from pet.last_event.

    Returns (event_type, detail) where event_type matches MemoryType string
    constants, or (None, None) if last_event holds no memory-worthy event.
    """
    if not pet.last_event:
        return None, None
    if pet.last_event.startswith("digivolution:"):
        return "digivolution", pet.last_event.split(":", 1)[1]
    if pet.last_event == "level_up":
        return "level_up", str(pet.level)
    return None, None
