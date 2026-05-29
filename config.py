"""Centralized configuration loaded once from the environment."""

import os
from dataclasses import dataclass

# Brand name — a true constant, surfaced in user-facing copy.
BOT_NAME = "Otto"


@dataclass(frozen=True)
class Settings:
    token: str
    log_channel_id: int
    check_interval_minutes: int = 30
    group_poll_interval_minutes: int = 60
    default_event_duration_hours: int = 3


def load_settings() -> Settings:
    """Build Settings from environment variables (call after load_dotenv())."""
    return Settings(
        token=os.getenv("DISCORD_TOKEN", ""),
        log_channel_id=int(os.getenv("LOG_CHANNEL_ID", "0")),
        check_interval_minutes=int(os.getenv("CHECK_INTERVAL_MINUTES", "30")),
        group_poll_interval_minutes=int(os.getenv("GROUP_POLL_INTERVAL_MINUTES", "60")),
        default_event_duration_hours=int(os.getenv("DEFAULT_EVENT_DURATION_HOURS", "3")),
    )
