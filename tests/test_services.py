"""Tests for the pure domain logic in services.py."""

from datetime import datetime, timedelta, timezone

import services
from models import Event, EventStatus

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)


def _event(start, end=None, status=EventStatus.PENDING,
           link="https://www.meetup.com/g/events/1/", submitter=1) -> Event:
    return Event(
        id="x",
        event_name="X",
        meetup_link=link,
        event_datetime=start,
        guild_id=1,
        event_end=end,
        status=status,
        submitter_id=submitter,
    )


def test_is_duplicate_matches_canonical():
    events = [_event(NOW, link="https://www.meetup.com/Nova/events/315002388/?x=1")]
    assert services.is_duplicate("https://www.meetup.com/nova/events/315002388", events)
    assert not services.is_duplicate("https://www.meetup.com/nova/events/999/", events)


def test_is_in_past_allows_same_day():
    assert services.is_in_past(NOW - timedelta(days=1), NOW)
    assert not services.is_in_past(NOW, NOW)
    assert not services.is_in_past(NOW + timedelta(days=1), NOW)


def test_compute_event_end_uses_scraped_when_sane():
    end = NOW + timedelta(hours=2)
    assert services.compute_event_end(NOW, end, 3) == (end, False)


def test_compute_event_end_falls_back():
    assert services.compute_event_end(NOW, None, 3) == (NOW + timedelta(hours=3), True)
    # end-before-start is rejected as bad data
    assert services.compute_event_end(NOW, NOW - timedelta(hours=1), 3) == (
        NOW + timedelta(hours=3),
        True,
    )


def test_effective_end():
    assert services.effective_end(_event(NOW, end=NOW + timedelta(hours=2)), 3) == (
        NOW + timedelta(hours=2)
    )
    assert services.effective_end(_event(NOW, end=None), 3) == NOW + timedelta(hours=3)


def test_events_due_for_followup():
    started = NOW - timedelta(hours=5)
    due = _event(started, end=NOW - timedelta(hours=1))           # ended + pending
    not_yet = _event(NOW, end=NOW + timedelta(hours=1))           # not ended
    done = _event(started, end=NOW - timedelta(hours=1),
                  status=EventStatus.COMPLETED)                   # not pending
    assert services.events_due_for_followup([due, not_yet, done], NOW, 3) == [due]


def test_events_due_for_followup_legacy_no_end_uses_default():
    started = NOW - timedelta(hours=4)  # +3h default => ended 1h ago
    e = _event(started, end=None)
    assert services.events_due_for_followup([e], NOW, 3) == [e]


def test_select_new_event_urls_dedups_and_keeps_order():
    known = {"https://www.meetup.com/g/events/1"}
    fetched = [
        "https://www.meetup.com/g/events/1/",        # already known
        "https://www.meetup.com/g/events/2/?x=1",    # new
        "https://www.meetup.com/g/events/2/",        # dup of previous
        "https://www.meetup.com/g/events/3/",        # new
    ]
    assert services.select_new_event_urls(fetched, known) == [
        "https://www.meetup.com/g/events/2/?x=1",
        "https://www.meetup.com/g/events/3/",
    ]
