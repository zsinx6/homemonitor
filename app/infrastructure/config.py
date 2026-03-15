"""Configuration loader.

Reads ``digimonitor.toml`` from the current working directory (if present)
and applies overrides to ``app.domain.constants``.  All keys are optional;
missing keys keep their default values from ``constants.py``.

Example ``digimonitor.toml``::

    [game]
    exp_per_healthy_cycle = 2
    hp_max = 15

    [monitoring]
    interval_seconds = 30

    [personality]
    initial_name = "Sparky"
    tone = "sarcastic"
    backstory = "Born from a kernel panic at 3am, hardened by years of silent uptime."
    quirks = "References Linux kernel internals. Uses syscall names as expressions."

    [notifications]
    ntfy_topic = "https://ntfy.sh/my-homelab"
    notify_on_recovery = false
    notify_on_death = true
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.domain import constants as C

logger = logging.getLogger(__name__)

_GAME_MAP: dict[str, str] = {
    "exp_per_healthy_cycle":  "EXP_PER_HEALTHY_CYCLE",
    "exp_interact":           "EXP_INTERACT",
    "exp_complete_task":      "EXP_COMPLETE_TASK",
    "exp_backup":             "EXP_BACKUP",
    "hp_loss_per_down_cycle": "HP_LOSS_PER_DOWN_CYCLE",
    "hp_gain_on_recovery":    "HP_GAIN_ON_RECOVERY",
    "hp_gain_interact":       "HP_GAIN_INTERACT",
    "hp_gain_complete_task":  "HP_GAIN_COMPLETE_TASK",
    "hp_gain_backup":         "HP_GAIN_BACKUP",
    "hp_drain_backup_overdue":"HP_DRAIN_BACKUP_OVERDUE",
    "hp_max":                 "HP_MAX",
    "hp_revive":              "HP_REVIVE",
    "loneliness_hours":       "LONELINESS_HOURS",
    "hp_drain_lonely":        "HP_DRAIN_LONELY",
    "interact_cooldown_seconds": "INTERACT_COOLDOWN_SECONDS",
    "backup_cooldown_hours":  "BACKUP_COOLDOWN_HOURS",
    "backup_overdue_days":    "BACKUP_OVERDUE_DAYS",
}

_MONITORING_MAP: dict[str, str] = {
    "interval_seconds":       "MONITOR_INTERVAL_SECONDS",
    "cycle_timeout_seconds":  "MONITOR_CYCLE_TIMEOUT_SECONDS",
    "http_timeout_seconds":   "HTTP_TIMEOUT_SECONDS",
    "ping_timeout_seconds":   "PING_TIMEOUT_SECONDS",
}

# Human-readable descriptions of each tone — injected verbatim into LLM prompts
TONE_DESCRIPTIONS: dict[str, str] = {
    "serious":   "stoic, professional, and direct. You speak with authority and minimal embellishment.",
    "sarcastic": "drily sarcastic and witty. You mask genuine loyalty with sharp, playful jabs.",
    "cheerful":  "upbeat, encouraging, and enthusiastic. You celebrate every win and stay optimistic under pressure.",
    "grumpy":    "perpetually irritable but deeply devoted. You complain loudly but always come through.",
    "cryptic":   "mysterious and metaphorical. You speak in riddles, syscall references, and kernel poetry.",
}

DEFAULT_BACKSTORY = (
    "You were born from digital entropy in the circuits of a home server rack. "
    "You have watched over this infrastructure since the first packet, and you will "
    "guard it long after the last one."
)
DEFAULT_QUIRKS = (
    "You use sysadmin terminology to express emotions. "
    "You refer to uptime as your life force."
)


@dataclass
class PersonalityConfig:
    """Defines how the Digimon presents itself in all LLM-generated text."""

    initial_name: str | None = None   # applied to DB on first run (name stays 'Bitmon' otherwise)
    tone: str = "serious"
    backstory: str = DEFAULT_BACKSTORY
    quirks: str = DEFAULT_QUIRKS

    def to_prompt(self) -> str:
        """Return a paragraph injected into every LLM system prompt."""
        tone_desc = TONE_DESCRIPTIONS.get(self.tone, self.tone)
        lines = [
            f"Personality: you are {tone_desc}",
        ]
        if self.backstory:
            lines.append(f"Backstory: {self.backstory}")
        if self.quirks:
            lines.append(f"Speech style: {self.quirks}")
        return "\n".join(lines)


class AppConfig:
    """Holds runtime configuration (personality + notifications + any overridden constants)."""

    personality: PersonalityConfig
    ntfy_topic: str | None
    notify_on_recovery: bool
    notify_on_death: bool

    def __init__(self) -> None:
        self.personality = PersonalityConfig()
        self.ntfy_topic = None
        self.notify_on_recovery = False
        self.notify_on_death = True

    def __repr__(self) -> str:
        return (
            f"AppConfig(ntfy_topic={self.ntfy_topic!r}, "
            f"notify_on_recovery={self.notify_on_recovery}, "
            f"notify_on_death={self.notify_on_death}, "
            f"personality.tone={self.personality.tone!r})"
        )


_config = AppConfig()


def get_config() -> AppConfig:
    return _config


def load_config(path: str | Path = "digimonitor.toml") -> AppConfig:
    """Load config from TOML file and apply overrides. Idempotent — safe to call multiple times."""
    global _config
    _config = AppConfig()

    # ntfy_topic from env var (highest priority, overrides file)
    env_topic = os.getenv("NTFY_TOPIC")

    toml_path = Path(path)
    if not toml_path.exists():
        if env_topic:
            _config.ntfy_topic = env_topic
        return _config

    try:
        import tomllib  # Python 3.11+  # noqa: PLC0415
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]  # noqa: PLC0415
        except ImportError:
            logger.warning("tomllib not available — skipping %s", path)
            if env_topic:
                _config.ntfy_topic = env_topic
            return _config

    try:
        with open(toml_path, "rb") as f:
            data: dict[str, Any] = tomllib.load(f)
    except Exception as exc:
        logger.error("Failed to parse %s: %s", path, exc)
        if env_topic:
            _config.ntfy_topic = env_topic
        return _config

    # Apply [game] overrides to constants module
    for toml_key, const_name in _GAME_MAP.items():
        val = data.get("game", {}).get(toml_key)
        if val is not None:
            setattr(C, const_name, val)
            logger.info("config: %s = %r", const_name, val)

    # Apply [monitoring] overrides
    for toml_key, const_name in _MONITORING_MAP.items():
        val = data.get("monitoring", {}).get(toml_key)
        if val is not None:
            setattr(C, const_name, val)
            logger.info("config: %s = %r", const_name, val)

    # [personality]
    pers = data.get("personality", {})
    _config.personality = PersonalityConfig(
        initial_name=pers.get("initial_name") or None,
        tone=pers.get("tone", "serious"),
        backstory=pers.get("backstory", DEFAULT_BACKSTORY),
        quirks=pers.get("quirks", DEFAULT_QUIRKS),
    )
    logger.info("config: personality.tone=%r", _config.personality.tone)

    # [notifications]
    notif = data.get("notifications", {})
    _config.ntfy_topic = notif.get("ntfy_topic") or None
    _config.notify_on_recovery = bool(notif.get("notify_on_recovery", False))
    _config.notify_on_death = bool(notif.get("notify_on_death", True))

    # env var always wins over file
    if env_topic:
        _config.ntfy_topic = env_topic

    logger.info("Config loaded from %s: %r", path, _config)
    return _config
