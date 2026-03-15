"""Pet API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends

import aiosqlite

from app.api.dependencies import get_db, get_pet_service, get_phrase_selector
from app.api.models import PetBackupResponse, PetInteractResponse, PetResponse
from app.domain import constants as C
from app.domain.pet import derive_status
from app.domain.phrases import PhraseContext
from app.infrastructure.repositories import pet_repo, server_repo

router = APIRouter()


async def _build_pet_response(db, phrase_selector) -> PetResponse:
    pet = await pet_repo.get_pet(db)
    servers = await server_repo.list_servers(db)
    any_down = any(s.status == "DOWN" for s in servers)
    status = derive_status(pet, any_server_down=any_down)

    # Select context-aware phrase
    ctx_map = {
        "happy": PhraseContext.HAPPY,
        "lonely": PhraseContext.LONELY,
        "sad": PhraseContext.SAD,
        "injured": PhraseContext.INJURED,
        "critical": PhraseContext.CRITICAL,
    }
    # Prioritise event-based phrase over status phrase
    if pet.last_event == "server_down":
        down_names = [s.name for s in servers if s.status == "DOWN"]
        server_name = down_names[0] if down_names else "unknown"
        phrase = await phrase_selector.select(
            PhraseContext.SERVER_DOWN, {"server_name": server_name}
        )
    elif pet.last_event == "level_up":
        phrase = await phrase_selector.select(
            PhraseContext.LEVEL_UP, {"level": pet.level}
        )
    elif pet.last_event == "recovery":
        phrase = await phrase_selector.select(
            PhraseContext.RECOVERY, {"server_name": "server"}
        )
    elif pet.last_event == "backup":
        phrase = await phrase_selector.select(PhraseContext.BACKUP, {})
    else:
        phrase = await phrase_selector.select(ctx_map.get(status, PhraseContext.HAPPY), {})

    last_event = pet.last_event
    # Clear last_event after delivering it (one-shot)
    if last_event:
        await pet_repo.clear_last_event(db)

    return PetResponse(
        id=pet.id,
        name=pet.name,
        level=pet.level,
        exp=pet.exp,
        max_exp=pet.max_exp,
        hp=pet.hp,
        hp_max=C.HP_MAX,
        status=status,
        phrase=phrase,
        last_event=last_event,
        last_backup_date=pet.last_backup_date,
        last_updated=pet.last_updated,
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
    pet = await pet_service.interact(db)
    phrase = await phrase_selector.select(PhraseContext.INTERACT, {})
    return PetInteractResponse(exp=pet.exp, phrase=phrase)


@router.post("/pet/backup", response_model=PetBackupResponse)
async def backup(
    db: aiosqlite.Connection = Depends(get_db),
    pet_service=Depends(get_pet_service),
    phrase_selector=Depends(get_phrase_selector),
):
    pet = await pet_service.backup(db)
    phrase = await phrase_selector.select(PhraseContext.BACKUP, {})
    return PetBackupResponse(
        exp=pet.exp,
        hp=pet.hp,
        phrase=phrase,
        last_backup_date=pet.last_backup_date,
    )
