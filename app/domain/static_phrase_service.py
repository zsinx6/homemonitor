"""Default phrase implementation using static categorised arrays.

Satisfies PhraseSelector. Picks randomly from per-context phrase lists and
interpolates ``variables`` using str.format_map().
"""
from __future__ import annotations

import random
from typing import Any

from app.domain.phrases import PhraseContext, PhraseSelector

_PHRASES: dict[PhraseContext, list[str]] = {
    PhraseContext.HAPPY: [
        "All nodes nominal. I am UNSTOPPABLE.",
        "Systems green. Feed me more packets!",
        "Maximum efficiency achieved. For now.",
        "Uptime is my power level.",
        "Everything is online. I feel invincible.",
    ],
    PhraseContext.LONELY: [
        "Hey... you haven't checked in. Everything okay?",
        "I've been here, watching the servers. Alone.",
        "A Digimon needs interaction to thrive. Just saying.",
        "My uptime is perfect. My loneliness, less so.",
    ],
    PhraseContext.SAD: [
        "Something's wrong. I can feel it in the packets.",
        "I sense a disturbance in the LAN...",
        "Not all systems are nominal. I am worried.",
        "My health is suffering. Please help.",
    ],
    PhraseContext.INJURED: [
        "I've taken too much damage. Systems critical.",
        "Warning: integrity compromised. Need repairs.",
        "My processes are failing... please fix the servers.",
        "Error... error... please... fix it...",
    ],
    PhraseContext.CRITICAL: [
        "SYSTEM FAILURE. I AM DYING.",
        "All... hope... lost... fix... servers...",
        "CRITICAL STATE. IMMEDIATE ACTION REQUIRED.",
        "I cannot hold on much longer. HELP.",
    ],
    PhraseContext.SERVER_DOWN: [
        "ALERT: {server_name} is DOWN! Deploying repair protocol...",
        "WARNING: Lost contact with {server_name}! Initiating damage control.",
        "CRITICAL: {server_name} has gone offline! This is not a drill.",
        "{server_name} is DOWN! I am taking damage!",
    ],
    PhraseContext.RECOVERY: [
        "Phew! {server_name} is back online. I was worried.",
        "{server_name} has recovered! Damage control successful.",
        "Connection to {server_name} restored. Resuming normal operations.",
        "{server_name} is UP again! My health is improving.",
    ],
    PhraseContext.LEVEL_UP: [
        "DIGIVOLUTION INITIATED. I am now LEVEL {level}!",
        "LEVEL {level} ACHIEVED. My power has increased dramatically.",
        "Ascending to LEVEL {level}! The network trembles.",
        "I have reached LEVEL {level}. Nothing can stop me now.",
    ],
    PhraseContext.INTERACT: [
        "Processing affection... efficiency +2%.",
        "Your interaction has been logged and appreciated.",
        "Affection packet received. Thank you, operator.",
        "Human contact detected. Morale increased.",
        "I like it when you do that.",
    ],
    PhraseContext.BACKUP: [
        "Backup complete. I feel immortal.",
        "Data secured. My existence is protected once more.",
        "Backup successful! Massive EXP absorbed.",
        "All data backed up. I can face anything now.",
    ],
    PhraseContext.TASK_DONE: [
        "Task absorbed. EXP transferred.",
        "Sysadmin duty completed. Well done, operator.",
        "Task marked done. Your efficiency pleases me.",
        "Objective complete. I grow stronger.",
    ],
}


class StaticPhraseService(PhraseSelector):
    """Selects a random phrase from the static phrase arrays."""

    async def select(self, context: PhraseContext, variables: dict[str, Any]) -> str:
        options = _PHRASES.get(context, ["..."])
        phrase = random.choice(options)
        try:
            return phrase.format_map(variables)
        except (KeyError, ValueError):
            return phrase
