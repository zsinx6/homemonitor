"""Abstract LLM interface — v2 seam.

In v1 this is unused directly; StaticPhraseService is the concrete impl.
In v2, a CloudLLMService subclass can be swapped in via config.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMInterface(ABC):
    """Cloud LLM gateway interface for Digimon dialogue generation."""

    @abstractmethod
    async def generate_phrase(self, context: str, variables: dict[str, Any]) -> str:
        """Generate a Digimon-style phrase for the given context."""
