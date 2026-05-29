"""Best-effort scraping of a Meetup event page's schema.org JSON-LD."""

import asyncio
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import aiohttp
from dateutil import parser as dateutil_parser

_EVENT_ID_RE = re.compile(r"/events/(\d+)")


def canonical_event_url(url: str) -> str:
    """Normalize a Meetup event URL to a stable de-dup key.

    The key is the URL truncated at the numeric event id, lowercased, with
    query string, fragment, trailing slash, www/non-www and http/https
    differences collapsed:

        https://www.meetup.com/Nova-Code-Coffee/events/315002388/?utm=x
            -> https://www.meetup.com/nova-code-coffee/events/315002388

    URLs that don't look like a Meetup event fall back to a normalized
    scheme://host/path form so they still de-dup against themselves.
    """
    parsed = urlparse((url or "").strip())
    host = parsed.netloc.lower()
    path = parsed.path or ""

    match = _EVENT_ID_RE.search(path)
    if host.endswith("meetup.com") and match:
        prefix = path[: match.end()].rstrip("/").lower()
        return f"https://www.meetup.com{prefix}"

    scheme = (parsed.scheme or "https").lower()
    return f"{scheme}://{host}{path.rstrip('/')}".lower()


def _parse_meetup_html(html: str) -> tuple[str | None, str | None, str | None]:
    """Pull (name, startDate, endDate) out of an Event object in the JSON-LD."""
    name = None
    start = None
    end = None

    def walk(node):
        if isinstance(node, list):
            for n in node:
                yield from walk(n)
        elif isinstance(node, dict):
            graph = node.get("@graph")
            if isinstance(graph, list):
                for n in graph:
                    yield from walk(n)
            yield node

    blocks = re.findall(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    for block in blocks:
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        for obj in walk(data):
            types = obj.get("@type")
            types = types if isinstance(types, list) else [types]
            if "Event" in types:
                name = name or obj.get("name")
                start = start or obj.get("startDate")
                end = end or obj.get("endDate")
    return name, start, end


def _to_utc(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp to a UTC datetime, or None if unusable."""
    if not value:
        return None
    try:
        parsed = dateutil_parser.parse(value)
    except (ValueError, OverflowError):
        return None
    return (
        parsed.astimezone(timezone.utc)
        if parsed.tzinfo
        else parsed.replace(tzinfo=timezone.utc)
    )


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    )
}


async def _fetch_html(url: str) -> str | None:
    """GET a page, returning its HTML or None on any failure (timeout, non-200, DNS)."""
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout, headers=_HEADERS) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                return await resp.text()
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None


async def fetch_meetup_event(
    url: str,
) -> tuple[str | None, datetime | None, datetime | None]:
    """Best-effort lookup of a Meetup event's name, UTC start and UTC end time.

    Any field may come back None — Meetup sits behind Cloudflare and not every
    event lists an end time, so the caller must treat missing values as normal
    and fall back accordingly.
    """
    html = await _fetch_html(url)
    if html is None:
        return None, None, None
    name, start, end = _parse_meetup_html(html)
    return name, _to_utc(start), _to_utc(end)


def normalize_group_input(value: str) -> tuple[str, str]:
    """Turn a group slug or URL into (slug, events_url).

    Accepts 'nova-code-coffee', a group URL, or an events URL; returns the
    lowercased slug and the canonical group events page URL.
    """
    value = (value or "").strip()
    if "meetup.com" in value or value.startswith("http"):
        path = urlparse(value if value.startswith("http") else f"https://{value}").path
        parts = [p for p in path.split("/") if p]
        slug = parts[0] if parts else ""
    else:
        slug = value.strip("/").split("/")[0]
    slug = slug.lower()
    return slug, f"https://www.meetup.com/{slug}/events/"


def _extract_event_urls(html: str) -> list[str]:
    """Canonical event URLs linked on a group page, de-duped, order preserved."""
    urls: list[str] = []
    seen: set[str] = set()
    for slug, event_id in re.findall(r"/([A-Za-z0-9_-]+)/events/(\d+)", html):
        canonical = f"https://www.meetup.com/{slug.lower()}/events/{event_id}"
        if canonical not in seen:
            seen.add(canonical)
            urls.append(canonical)
    return urls


async def fetch_group_event_urls(group_events_url: str) -> list[str]:
    """Best-effort list of event URLs currently listed on a group's events page."""
    html = await _fetch_html(group_events_url)
    return _extract_event_urls(html) if html else []
