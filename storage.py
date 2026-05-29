"""JSON persistence for events and groups. Reads sync; writes async, locked, atomic."""

import asyncio
import json
import os

from models import Event, EventStatus, Group

DATA_DIR = os.getenv("DATA_DIR", "data")
EVENTS_FILE = os.path.join(DATA_DIR, "events.json")
GROUPS_FILE = os.path.join(DATA_DIR, "groups.json")

# Serializes read-modify-write cycles so the poll loop and interaction handlers
# can't clobber each other's writes within the single event loop.
_write_lock = asyncio.Lock()


def _read_raw(path: str, key: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, "r") as f:
        return json.load(f).get(key, [])


def _atomic_write(path: str, key: str, rows: list[dict]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump({key: rows}, f, indent=2)
    os.replace(tmp, path)  # atomic on POSIX


# --- events: reads (sync) ---------------------------------------------------

def load_events() -> list[Event]:
    return [Event.from_dict(d) for d in _read_raw(EVENTS_FILE, "events")]


def get_event(event_id: str) -> Event | None:
    for event in load_events():
        if event.id == event_id:
            return event
    return None


def get_events_by_status(status: EventStatus | str) -> list[Event]:
    value = status.value if isinstance(status, EventStatus) else status
    return [e for e in load_events() if e.status.value == value]


# --- events: writes (async, locked, atomic) ---------------------------------

async def add_event(event: Event) -> None:
    async with _write_lock:
        rows = _read_raw(EVENTS_FILE, "events")
        rows.append(event.to_dict())
        _atomic_write(EVENTS_FILE, "events", rows)


async def update_event(event_id: str, **changes) -> None:
    """Apply field changes to one event. Enum values are stored as their .value."""
    normalized = {
        k: (v.value if isinstance(v, EventStatus) else v) for k, v in changes.items()
    }
    async with _write_lock:
        rows = _read_raw(EVENTS_FILE, "events")
        for row in rows:
            if row["id"] == event_id:
                row.update(normalized)
                break
        _atomic_write(EVENTS_FILE, "events", rows)


# --- groups: reads (sync) ---------------------------------------------------

def load_groups() -> list[Group]:
    return [Group.from_dict(d) for d in _read_raw(GROUPS_FILE, "groups")]


def get_group(slug: str, guild_id: int) -> Group | None:
    for group in load_groups():
        if group.slug == slug and group.guild_id == guild_id:
            return group
    return None


# --- groups: writes (async, locked, atomic) ---------------------------------

async def add_group(group: Group) -> None:
    async with _write_lock:
        rows = _read_raw(GROUPS_FILE, "groups")
        rows.append(group.to_dict())
        _atomic_write(GROUPS_FILE, "groups", rows)


async def remove_group(slug: str, guild_id: int) -> bool:
    async with _write_lock:
        rows = _read_raw(GROUPS_FILE, "groups")
        kept = [r for r in rows if not (r["slug"] == slug and r["guild_id"] == guild_id)]
        _atomic_write(GROUPS_FILE, "groups", kept)
        return len(kept) != len(rows)


async def update_group(slug: str, guild_id: int, **changes) -> None:
    async with _write_lock:
        rows = _read_raw(GROUPS_FILE, "groups")
        for row in rows:
            if row["slug"] == slug and row["guild_id"] == guild_id:
                row.update(changes)
                break
        _atomic_write(GROUPS_FILE, "groups", rows)
