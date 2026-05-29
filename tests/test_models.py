"""Tests for the Event/Group dataclasses and their serialization."""

from datetime import datetime, timezone

from models import Event, Group, EventStatus, EventSource


def _event(**kw) -> Event:
    base = dict(
        id="e1",
        event_name="Code & Coffee",
        meetup_link="https://www.meetup.com/g/events/1/",
        event_datetime=datetime(2026, 4, 15, 19, 0, tzinfo=timezone.utc),
        guild_id=10,
        event_end=datetime(2026, 4, 15, 22, 0, tzinfo=timezone.utc),
        submitter_id=99,
    )
    base.update(kw)
    return Event(**base)


def test_event_roundtrip():
    e = _event()
    d = e.to_dict()
    assert d["status"] == "pending"  # enums stored as plain strings
    assert d["source"] == "manual"
    assert Event.from_dict(d) == e


def test_event_from_dict_legacy_defaults():
    # A row written before event_end / source / group existed.
    legacy = {
        "id": "old",
        "event_name": "Legacy",
        "meetup_link": "https://www.meetup.com/g/events/2/",
        "event_datetime": "2026-01-01T00:00:00+00:00",
        "submitter_id": 5,
        "guild_id": 7,
        "status": "pending",
    }
    e = Event.from_dict(legacy)
    assert e.event_end is None
    assert e.source == EventSource.MANUAL
    assert e.group is None
    assert e.status == EventStatus.PENDING


def test_event_to_dict_handles_none_end():
    assert _event(event_end=None).to_dict()["event_end"] is None


def test_event_auto_source_and_no_submitter():
    e = _event(source=EventSource.AUTO, submitter_id=None, group="nova")
    d = e.to_dict()
    assert d["source"] == "auto"
    assert d["submitter_id"] is None
    assert Event.from_dict(d) == e


def test_group_roundtrip():
    g = Group(
        slug="nova",
        url="https://www.meetup.com/nova/events/",
        guild_id=1,
        channel_id=2,
        added_by=3,
    )
    assert Group.from_dict(g.to_dict()) == g
