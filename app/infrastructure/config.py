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

    [notifications]
    ntfy_topic = "https://ntfy.sh/my-homelab"
    notify_on_recovery = false
    notify_on_death = true
"""
from __future__ import annotations

import logging
import os
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


class AppConfig:
    """Holds runtime configuration (notifications + any overridden constants)."""

    ntfy_topic: str | None = None
    notify_on_recovery: bool = False
    notify_on_death: bool = True

    def __repr__(self) -> str:
        return (
            f"AppConfig(ntfy_topic={self.ntfy_topic!r}, "
            f"notify_on_recovery={self.notify_on_recovery}, "
            f"notify_on_death={self.notify_on_death})"
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
