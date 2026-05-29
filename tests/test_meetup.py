"""Baseline tests pinning current meetup.py behavior before the refactor."""

from datetime import timezone

import pytest

from meetup import (
    canonical_event_url,
    _parse_meetup_html,
    _to_utc,
    _extract_event_urls,
    normalize_group_input,
)


def _page(jsonld: str) -> str:
    return f'<html><head><script type="application/ld+json">{jsonld}</script></head></html>'


# ---------------------------------------------------------------------------
# canonical_event_url
# ---------------------------------------------------------------------------

CANONICAL = "https://www.meetup.com/nova-code-coffee/events/315002388"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.meetup.com/nova-code-coffee/events/315002388/",
        "https://www.meetup.com/nova-code-coffee/events/315002388",
        "https://www.meetup.com/nova-code-coffee/events/315002388/?utm_source=x&y=1",
        "http://meetup.com/nova-code-coffee/events/315002388/",
        "https://www.meetup.com/Nova-Code-Coffee/events/315002388/",
        "https://www.meetup.com/nova-code-coffee/events/315002388/attendees/",
        "https://www.meetup.com/nova-code-coffee/events/315002388/#rsvp",
    ],
)
def test_canonical_url_variants_collapse(url):
    assert canonical_event_url(url) == CANONICAL


def test_canonical_url_distinct_ids_differ():
    other = "https://www.meetup.com/nova-code-coffee/events/999999999/"
    assert canonical_event_url(other) != CANONICAL


def test_canonical_url_non_meetup_fallback_normalizes():
    # Same scheme + host + path collapse trailing slash and casing.
    assert canonical_event_url("https://example.org/Some/Path/") == canonical_event_url(
        "https://example.org/some/path"
    )


# ---------------------------------------------------------------------------
# _parse_meetup_html  ->  (name, startDate, endDate)
# ---------------------------------------------------------------------------

def test_parse_event_with_start_and_end():
    name, start, end = _parse_meetup_html(
        _page(
            '{"@type":"Event","name":"Code & Coffee",'
            '"startDate":"2026-04-15T19:00:00-04:00",'
            '"endDate":"2026-04-15T21:00:00-04:00"}'
        )
    )
    assert (name, start, end) == (
        "Code & Coffee",
        "2026-04-15T19:00:00-04:00",
        "2026-04-15T21:00:00-04:00",
    )


def test_parse_event_without_end():
    name, start, end = _parse_meetup_html(
        _page('{"@type":"Event","name":"Beach Cleanup","startDate":"2026-06-01T09:00:00Z"}')
    )
    assert (name, start, end) == ("Beach Cleanup", "2026-06-01T09:00:00Z", None)


def test_parse_event_in_graph():
    name, start, end = _parse_meetup_html(
        _page(
            '{"@graph":[{"@type":"WebPage"},'
            '{"@type":"Event","name":"Town Hall","startDate":"2026-09-09T17:00:00Z",'
            '"endDate":"2026-09-09T18:30:00Z"}]}'
        )
    )
    assert (name, start, end) == (
        "Town Hall",
        "2026-09-09T17:00:00Z",
        "2026-09-09T18:30:00Z",
    )


def test_parse_event_type_as_list():
    name, start, _ = _parse_meetup_html(
        _page('{"@type":["Event","SocialEvent"],"name":"Game Night","startDate":"2026-07-04T18:30:00Z"}')
    )
    assert (name, start) == ("Game Night", "2026-07-04T18:30:00Z")


def test_parse_no_event_returns_none():
    assert _parse_meetup_html(_page('{"@type":"Organization","name":"Org"}')) == (None, None, None)


def test_parse_malformed_jsonld_does_not_raise():
    assert _parse_meetup_html(_page("{not valid json")) == (None, None, None)


def test_parse_picks_event_among_multiple_blocks():
    html = (
        '<script type="application/ld+json">{"@type":"WebSite"}</script>'
        '<script type="application/ld+json">'
        '{"@type":"Event","name":"Meetup","startDate":"2026-01-01T00:00:00Z"}</script>'
    )
    name, start, _ = _parse_meetup_html(html)
    assert (name, start) == ("Meetup", "2026-01-01T00:00:00Z")


# ---------------------------------------------------------------------------
# _to_utc
# ---------------------------------------------------------------------------

def test_to_utc_naive_assumed_utc():
    dt = _to_utc("2026-04-15T19:00:00")
    assert dt.tzinfo == timezone.utc
    assert (dt.hour, dt.minute) == (19, 0)


def test_to_utc_offset_converted_to_utc():
    dt = _to_utc("2026-04-15T19:00:00-04:00")
    assert dt.tzinfo == timezone.utc
    assert dt.hour == 23  # 19:00 -04:00 == 23:00 UTC


def test_to_utc_none_and_invalid():
    assert _to_utc(None) is None
    assert _to_utc("") is None
    assert _to_utc("not a date") is None


# ---------------------------------------------------------------------------
# group discovery: normalize_group_input + _extract_event_urls
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "value",
    [
        "nova-code-coffee",
        "Nova-Code-Coffee",
        "https://www.meetup.com/nova-code-coffee/",
        "https://www.meetup.com/nova-code-coffee/events/",
        "www.meetup.com/nova-code-coffee/events/315002388/",
    ],
)
def test_normalize_group_input(value):
    slug, url = normalize_group_input(value)
    assert slug == "nova-code-coffee"
    assert url == "https://www.meetup.com/nova-code-coffee/events/"


def test_extract_event_urls_relative_and_absolute_deduped():
    html = """
      <a href="/nova-code-coffee/events/315002388/">Event A</a>
      <a href="https://www.meetup.com/nova-code-coffee/events/315002388/?utm=x">dup</a>
      <a href="/Nova-Code-Coffee/events/999000111/">Event B</a>
      <a href="/some-other-group/events/424242/">Other</a>
    """
    assert _extract_event_urls(html) == [
        "https://www.meetup.com/nova-code-coffee/events/315002388",
        "https://www.meetup.com/nova-code-coffee/events/999000111",
        "https://www.meetup.com/some-other-group/events/424242",
    ]


def test_extract_event_urls_none_found():
    assert _extract_event_urls("<html>no events here</html>") == []
