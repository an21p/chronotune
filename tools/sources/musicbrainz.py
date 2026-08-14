"""MusicBrainz lookup for a track's original release year.

Queries release-GROUPS, not recordings. Recording search returns reissue dates
(it dates Daft Punk's "Around the World" to 2004; the answer is 1997).

MusicBrainz requires a descriptive User-Agent and roughly 1 request/second.
Both are honoured here.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

SEARCH_URL = "https://musicbrainz.org/ws/2/release-group"
USER_AGENT = "Chronotune/0.1 (pishias92@gmail.com)"
RATE_LIMIT_SECONDS = 1.1


def _fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def _escape(value: str) -> str:
    """Escape backslashes and quotes for a Lucene phrase query.

    An unescaped quote closes the phrase early, producing a malformed query
    that returns wrong results or a 400 — which would halt a builder run
    partway through. Mirrors the equivalent escaping in the Wikidata adapter.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')


def first_release_year(
    artist: str,
    title: str,
    *,
    fetch_json=_fetch_json,
    sleep=time.sleep,
) -> int | None:
    """Earliest first-release-date year across matching release groups."""
    lucene = f'releasegroup:"{_escape(title)}" AND artist:"{_escape(artist)}"'
    query = urllib.parse.urlencode({"query": lucene, "fmt": "json", "limit": 10})

    try:
        payload = fetch_json(f"{SEARCH_URL}?{query}")
    finally:
        sleep(RATE_LIMIT_SECONDS)

    years = []
    for group in payload.get("release-groups", []):
        date = (group.get("first-release-date") or "").strip()
        if len(date) >= 4 and date[:4].isdigit():
            years.append(int(date[:4]))

    return min(years) if years else None
