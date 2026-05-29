"""Pure domain logic — no Discord, no IO. Fully unit-testable."""

from __future__ import annotations

from datetime import datetime, timedelta

from meetup import canonical_event_url
from models import Event, EventStatus


def is_duplicate(meetup_link: str, events: list[Event]) -> bool:
    """True if any existing event has the same canonical Meetup URL."""
    key = canonical_event_url(meetup_link)
    return any(canonical_event_url(e.meetup_link) == key for e in events)


def is_in_past(start: datetime, now: datetime) -> bool:
    """True if the event's date is before today (same-day is allowed)."""
    return start.date() < now.date()


def compute_event_end(
    start: datetime, scraped_end: datetime | None, default_hours: int
) -> tuple[datetime, bool]:
    """Return (end, estimated). Use the scraped end when sane, else start + default."""
    if scraped_end and scraped_end > start:
        return scraped_end, False
    return start + timedelta(hours=default_hours), True


def effective_end(event: Event, default_hours: int) -> datetime:
    """The event's end time, falling back to start + default when unknown."""
    if event.event_end:
        return event.event_end
    return event.event_datetime + timedelta(hours=default_hours)


def events_due_for_followup(
    events: list[Event], now: datetime, default_hours: int
) -> list[Event]:
    """Pending events whose (effective) end time has passed."""
    return [
        e
        for e in events
        if e.status == EventStatus.PENDING and now >= effective_end(e, default_hours)
    ]


def known_event_keys(events: list[Event]) -> set[str]:
    """Canonical de-dup keys for every known event."""
    return {canonical_event_url(e.meetup_link) for e in events}


def select_new_event_urls(fetched_urls: list[str], known_keys: set[str]) -> list[str]:
    """Fetched URLs whose canonical key isn't already known (de-duped, order kept)."""
    new: list[str] = []
    seen: set[str] = set()
    for url in fetched_urls:
        key = canonical_event_url(url)
        if key in known_keys or key in seen:
            continue
        seen.add(key)
        new.append(url)
    return new
