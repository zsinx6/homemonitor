"""FastAPI dependency injection: DB connection, services, phrase selector."""
from __future__ import annotations

import logging
import os
from typing import AsyncGenerator, Optional

import aiosqlite
from fastapi import Request

from app.domain.phrases import PhraseSelector
from app.domain.static_phrase_service import StaticPhraseService
from app.infrastructure.adapters import MemoryRepoAdapter, PetRepoAdapter, ServerRepoAdapter, TaskRepoAdapter
from app.services.monitor_service import MonitorService
from app.services.pet_service import PetService
from app.services.task_service import TaskService

logger = logging.getLogger(__name__)

# Module-level singletons — lazily initialised on first request
_phrase_selector: Optional[PhraseSelector] = None
_llm_chat_service = None


async def get_db(request: Request) -> AsyncGenerator[aiosqlite.Connection, None]:
    db_path = request.app.state.db_path
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        yield db


def get_phrase_selector() -> PhraseSelector:
    global _phrase_selector
    if _phrase_selector is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                from app.services.llm_service import GeminiPhraseService  # noqa: PLC0415
                _phrase_selector = GeminiPhraseService(api_key)
                logger.info("Gemini phrase service enabled (gemini-1.5-flash).")
            except Exception as exc:
                logger.warning("Could not init GeminiPhraseService (%s); using static.", exc)
                _phrase_selector = StaticPhraseService()
        else:
            _phrase_selector = StaticPhraseService()
    return _phrase_selector


def get_llm_chat_service():
    global _llm_chat_service
    if _llm_chat_service is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                from app.services.llm_service import LLMChatService  # noqa: PLC0415
                _llm_chat_service = LLMChatService(api_key)
                logger.info("Gemini chat service enabled.")
            except Exception as exc:
                logger.warning("Could not init LLMChatService (%s); chat disabled.", exc)
                from app.services.llm_service import NoopChatService  # noqa: PLC0415
                _llm_chat_service = NoopChatService()
        else:
            from app.services.llm_service import NoopChatService  # noqa: PLC0415
            _llm_chat_service = NoopChatService()
    return _llm_chat_service


def get_pet_service() -> PetService:
    return PetService(pet_repo=PetRepoAdapter(), memory_repo=MemoryRepoAdapter())


def get_task_service() -> TaskService:
    return TaskService(pet_repo=PetRepoAdapter(), task_repo=TaskRepoAdapter(), memory_repo=MemoryRepoAdapter())

