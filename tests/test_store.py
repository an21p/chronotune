import json

import pytest

from chronotune.store import Pool, PoolError, Track, load_pool


def _write(tmp_path, tracks, order):
    tracks_path = tmp_path / "tracks.json"
    order_path = tmp_path / "daily_order.json"
    tracks_path.write_text(json.dumps(tracks))
    order_path.write_text(json.dumps(order))
    return tracks_path, order_path


TRACK = {
    "deezer_id": 42,
    "artist": "Queen",
    "title": "Bohemian Rhapsody",
    "year": 1975,
    "sources": {"musicbrainz": 1975, "wikidata": 1975},
}


def test_loads_tracks_and_order(tmp_path):
    pool = load_pool(*_write(tmp_path, [TRACK], [42]))

    assert len(pool) == 1
    assert pool.daily_order == [42]
    assert pool.by_id(42) == Track(deezer_id=42, artist="Queen",
                                   title="Bohemian Rhapsody", year=1975)


def test_raises_when_tracks_file_is_missing(tmp_path):
    order_path = tmp_path / "daily_order.json"
    order_path.write_text("[]")

    with pytest.raises(PoolError, match="not found"):
        load_pool(tmp_path / "missing.json", order_path)


def test_raises_when_pool_is_empty(tmp_path):
    with pytest.raises(PoolError, match="empty"):
        load_pool(*_write(tmp_path, [], []))


def test_raises_when_daily_order_references_an_unknown_track(tmp_path):
    """Never skip — skipping shifts every subsequent day."""
    with pytest.raises(PoolError, match="99"):
        load_pool(*_write(tmp_path, [TRACK], [42, 99]))


def test_raises_on_duplicate_deezer_ids(tmp_path):
    with pytest.raises(PoolError, match="duplicate"):
        load_pool(*_write(tmp_path, [TRACK, TRACK], [42]))


def test_by_id_raises_keyerror_for_unknown_track(tmp_path):
    pool = load_pool(*_write(tmp_path, [TRACK], [42]))

    with pytest.raises(KeyError):
        pool.by_id(999)


@pytest.mark.parametrize(
    "bad_entry",
    [
        {"artist": "Queen", "title": "X", "year": 1975},                      # no deezer_id
        {"deezer_id": 1, "title": "X", "year": 1975},                          # no artist
        {"deezer_id": 1, "artist": "Q", "title": "X", "year": None},           # None year
        {"deezer_id": "abc", "artist": "Q", "title": "X", "year": 1975},       # non-numeric id
        {"deezer_id": 1, "artist": "Q", "title": "X", "year": "not-a-year"},   # non-numeric year
    ],
)
def test_malformed_track_record_raises_pool_error(tmp_path, bad_entry):
    """A caller wrapping startup in `except PoolError` must catch these."""
    with pytest.raises(PoolError, match="malformed"):
        load_pool(*_write(tmp_path, [bad_entry], []))
