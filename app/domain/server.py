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
    previous_statuses: dict[str, str],
    current_statuses: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Compare two status snapshots and return (newly_down, newly_recovered).

    Only servers that existed in the previous snapshot can have transitions.
    A brand-new server appearing as DOWN is not considered a transition.
    """
    newly_down: list[str] = []
    newly_recovered: list[str] = []

    for name, prev_status in previous_statuses.items():
        curr_status = current_statuses.get(name)
        if curr_status is None:
            continue
        if prev_status == "UP" and curr_status == "DOWN":
            newly_down.append(name)
        elif prev_status == "DOWN" and curr_status == "UP":
            newly_recovered.append(name)

    return newly_down, newly_recovered
