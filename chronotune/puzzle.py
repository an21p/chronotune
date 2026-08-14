"""Puzzle selection.

The daily walks data/daily_order.json directly rather than shuffling the pool.
A seeded shuffle would be recomputed over the whole pool, so every builder run
that added tracks would reorder the sequence and change which song players got
on days they had already played. Because daily_order is append-only, indexing
into it keeps past dailies stable forever.
"""

from __future__ import annotations

import random as _random
from datetime import date

from chronotune.store import Pool

EPOCH = date(2026, 1, 1)


def _days_since_epoch(today: date) -> int:
    return (today - EPOCH).days


def puzzle_number(today: date) -> int:
    """1-based puzzle number shown to players and used in share text."""
    return _days_since_epoch(today) + 1


def daily_track_id(pool: Pool, today: date) -> int:
    order = pool.daily_order
    return order[_days_since_epoch(today) % len(order)]


def pick_unseen_track_id(pool: Pool, seen: list[int], *, rng=_random) -> int | None:
    """A random track the player has not played in infinite mode."""
    seen_set = set(seen)
    candidates = sorted(t.deezer_id for t in pool.tracks if t.deezer_id not in seen_set)
    if not candidates:
        return None
    return rng.choice(candidates)
