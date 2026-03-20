"""Pet API routes."""
from __future__ import annotations

from datetime import datetime, timezone
from math import ceil

from fastapi import APIRouter, Depends

import aiosqlite

from app.api.dependencies import get_db, get_pet_service, get_phrase_selector
from app.api.models import PetBackupResponse, PetCleanResponse, PetFocusResponse, PetInteractResponse, PetRenameRequest, PetResponse
from app.domain import constants as C
from app.domain.pet import get_next_evolution_level
from app.domain.phrases import PhraseContext
from app.services import context_service
from app.services.pet_service import PetService

router = APIRouter()


def _decode_event(last_event: str | None) -> tuple[str | None, str | None]:
    """Split 'event_type:detail' → (type, detail). Returns (None, None) if no event."""
    if not last_event:
        return None, None
    if ":" in last_event:
        event_type, detail = last_event.split(":", 1)
        return event_type, detail
    return last_event, None


async def _build_pet_response(db, phrase_selector, pet_service: PetService) -> PetResponse:
    # Single aggregation call — provides context for LLM phrases
    snapshot = await context_service.build_snapshot(db)
    pet = snapshot._raw_pet

    next_evo_level = get_next_evolution_level(pet.level)

    # Compute server-authoritative backup cooldown remaining
    if pet.last_backup_date is not None:
        elapsed_s = (datetime.now(timezone.utc) - pet.last_backup_date).total_seconds()
        backup_remaining = max(0, ceil(C.BACKUP_COOLDOWN_HOURS * 3600 - elapsed_s))
    else:
        backup_remaining = 0

    # Compute focus cooldown remaining
    if pet.last_focus_date is not None:
        elapsed_s = (datetime.now(timezone.utc) - pet.last_focus_date).total_seconds()
        focus_remaining = max(0, ceil(C.FOCUS_COOLDOWN_MINUTES * 60 - elapsed_s))
    else:
        focus_remaining = 0

    # Decode last_event — may carry an encoded server name as detail
    event_type, event_detail = _decode_event(pet.last_event)

    # Context dict injected into every phrase selector call so LLM has full state
    ctx = {"__context__": snapshot, "species": snapshot.pet_species}

    # Select context-aware phrase, prioritising event over status
    status_ctx_map = {
        "happy": PhraseContext.HAPPY,
        "lonely": PhraseContext.LONELY,
        "sad": PhraseContext.SAD,
        "injured": PhraseContext.INJURED,
        "critical": PhraseContext.CRITICAL,
    }
    if event_type == "server_down":
        phrase = await phrase_selector.select(
            PhraseContext.SERVER_DOWN, {**ctx, "server_name": event_detail or "unknown"}
        )
    elif event_type == "level_up":
        phrase = await phrase_selector.select(
            PhraseContext.LEVEL_UP, {**ctx, "level": pet.level}
        )
    elif event_type == "digivolution":
        phrase = await phrase_selector.select(
            PhraseContext.DIGIVOLUTION, {**ctx, "species": event_detail or snapshot.pet_species}
        )
    elif event_type == "recovery":
        phrase = await phrase_selector.select(
            PhraseContext.RECOVERY, {**ctx, "server_name": event_detail or "server"}
        )
    elif event_type == "backup":
        phrase = await phrase_selector.select(PhraseContext.BACKUP, ctx)
    elif event_type == "task_done":
        phrase = await phrase_selector.select(PhraseContext.TASK_DONE, ctx)
    elif event_type == "death":
        phrase = await phrase_selector.select(PhraseContext.DEATH, ctx)
    elif event_type == "revival":
        phrase = await phrase_selector.select(PhraseContext.REVIVAL, ctx)
    else:
        phrase = await phrase_selector.select(
            status_ctx_map.get(snapshot.pet_status, PhraseContext.HAPPY), ctx
        )

    # Deliver only the clean event type to the frontend (strip encoded detail)
    clean_event = event_type
    if clean_event:
        await pet_service.clear_last_event(db)

    return PetResponse(
        id=pet.id,
        name=pet.name,
        level=pet.level,
        exp=pet.exp,
        max_exp=pet.max_exp,
        hp=pet.hp,
        hp_max=C.HP_MAX,
        is_dead=pet.is_dead,
        status=snapshot.pet_status,
        phrase=phrase,
        evolution=snapshot.pet_species,
        evolution_stage=snapshot.pet_stage,
        evolution_next_level=next_evo_level,
        last_event=clean_event,
        last_backup_date=pet.last_backup_date,
        last_interaction_date=pet.last_interaction_date,
        last_updated=pet.last_updated,
        backup_cooldown_remaining_seconds=backup_remaining,
        focus_cooldown_remaining_seconds=focus_remaining,
        days_since_backup=snapshot.days_since_backup,
        dust_count=pet.dust_count,
        current_mood=pet.current_mood,
    )


