"""Checker registry: maps server type strings to checker instances.

Register checkers at startup with ``register()``, then look them up in the
monitoring loop with ``get_checker()``.  Unknown types fall back to the HTTP
checker so the app degrades gracefully rather than crashing.
"""
from __future__ import annotations

from app.infrastructure.checkers.base import ServerChecker

_REGISTRY: dict[str, ServerChecker] = {}


def register(name: str, checker: ServerChecker) -> None:
    """Register a checker under the given type name (e.g. "http", "tcp")."""
    _REGISTRY[name] = checker


def get_checker(name: str) -> ServerChecker | None:
    """Return the checker for *name*, or the http checker as a fallback."""
    return _REGISTRY.get(name) or _REGISTRY.get("http")


def registered_types() -> list[str]:
    """Return sorted list of all registered type names."""
    return sorted(_REGISTRY.keys())
