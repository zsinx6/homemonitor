"""Memory domain entity.

A Memory records a significant event in the pet's life — server failures,
task completions, backups, evolutions, death and revival.  The history is
stored in the database and fed to the LLM so the Digimon can remember what
has happened to its infrastructure.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


class MemoryType:
    SERVER_DOWN = "server_down"
    SERVER_RECOVERY = "server_recovery"
    TASK_COMPLETE = "task_complete"
    BACKUP = "backup"
    LEVEL_UP = "level_up"
    DIGIVOLUTION = "digivolution"
    DEATH = "death"
    REVIVAL = "revival"
    RENAME = "rename"
    MAINTENANCE_ON = "maintenance_on"
    MAINTENANCE_OFF = "maintenance_off"

    # Human-readable labels and icons for the UI
    LABELS: dict[str, tuple[str, str]] = {
        SERVER_DOWN:      ("🔴", "went DOWN"),
        SERVER_RECOVERY:  ("🟢", "came back UP"),
        TASK_COMPLETE:    ("✅", "Task completed"),
        BACKUP:           ("💾", "Backup ran"),
        LEVEL_UP:         ("⬆️", "Level up"),
        DIGIVOLUTION:     ("✨", "Digivolved"),
        DEATH:            ("💀", "Fell in battle"),
        REVIVAL:          ("💫", "Was revived"),
        RENAME:           ("✎", "Renamed to"),
        MAINTENANCE_ON:   ("🔧", "Maintenance ON"),
        MAINTENANCE_OFF:  ("🔧", "Maintenance OFF"),
    }


@dataclass(frozen=True)
class Memory:
    id: int
    event_type: str
    detail: Optional[str]
    occurred_at: datetime
