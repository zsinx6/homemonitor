"""Pet chat endpoint — LLM-powered conversation with the Digimon."""
from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, Depends

from app.api.dependencies import get_db, get_llm_chat_service
from app.api.models import ChatRequest, ChatResponse
from app.services import context_service

router = APIRouter()


@router.post("/pet/chat", response_model=ChatResponse)
async def pet_chat(
    body: ChatRequest,
    db: aiosqlite.Connection = Depends(get_db),
    llm_service=Depends(get_llm_chat_service),
):
    """Send a message to the Digimon and receive an LLM-generated reply.

    The full system snapshot (pet stats, server health, tasks, backup status)
    is injected as context so the Digimon can answer infra questions and
    proactively suggest improvements.
    """
    snapshot = await context_service.build_snapshot(db)
    response = await llm_service.chat(body.message, snapshot)
    return ChatResponse(response=response)
