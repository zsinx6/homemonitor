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
    DUST_CLEANED = "dust_cleaned"
    FOCUS_COMPLETE = "focus_complete"
    SSL_EXPIRY_WARNING = "ssl_expiry_warning"
    PUBLIC_IP_CHANGED = "public_ip_changed"

    # Human-readable labels and icons for the UI
    LABELS: dict[str, tuple[str, str]] = {
        SERVER_DOWN:        ("DN", "went DOWN"),
        SERVER_RECOVERY:    ("UP", "came back UP"),
        TASK_COMPLETE:      ("OK", "Task completed"),
        BACKUP:             ("BK", "Backup ran"),
        LEVEL_UP:           ("LV", "Level up"),
        DIGIVOLUTION:       ("EV", "Digivolved"),
        DEATH:              ("XX", "Fell in battle"),
        REVIVAL:            ("RV", "Was revived"),
        RENAME:             ("RN", "Renamed to"),
        MAINTENANCE_ON:     ("MN", "Maintenance ON"),
        MAINTENANCE_OFF:    ("MN", "Maintenance OFF"),
        DUST_CLEANED:       ("CL", "Cleaned up dust"),
        FOCUS_COMPLETE:     ("FO", "Completed focus session"),
        SSL_EXPIRY_WARNING: ("SL", "SSL cert expiring"),
        PUBLIC_IP_CHANGED:  ("IP", "Public IP changed"),
    }


@dataclass(frozen=True)
class Memory:
    id: int
    event_type: str
    detail: Optional[str]
    occurred_at: datetime
