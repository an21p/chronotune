"""Load and validate the curated pool.

All validation happens at startup and fails loudly. A daily_order entry with no
matching track is a hard error rather than a skip: skipping would shift every
subsequent day and invalidate already-shared grids.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class PoolError(Exception):
    """Raised when the curated data files are missing or inconsistent."""


@dataclass(frozen=True)
class Track:
    deezer_id: int
    artist: str
    title: str
    year: int


class Pool:
    def __init__(self, tracks: list[Track], daily_order: list[int]):
        self.tracks = tracks
        self.daily_order = daily_order
        self._by_id = {track.deezer_id: track for track in tracks}

    def by_id(self, deezer_id: int) -> Track:
        return self._by_id[deezer_id]

    def __len__(self) -> int:
        return len(self.tracks)


def _read_json(path: Path):
    if not path.exists():
        raise PoolError(f"{path} not found. Run tools/build_tracks.py first.")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise PoolError(f"{path} is not valid JSON: {error}") from error


def load_pool(tracks_path, order_path) -> Pool:
    raw_tracks = _read_json(Path(tracks_path))
    raw_order = _read_json(Path(order_path))

    if not raw_tracks:
        raise PoolError("Track pool is empty. Run tools/build_tracks.py first.")

    tracks = [
        Track(
            deezer_id=int(entry["deezer_id"]),
            artist=entry["artist"],
            title=entry["title"],
            year=int(entry["year"]),
        )
        for entry in raw_tracks
    ]

    ids = [track.deezer_id for track in tracks]
    if len(ids) != len(set(ids)):
        duplicates = {i for i in ids if ids.count(i) > 1}
        raise PoolError(f"duplicate deezer_id in tracks.json: {sorted(duplicates)}")

    known = set(ids)
    missing = [i for i in raw_order if i not in known]
    if missing:
        raise PoolError(
            f"daily_order references tracks missing from tracks.json: {missing}. "
            "Do not remove them from daily_order — that shifts every later day. "
            "Restore the track data or fix the entry deliberately."
        )

    return Pool(tracks, list(raw_order))
