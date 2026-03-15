"""Pet API routes."""
from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, Depends

import aiosqlite

from app.api.dependencies import get_db, get_pet_service, get_phrase_selector
from app.api.models import PetBackupResponse, PetInteractResponse, PetResponse
from app.domain import constants as C
from app.domain.pet import derive_status, get_evolution, get_next_evolution_level
from app.domain.phrases import PhraseContext
from app.infrastructure.repositories import pet_repo, server_repo

router = APIRouter()


def _decode_event(last_event: str | None) -> tuple[str | None, str | None]:
    """Split 'event_type:detail' → (type, detail). Returns (None, None) if no event."""
    if not last_event:
        return None, None
    if ":" in last_event:
        event_type, detail = last_event.split(":", 1)
        return event_type, detail
    return last_event, None


async def _build_pet_response(db, phrase_selector) -> PetResponse:
    pet = await pet_repo.get_pet(db)
    servers = await server_repo.list_servers(db)
    any_down = any(s.status == "DOWN" and not s.maintenance_mode for s in servers)
    status = derive_status(pet, any_server_down=any_down)
    species, stage = get_evolution(pet.level)
    next_evo_level = get_next_evolution_level(pet.level)

    # Compute server-authoritative backup cooldown remaining
    if pet.last_backup_date is not None:
        elapsed_s = (datetime.now(timezone.utc) - pet.last_backup_date).total_seconds()
        backup_remaining = max(0, int(C.BACKUP_COOLDOWN_HOURS * 3600 - elapsed_s))
    else:
        backup_remaining = 0

    # Decode last_event — may carry an encoded server name as detail
    event_type, event_detail = _decode_event(pet.last_event)

    # Select context-aware phrase, prioritising event over status
    ctx_map = {
        "happy": PhraseContext.HAPPY,
        "lonely": PhraseContext.LONELY,
        "sad": PhraseContext.SAD,
        "injured": PhraseContext.INJURED,
        "critical": PhraseContext.CRITICAL,
    }
    if event_type == "server_down":
        server_name = event_detail or "unknown"
        phrase = await phrase_selector.select(
            PhraseContext.SERVER_DOWN, {"server_name": server_name}
        )
    elif event_type == "level_up":
        phrase = await phrase_selector.select(
            PhraseContext.LEVEL_UP, {"level": pet.level, "species": species}
        )
    elif event_type == "digivolution":
        new_species = event_detail or species
        phrase = await phrase_selector.select(
            PhraseContext.DIGIVOLUTION, {"species": new_species}
        )
    elif event_type == "recovery":
        server_name = event_detail or "server"
        phrase = await phrase_selector.select(
            PhraseContext.RECOVERY, {"server_name": server_name}
        )
    elif event_type == "backup":
        phrase = await phrase_selector.select(PhraseContext.BACKUP, {})
    elif event_type == "task_done":
        phrase = await phrase_selector.select(PhraseContext.TASK_DONE, {})
    elif event_type == "death":
        phrase = await phrase_selector.select(PhraseContext.DEATH, {})
    elif event_type == "revival":
        phrase = await phrase_selector.select(PhraseContext.REVIVAL, {})
    else:
        phrase = await phrase_selector.select(ctx_map.get(status, PhraseContext.HAPPY), {})

    # Deliver only the clean event type to the frontend (strip encoded detail)
    clean_event = event_type
    if clean_event:
        await pet_repo.clear_last_event(db)

    return PetResponse(
        id=pet.id,
        name=pet.name,
        level=pet.level,
        exp=pet.exp,
        max_exp=pet.max_exp,
        hp=pet.hp,
        hp_max=C.HP_MAX,
        is_dead=pet.is_dead,
        status=status,
        phrase=phrase,
        evolution=species,
        evolution_stage=stage,
        evolution_next_level=next_evo_level,
        last_event=clean_event,
        last_backup_date=pet.last_backup_date,
        last_interaction_date=pet.last_interaction_date,
        last_updated=pet.last_updated,
        backup_cooldown_remaining_seconds=backup_remaining,
    )


@router.get("/pet", response_model=PetResponse)
async def get_pet_state(
    db: aiosqlite.Connection = Depends(get_db),
    phrase_selector=Depends(get_phrase_selector),
):
    return await _build_pet_response(db, phrase_selector)


@router.post("/pet/interact", response_model=PetInteractResponse)
async def interact(
    db: aiosqlite.Connection = Depends(get_db),
    pet_service=Depends(get_pet_service),
    phrase_selector=Depends(get_phrase_selector),
):
    pet, on_cooldown = await pet_service.interact(db)
    if pet.is_dead:
        phrase = await phrase_selector.select(PhraseContext.DEATH, {})
    elif on_cooldown:
        phrase = await phrase_selector.select(PhraseContext.INTERACT_COOLDOWN, {})
    else:
        phrase = await phrase_selector.select(PhraseContext.INTERACT, {})
    return PetInteractResponse(exp=pet.exp, phrase=phrase, on_cooldown=on_cooldown)


@router.post("/pet/backup", response_model=PetBackupResponse)
async def backup(
    db: aiosqlite.Connection = Depends(get_db),
    pet_service=Depends(get_pet_service),
    phrase_selector=Depends(get_phrase_selector),
):
    pet, on_cooldown = await pet_service.backup(db)
    if pet.is_dead:
        phrase = await phrase_selector.select(PhraseContext.DEATH, {})
    elif on_cooldown:
        phrase = await phrase_selector.select(PhraseContext.BACKUP_COOLDOWN, {})
    else:
        phrase = await phrase_selector.select(PhraseContext.BACKUP, {})
    return PetBackupResponse(
        exp=pet.exp,
        hp=pet.hp,
        phrase=phrase,
        on_cooldown=on_cooldown,
        last_backup_date=pet.last_backup_date,
    )


@router.post("/pet/revive", response_model=PetResponse)
async def revive(
    db: aiosqlite.Connection = Depends(get_db),
    pet_service=Depends(get_pet_service),
    phrase_selector=Depends(get_phrase_selector),
):
    """Revive the dead pet. Resets HP to HP_REVIVE and clears EXP. No-op if alive."""
    await pet_service.revive(db)
    return await _build_pet_response(db, phrase_selector)