@router.get("/pet", response_model=PetResponse)
async def get_pet_state(
    db: aiosqlite.Connection = Depends(get_db),
    phrase_selector=Depends(get_phrase_selector),
    pet_service: PetService = Depends(get_pet_service),
):
    return await _build_pet_response(db, phrase_selector, pet_service)


@router.post("/pet/interact", response_model=PetInteractResponse)
async def interact(
    db: aiosqlite.Connection = Depends(get_db),
    pet_service: PetService = Depends(get_pet_service),
    phrase_selector=Depends(get_phrase_selector),
):
    pet, on_cooldown = await pet_service.interact(db)
    snapshot = await context_service.build_snapshot(db)
    ctx = {"__context__": snapshot, "species": snapshot.pet_species}
    if pet.is_dead:
        phrase = await phrase_selector.select(PhraseContext.DEATH, ctx)
    elif on_cooldown:
        phrase = await phrase_selector.select(PhraseContext.INTERACT_COOLDOWN, ctx)
    else:
        phrase = await phrase_selector.select(PhraseContext.INTERACT, ctx)
    return PetInteractResponse(exp=pet.exp, phrase=phrase, on_cooldown=on_cooldown)


@router.post("/pet/backup", response_model=PetBackupResponse)
async def backup(
    db: aiosqlite.Connection = Depends(get_db),
    pet_service: PetService = Depends(get_pet_service),
    phrase_selector=Depends(get_phrase_selector),
):
    pet, on_cooldown = await pet_service.backup(db)
    snapshot = await context_service.build_snapshot(db)
    ctx = {"__context__": snapshot, "species": snapshot.pet_species}
    if pet.is_dead:
        phrase = await phrase_selector.select(PhraseContext.DEATH, ctx)
    elif on_cooldown:
        phrase = await phrase_selector.select(PhraseContext.BACKUP_COOLDOWN, ctx)
    else:
        phrase = await phrase_selector.select(PhraseContext.BACKUP, ctx)
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
    pet_service: PetService = Depends(get_pet_service),
    phrase_selector=Depends(get_phrase_selector),
):
    """Revive the dead pet. Resets HP to HP_REVIVE and clears EXP. No-op if alive."""
    await pet_service.revive(db)
    return await _build_pet_response(db, phrase_selector, pet_service)


@router.patch("/pet/rename", response_model=PetResponse)
async def rename_pet(
    body: PetRenameRequest,
    db: aiosqlite.Connection = Depends(get_db),
    pet_service: PetService = Depends(get_pet_service),
    phrase_selector=Depends(get_phrase_selector),
):
    """Set a custom display name for the pet (resets on next evolution)."""
    await pet_service.rename(db, body.name)
    return await _build_pet_response(db, phrase_selector, pet_service)


@router.post("/pet/clean", response_model=PetCleanResponse)
async def clean(
    db: aiosqlite.Connection = Depends(get_db),
    pet_service: PetService = Depends(get_pet_service),
    phrase_selector=Depends(get_phrase_selector),
):
    """Clean the pet's dust. Grants EXP on success."""
    pet, success = await pet_service.clean(db)
    snapshot = await context_service.build_snapshot(db)
    ctx = {"__context__": snapshot, "species": snapshot.pet_species}
    if pet.is_dead:
        phrase = await phrase_selector.select(PhraseContext.DEATH, ctx)
    elif not success:
        phrase = "No dust to clean."
    else:
        phrase = await phrase_selector.select(PhraseContext.INTERACT, ctx)
    return PetCleanResponse(
        exp=pet.exp,
        phrase=phrase,
        success=success,
        dust_count=pet.dust_count,
    )


@router.post("/pet/focus_reward", response_model=PetFocusResponse)
async def focus_reward(
    db: aiosqlite.Connection = Depends(get_db),
    pet_service: PetService = Depends(get_pet_service),
    phrase_selector=Depends(get_phrase_selector),
):
    """Complete a focus session. Grants EXP and HP (30-minute cooldown)."""
    pet, on_cooldown = await pet_service.focus_reward(db)
    snapshot = await context_service.build_snapshot(db)
    ctx = {"__context__": snapshot, "species": snapshot.pet_species}
    if pet.is_dead:
        phrase = await phrase_selector.select(PhraseContext.DEATH, ctx)
    elif on_cooldown:
        phrase = await phrase_selector.select(PhraseContext.BACKUP_COOLDOWN, ctx)
    else:
        phrase = await phrase_selector.select(PhraseContext.BACKUP, ctx)
    return PetFocusResponse(
        exp=pet.exp,
        hp=pet.hp,
        phrase=phrase,
        on_cooldown=on_cooldown,
    )
