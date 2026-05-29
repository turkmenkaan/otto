"""Tests for the JSON storage layer (atomic, locked writes)."""

from datetime import datetime, timezone

import pytest

import storage
from models import Event, EventStatus, Group


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
    monkeypatch.setattr(storage, "GROUPS_FILE", str(tmp_path / "groups.json"))
    return tmp_path


def _group(slug: str = "nova", guild_id: int = 1) -> Group:
    return Group(
        slug=slug,
        url=f"https://www.meetup.com/{slug}/events/",
        guild_id=guild_id,
        channel_id=42,
        added_by=7,
    )


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


# --- groups -----------------------------------------------------------------

async def test_add_and_get_group(temp_store):
    assert storage.load_groups() == []
    await storage.add_group(_group("nova"))
    g = storage.get_group("nova", 1)
    assert g is not None and g.channel_id == 42 and g.seeded is False


async def test_get_group_scoped_by_guild(temp_store):
    await storage.add_group(_group("nova", guild_id=1))
    assert storage.get_group("nova", 999) is None


async def test_update_group_seeded(temp_store):
    await storage.add_group(_group("nova"))
    await storage.update_group("nova", 1, seeded=True)
    assert storage.get_group("nova", 1).seeded is True


async def test_remove_group(temp_store):
    await storage.add_group(_group("nova"))
    assert await storage.remove_group("nova", 1) is True
    assert storage.get_group("nova", 1) is None
    assert await storage.remove_group("nova", 1) is False  # already gone
