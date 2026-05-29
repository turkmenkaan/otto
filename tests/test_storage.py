"""Tests for the JSON storage layer (atomic, locked writes)."""

from datetime import datetime, timezone

import pytest

import storage
from models import Event, EventStatus


def _event(event_id: str = "e1") -> Event:
    return Event(
        id=event_id,
        event_name="X",
        meetup_link="https://www.meetup.com/g/events/1/",
        event_datetime=datetime(2026, 4, 15, 19, 0, tzinfo=timezone.utc),
        guild_id=1,
        event_end=datetime(2026, 4, 15, 22, 0, tzinfo=timezone.utc),
        submitter_id=9,
    )


@pytest.fixture
def temp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(storage, "EVENTS_FILE", str(tmp_path / "events.json"))
    return tmp_path


async def test_add_and_load(temp_store):
    assert storage.load_events() == []
    await storage.add_event(_event("a"))
    events = storage.load_events()
    assert len(events) == 1
    assert events[0].id == "a"
    assert events[0].status == EventStatus.PENDING


async def test_update_event(temp_store):
    await storage.add_event(_event("a"))
    await storage.update_event("a", status=EventStatus.COMPLETED)
    assert storage.get_event("a").status == EventStatus.COMPLETED


async def test_get_events_by_status(temp_store):
    await storage.add_event(_event("a"))
    await storage.add_event(_event("b"))
    await storage.update_event("b", status=EventStatus.COMPLETED)
    assert [e.id for e in storage.get_events_by_status(EventStatus.PENDING)] == ["a"]


async def test_atomic_write_leaves_no_tmp_file(temp_store):
    await storage.add_event(_event("a"))
    assert not (temp_store / "events.json.tmp").exists()
    assert (temp_store / "events.json").exists()
