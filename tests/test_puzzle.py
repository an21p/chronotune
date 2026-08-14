import random
from datetime import date

from chronotune.puzzle import EPOCH, daily_track_id, pick_unseen_track_id, puzzle_number
from chronotune.store import Pool, Track


def _pool(ids):
    tracks = [Track(deezer_id=i, artist="A", title=f"T{i}", year=2000) for i in ids]
    return Pool(tracks, list(ids))


def test_puzzle_number_starts_at_one_on_the_epoch():
    assert puzzle_number(EPOCH) == 1
    assert puzzle_number(date(2026, 1, 2)) == 2


def test_daily_is_deterministic_for_a_given_date():
    pool = _pool([10, 20, 30])
    day = date(2026, 3, 5)

    assert daily_track_id(pool, day) == daily_track_id(pool, day)


def test_consecutive_days_walk_the_order():
    pool = _pool([10, 20, 30])

    assert daily_track_id(pool, date(2026, 1, 1)) == 10
    assert daily_track_id(pool, date(2026, 1, 2)) == 20
    assert daily_track_id(pool, date(2026, 1, 3)) == 30


def test_daily_wraps_when_the_list_is_exhausted():
    pool = _pool([10, 20, 30])

    assert daily_track_id(pool, date(2026, 1, 4)) == 10


def test_appending_to_the_order_does_not_change_earlier_days():
    """The whole point of append-only: past dailies must be stable."""
    before = _pool([10, 20, 30])
    after = _pool([10, 20, 30, 40, 50])

    for offset in range(3):
        day = date(2026, 1, 1 + offset)
        assert daily_track_id(before, day) == daily_track_id(after, day)


def test_pick_unseen_excludes_seen_tracks():
    pool = _pool([10, 20, 30])

    assert pick_unseen_track_id(pool, [10, 20], rng=random.Random(0)) == 30


def test_pick_unseen_returns_none_when_everything_is_seen():
    pool = _pool([10, 20])

    assert pick_unseen_track_id(pool, [10, 20], rng=random.Random(0)) is None


def test_pick_unseen_is_deterministic_for_a_seeded_rng():
    pool = _pool([10, 20, 30, 40])

    first = pick_unseen_track_id(pool, [], rng=random.Random(7))
    second = pick_unseen_track_id(pool, [], rng=random.Random(7))

    assert first == second
