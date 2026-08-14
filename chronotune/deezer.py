"""Resolve a Deezer preview URL at request time.

Preview URLs embed an expiry token (~7h), so they are never stored in
tracks.json — only the track id is. The MP3 responds with
`access-control-allow-origin: *`, so the browser can read it with the Web Audio
API without a proxy.
"""

from __future__ import annotations

import json
import urllib.request

TRACK_URL = "https://api.deezer.com/track"


class PreviewUnavailable(Exception):
    """Raised when no playable preview URL could be obtained."""


def _fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "Chronotune/0.1"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def resolve_preview_url(deezer_id: int, *, fetch_json=_fetch_json, attempts: int = 2) -> str:
    last_error: Exception | None = None

    for _ in range(attempts):
        try:
            payload = fetch_json(f"{TRACK_URL}/{deezer_id}")
        except Exception as error:
            last_error = error
            continue

        if "error" in payload:
            last_error = PreviewUnavailable(f"Deezer error: {payload['error']}")
            continue

        preview = payload.get("preview") or ""
        if preview:
            return preview

        last_error = PreviewUnavailable(f"track {deezer_id} has no preview")

    raise PreviewUnavailable(f"could not resolve preview for {deezer_id}") from last_error
