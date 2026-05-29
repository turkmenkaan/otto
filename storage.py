"""JSON persistence for events. Reads are sync; writes are async, locked and atomic."""

import asyncio
import json
import os

from models import Event, EventStatus

DATA_DIR = os.getenv("DATA_DIR", "data")
EVENTS_FILE = os.path.join(DATA_DIR, "events.json")

# Serializes read-modify-write cycles so the poll loop and interaction handlers
# can't clobber each other's writes within the single event loop.
_write_lock = asyncio.Lock()


def _read_raw() -> list[dict]:
    if not os.path.exists(EVENTS_FILE):
        return []
    with open(EVENTS_FILE, "r") as f:
        return json.load(f).get("events", [])


def _atomic_write(rows: list[dict]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = EVENTS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"events": rows}, f, indent=2)
    os.replace(tmp, EVENTS_FILE)  # atomic on POSIX


# --- reads (sync) -----------------------------------------------------------

def load_events() -> list[Event]:
    return [Event.from_dict(d) for d in _read_raw()]


def get_event(event_id: str) -> Event | None:
    for event in load_events():
        if event.id == event_id:
            return event
    return None


def get_events_by_status(status: EventStatus | str) -> list[Event]:
    value = status.value if isinstance(status, EventStatus) else status
    return [e for e in load_events() if e.status.value == value]


# --- writes (async, locked, atomic) -----------------------------------------

async def add_event(event: Event) -> None:
    async with _write_lock:
        rows = _read_raw()
        rows.append(event.to_dict())
        _atomic_write(rows)


async def update_event(event_id: str, **changes) -> None:
    """Apply field changes to one event. Enum values are stored as their .value."""
    normalized = {
        k: (v.value if isinstance(v, EventStatus) else v) for k, v in changes.items()
    }
    async with _write_lock:
        rows = _read_raw()
        for row in rows:
            if row["id"] == event_id:
                row.update(normalized)
                break
        _atomic_write(rows)
