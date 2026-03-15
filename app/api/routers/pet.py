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
    any_down = any(s.status == "DOWN" for s in servers)
    status = derive_status(pet, any_server_down=any_down)

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
            PhraseContext.LEVEL_UP, {"level": pet.level}
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
        status=status,
        phrase=phrase,
        last_event=clean_event,
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
