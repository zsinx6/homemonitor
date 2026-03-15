"""Server domain entity and pure business logic."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ServerCheckResult:
    server_id: int
    name: str
    is_up: bool
    error: Optional[str]


def compute_uptime_percent(total: int, successful: int) -> float:
    """Calculate uptime percentage, safe against division by zero."""
    if total == 0:
        return 0.0
    return round(successful / total * 100, 2)


def detect_state_transitions(
    previous_statuses: dict,
    current_statuses: dict,
) -> tuple[list, list]:
    """Compare two status snapshots and return (newly_down, newly_recovered).

    Keys can be any hashable (server name or server ID). Only servers that
    existed in the previous snapshot can have transitions. A brand-new server
    appearing as DOWN is not considered a transition.
    """
    newly_down: list = []
    newly_recovered: list = []

    for key, prev_status in previous_statuses.items():
        curr_status = current_statuses.get(key)
        if curr_status is None:
            continue
        if prev_status == "UP" and curr_status == "DOWN":
            newly_down.append(key)
        elif prev_status == "DOWN" and curr_status == "UP":
            newly_recovered.append(key)

    return newly_down, newly_recovered
