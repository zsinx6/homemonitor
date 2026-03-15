"""Shared utilities for the repository layer."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def parse_datetime(val: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-format datetime string into a UTC-aware datetime, or None."""
    if val is None:
        return None
    return datetime.fromisoformat(val).replace(tzinfo=timezone.utc)
