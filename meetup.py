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


def _parse_meetup_html(html: str) -> tuple[str | None, str | None]:
    """Pull (name, startDate) out of an Event object in the page's JSON-LD."""
    name = None
    start = None

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
    return name, start


async def fetch_meetup_event(url: str) -> tuple[str | None, datetime | None]:
    """Best-effort lookup of a Meetup event's name and UTC start time.

    Either field may come back None — Meetup sits behind Cloudflare, so the
    caller must treat failure as normal and fall back to manual input.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
        )
    }
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None, None
                html = await resp.text()
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None, None

    name, start = _parse_meetup_html(html)

    dt = None
    if start:
        try:
            parsed = dateutil_parser.parse(start)
            dt = (
                parsed.astimezone(timezone.utc)
                if parsed.tzinfo
                else parsed.replace(tzinfo=timezone.utc)
            )
        except (ValueError, OverflowError):
            dt = None
    return name, dt
