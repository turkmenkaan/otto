"""Typed domain models for events and watched groups."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class EventStatus(str, Enum):
    PENDING = "pending"
    AWAITING_FEEDBACK = "awaiting_feedback"
    COMPLETED = "completed"
    UNCLAIMED = "unclaimed"  # auto-discovered event that ended without a claimer


class EventSource(str, Enum):
    MANUAL = "manual"
    AUTO = "auto"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Event:
    id: str
    event_name: str
    meetup_link: str
    event_datetime: datetime  # start time, tz-aware UTC
    guild_id: int
    event_end: datetime | None = None
    status: EventStatus = EventStatus.PENDING
    source: EventSource = EventSource.MANUAL
    submitter_id: int | None = None
    group: str | None = None
    submitted_at: datetime = field(default_factory=_now_utc)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "event_name": self.event_name,
            "meetup_link": self.meetup_link,
            "event_datetime": self.event_datetime.isoformat(),
            "event_end": self.event_end.isoformat() if self.event_end else None,
            "guild_id": self.guild_id,
            "status": self.status.value,
            "source": self.source.value,
            "submitter_id": self.submitter_id,
            "group": self.group,
            "submitted_at": self.submitted_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        # Defaults keep older rows (pre event_end/source/group) loadable.
        end_raw = d.get("event_end")
        submitted_raw = d.get("submitted_at")
        return cls(
            id=d["id"],
            event_name=d["event_name"],
            meetup_link=d["meetup_link"],
            event_datetime=datetime.fromisoformat(d["event_datetime"]),
            guild_id=d["guild_id"],
            event_end=datetime.fromisoformat(end_raw) if end_raw else None,
            status=EventStatus(d.get("status", "pending")),
            source=EventSource(d.get("source", "manual")),
            submitter_id=d.get("submitter_id"),
            group=d.get("group"),
            submitted_at=(
                datetime.fromisoformat(submitted_raw) if submitted_raw else _now_utc()
            ),
        )


@dataclass
class Group:
    slug: str
    url: str
    guild_id: int
    channel_id: int
    added_by: int
    added_at: datetime = field(default_factory=_now_utc)
    seeded: bool = False

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "url": self.url,
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
            "added_by": self.added_by,
            "added_at": self.added_at.isoformat(),
            "seeded": self.seeded,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Group":
        added_raw = d.get("added_at")
        return cls(
            slug=d["slug"],
            url=d["url"],
            guild_id=d["guild_id"],
            channel_id=d["channel_id"],
            added_by=d["added_by"],
            added_at=datetime.fromisoformat(added_raw) if added_raw else _now_utc(),
            seeded=d.get("seeded", False),
        )
