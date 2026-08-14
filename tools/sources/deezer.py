"""Deezer lookup: availability and audio only.

Deezer's release_date is NOT used. It reflects whichever album edition the
search lands on, which for catalogue artists is usually a remaster or
compilation (it dates Billie Jean to 2009). Years come from MusicBrainz and
Wikidata instead.
"""

from __future__ import annotations

import json
import re
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import dataclass

SEARCH_URL = "https://api.deezer.com/search"

# Markers of alternate recordings. Loose search ranks these highly, and their
# release years differ from the original, so they must never enter the pool.
VARIANT_MARKERS = (
    "live",
    "remix",
    "remaster",
    "remastered",
    "acoustic",
    "radio edit",
    "edit",
    "version",
    "instrumental",
    "karaoke",
    "cover",
    "demo",
    "reprise",
    "mix",
)


@dataclass(frozen=True)
class DeezerMatch:
    deezer_id: int
    artist: str
    title: str


def normalise(text: str) -> str:
    """Casefold, strip accents and punctuation, collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    lowered = without_accents.casefold()
    cleaned = re.sub(r"[^\w\s]", "", lowered)
    return re.sub(r"\s+", " ", cleaned).strip()


def is_variant(title: str) -> bool:
    """True if the title advertises itself as an alternate recording.

    Only text inside brackets or after " - " is examined, so a song genuinely
    called "Live Forever" or "Mixed Emotions" is not rejected.

    This check is deliberately redundant with the title-equality check in
    search_track for Deezer results, but its real purpose is rejecting
    variant-shaped SEED titles. If a seed line itself is "Take On Me (Live)",
    exact title equality would match a live recording and only this check stops it.
    """
    qualifiers = re.findall(r"\(([^)]*)\)|\[([^\]]*)\]|\s-\s(.*)$", title)
    for groups in qualifiers:
        text = normalise(" ".join(g for g in groups if g))
        for marker in VARIANT_MARKERS:
            if re.search(rf"\b{re.escape(marker)}\b", text):
                return True
    return False


def _fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "Chronotune/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def search_track(artist: str, title: str, *, fetch_json=_fetch_json) -> DeezerMatch | None:
    """Find a streamable, non-variant Deezer track matching artist and title.

    Uses loose search deliberately: strict field syntax
    (artist:"…" track:"…") returns nothing for some tracks that loose search
    finds, so results are filtered client-side instead.
    """
    query = urllib.parse.quote(f"{artist} {title}")
    payload = fetch_json(f"{SEARCH_URL}?q={query}&limit=25")

    wanted_artist = normalise(artist)
    wanted_title = normalise(title)

    for entry in payload.get("data", []):
        found_title = entry.get("title", "")
        found_artist = (entry.get("artist") or {}).get("name", "")

        if not entry.get("preview"):
            continue
        if is_variant(found_title):
            continue
        if normalise(found_artist) != wanted_artist:
            continue
        if normalise(found_title) != wanted_title:
            continue

        return DeezerMatch(
            deezer_id=int(entry["id"]),
            artist=found_artist,
            title=found_title,
        )

    return None
