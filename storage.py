import json
import os

EVENTS_FILE = "events.json"


def load_events() -> list[dict]:
    if not os.path.exists(EVENTS_FILE):
        return []
    with open(EVENTS_FILE, "r") as f:
        return json.load(f).get("events", [])


def save_events(events: list[dict]):
    with open(EVENTS_FILE, "w") as f:
        json.dump({"events": events}, f, indent=2)


def add_event(event: dict):
    events = load_events()
    events.append(event)
    save_events(events)


def update_event(event_id: str, updates: dict):
    events = load_events()
    for e in events:
        if e["id"] == event_id:
            e.update(updates)
            break
    save_events(events)


def get_event(event_id: str) -> dict | None:
    for e in load_events():
        if e["id"] == event_id:
            return e
    return None


def get_events_by_status(status: str) -> list[dict]:
    return [e for e in load_events() if e["status"] == status]
