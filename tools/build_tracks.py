"""Build the curated track pool.

Consensus rule: a track is accepted only when MusicBrainz and Wikidata report
the same year. Deezer decides availability and supplies the audio, but gets no
vote on the year — its release_date reflects whichever album edition the search
lands on (it dates Billie Jean to 2009).

Usage:
    python tools/build_tracks.py --seeds data/seeds.txt
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

# Allow `python tools/build_tracks.py` as well as `python -m tools.build_tracks`.
# Running a script by path puts tools/ on sys.path rather than the repo root, so
# the absolute `tools.sources` imports below would fail with ModuleNotFoundError.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.sources import deezer, musicbrainz, wikidata

DATA_DIR = Path("data")
TRACKS_PATH = DATA_DIR / "tracks.json"
ORDER_PATH = DATA_DIR / "daily_order.json"
REJECTS_PATH = DATA_DIR / "rejects.json"


class AppendOnlyViolation(Exception):
    """Raised when a write would reorder, edit or remove daily_order entries."""


@dataclass
class Evaluation:
    status: str
    track: dict | None = None
    reason: str | None = None


def parse_seeds(text: str) -> list[tuple[str, str]]:
    """Parse 'Artist - Title' lines, ignoring blanks and # comments."""
    seeds = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if " - " not in line:
            continue
        artist, title = line.split(" - ", 1)
        seeds.append((artist.strip(), title.strip()))
    return seeds


def evaluate_seed(
    artist: str,
    title: str,
    *,
    search_track=deezer.search_track,
    mb_year=musicbrainz.first_release_year,
    wd_year=wikidata.first_publication_year,
) -> Evaluation:
    """Apply the acceptance rule to a single seed."""
    # Deezer first: it is fast and unrated, so a miss saves two slow lookups.
    match = search_track(artist, title)
    if match is None:
        return Evaluation("rejected", reason="no_deezer_match")

    mb = mb_year(artist, title)
    if mb is None:
        return Evaluation("rejected", reason="mb_missing")

    wd = wd_year(artist, title)
    if wd is None:
        return Evaluation("rejected", reason="wd_missing")

    if mb != wd:
        return Evaluation("rejected", reason="year_conflict")

    return Evaluation(
        "accepted",
        track={
            "deezer_id": match.deezer_id,
            "artist": match.artist,
            "title": match.title,
            "year": mb,
            "sources": {"musicbrainz": mb, "wikidata": wd},
        },
    )


def assert_append_only(existing: list[int], updated: list[int]) -> None:
    """Guarantee `existing` is an exact prefix of `updated`.

    Reordering or removing entries silently changes which song players got on
    days they have already played, and invalidates every shared grid. This is
    an enforced invariant, not a convention.
    """
    if len(updated) < len(existing):
        raise AppendOnlyViolation(
            f"daily_order shrank from {len(existing)} to {len(updated)} entries; "
            "entries must never be removed"
        )

    for index, (old, new) in enumerate(zip(existing, updated)):
        if old != new:
            raise AppendOnlyViolation(
                f"daily_order diverges at index {index}: {old} != {new}. "
                "Existing entries must never be reordered or edited."
            )


def _load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def _cache_key(artist: str, title: str) -> str:
    return f"{deezer.normalise(artist)}|{deezer.normalise(title)}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build the Chronotune track pool.")
    parser.add_argument("--seeds", default="data/seeds.txt")
    parser.add_argument("--out", default=str(TRACKS_PATH))
    parser.add_argument("--refresh", action="store_true",
                        help="Re-evaluate seeds already present in tracks.json")
    args = parser.parse_args(argv)

    tracks_path = Path(args.out)
    tracks = _load_json(tracks_path, [])
    order = _load_json(ORDER_PATH, [])
    rejects = _load_json(REJECTS_PATH, [])

    original_order = list(order)
    known = {_cache_key(t["artist"], t["title"]) for t in tracks}
    in_order = set(order)
    # Skip previously rejected seeds too. This is the expensive case: without
    # it, every rerun re-queries MusicBrainz and Wikidata for seeds already
    # known to fail, at 1 req/s. Adding 20 seeds should cost 20 lookups.
    refused = {_cache_key(r["artist"], r["title"]) for r in rejects}

    seeds = parse_seeds(Path(args.seeds).read_text())
    print(f"{len(seeds)} seeds, {len(tracks)} already accepted, {len(rejects)} rejected")

    for artist, title in seeds:
        key = _cache_key(artist, title)
        if not args.refresh and (key in known or key in refused):
            continue

        try:
            result = evaluate_seed(artist, title)
        except Exception as error:  # network failures must not lose progress
            print(f"  ERROR {artist} - {title}: {error}")
            continue

        if result.status == "rejected":
            print(f"  reject {artist} - {title} ({result.reason})")
            rejects.append({"artist": artist, "title": title, "reason": result.reason})
            _write_json(REJECTS_PATH, rejects)
            continue

        track = result.track
        print(f"  accept {artist} - {title} -> {track['year']}")

        if key not in known:
            tracks.append(track)
            known.add(key)
        if track["deezer_id"] not in in_order:
            order.append(track["deezer_id"])
            in_order.add(track["deezer_id"])

        # Resumable: persist after every acceptance so a crash loses nothing.
        assert_append_only(original_order, order)
        _write_json(tracks_path, tracks)
        _write_json(ORDER_PATH, order)

    assert_append_only(original_order, order)
    _write_json(tracks_path, tracks)
    _write_json(ORDER_PATH, order)

    print(f"\n{len(tracks)} tracks, {len(order)} daily slots, {len(rejects)} rejects")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
