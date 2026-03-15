"""ntfy.sh push notification client.

Sends fire-and-forget HTTP notifications to a ntfy.sh topic (or self-hosted
ntfy server).  All failures are logged and swallowed — notifications are
best-effort and must never block the monitor cycle.

Usage::

    notifier = NtfyNotifier("https://ntfy.sh/my-homelab-alerts")
    await notifier.notify("Server DOWN", "nginx is not responding", priority="high", tags=["warning"])
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ntfy priority values (https://docs.ntfy.sh/publish/#message-priority)
PRIORITY_MAX     = "max"       # really urgent — 5
PRIORITY_HIGH    = "high"      # 4
PRIORITY_DEFAULT = "default"   # 3
PRIORITY_LOW     = "low"       # 2
PRIORITY_MIN     = "min"       # 1


class NtfyNotifier:
    """Async ntfy.sh notification sender."""

    def __init__(self, topic_url: str) -> None:
        # topic_url can be a full URL like "https://ntfy.sh/my-topic"
        # or just a topic name (we prefix ntfy.sh automatically)
        if topic_url.startswith("http"):
            self._url = topic_url.rstrip("/")
        else:
            self._url = f"https://ntfy.sh/{topic_url}"

    async def notify(
        self,
        title: str,
        message: str,
        priority: str = PRIORITY_DEFAULT,
        tags: Optional[list[str]] = None,
    ) -> None:
        """POST a notification to the ntfy topic. Never raises."""
        headers: dict[str, str] = {
            "Title": title,
            "Priority": priority,
        }
        if tags:
            headers["Tags"] = ",".join(tags)

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(self._url, content=message.encode(), headers=headers)
                resp.raise_for_status()
        except Exception as exc:
            logger.warning("ntfy notification failed (%s): %s", self._url, exc)


def build_notifier(topic_url: Optional[str]) -> Optional[NtfyNotifier]:
    """Return a NtfyNotifier if a topic URL is configured, else None."""
    if topic_url:
        return NtfyNotifier(topic_url)
    return None
