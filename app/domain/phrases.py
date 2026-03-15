"""Phrase contexts and the abstract PhraseSelector interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any


class PhraseContext(str, Enum):
    HAPPY = "happy"
    LONELY = "lonely"
    SAD = "sad"
    INJURED = "injured"
    CRITICAL = "critical"
    SERVER_DOWN = "server_down"
    RECOVERY = "recovery"
    LEVEL_UP = "level_up"
    INTERACT = "interact"
    BACKUP = "backup"
    TASK_DONE = "task_done"


class PhraseSelector(ABC):
    """Abstract interface for phrase generation.

    v1 is implemented by StaticPhraseService (phrase arrays).
    v2 can be a CloudLLMService — same interface, no other changes needed.
    """

    @abstractmethod
    async def select(self, context: PhraseContext, variables: dict[str, Any]) -> str:
        """Return a phrase appropriate for the given context.

        ``variables`` contains interpolation data, e.g. {"server_name": "nginx"}.
        """
