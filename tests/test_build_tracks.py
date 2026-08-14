import json

import pytest

from tools.build_tracks import (
    AppendOnlyViolation,
    assert_append_only,
    evaluate_seed,
    parse_seeds,
)
from tools.sources.deezer import DeezerMatch

MATCH = DeezerMatch(deezer_id=42, artist="Queen", title="Bohemian Rhapsody")


def _evaluate(match=MATCH, mb=1975, wd=1975):
    return evaluate_seed(
        "Queen",
        "Bohemian Rhapsody",
        search_track=lambda a, t: match,
        mb_year=lambda a, t: mb,
        wd_year=lambda a, t: wd,
    )


def test_parse_seeds_splits_on_the_first_dash_only():
    text = "Queen - Bohemian Rhapsody\nJay-Z - 99 Problems\n"

    assert parse_seeds(text) == [("Queen", "Bohemian Rhapsody"), ("Jay-Z", "99 Problems")]


def test_parse_seeds_ignores_blanks_and_comments():
    text = "\n# a comment\nQueen - Bohemian Rhapsody\n   \n"

    assert parse_seeds(text) == [("Queen", "Bohemian Rhapsody")]


def test_accepts_when_musicbrainz_and_wikidata_agree():
    result = _evaluate(mb=1975, wd=1975)

    assert result.status == "accepted"
    assert result.track == {
        "deezer_id": 42,
        "artist": "Queen",
        "title": "Bohemian Rhapsody",
        "year": 1975,
        "sources": {"musicbrainz": 1975, "wikidata": 1975},
    }


def test_rejects_on_year_conflict():
    result = _evaluate(mb=1984, wd=1985)

    assert result.status == "rejected"
    assert result.reason == "year_conflict"


def test_rejects_when_musicbrainz_is_missing():
    assert _evaluate(mb=None).reason == "mb_missing"


def test_rejects_when_wikidata_is_missing():
    assert _evaluate(wd=None).reason == "wd_missing"


def test_rejects_when_deezer_has_no_match():
    assert _evaluate(match=None).reason == "no_deezer_match"


def test_deezer_is_checked_before_the_slow_sources():
    """Deezer is fast and unrated; skip MusicBrainz/Wikidata when it misses."""
    called = []

    evaluate_seed(
        "X", "Y",
        search_track=lambda a, t: None,
        mb_year=lambda a, t: called.append("mb"),
        wd_year=lambda a, t: called.append("wd"),
    )

    assert called == []


def test_append_only_allows_pure_appends():
    assert_append_only([1, 2, 3], [1, 2, 3, 4])
    assert_append_only([], [1])
    assert_append_only([1, 2], [1, 2])


def test_append_only_rejects_reordering():
    with pytest.raises(AppendOnlyViolation) as excinfo:
        assert_append_only([1, 2, 3], [1, 3, 2])

    assert "index 1" in str(excinfo.value)


def test_append_only_rejects_removal():
    with pytest.raises(AppendOnlyViolation):
        assert_append_only([1, 2, 3], [1, 2])


def test_append_only_rejects_edits_in_place():
    with pytest.raises(AppendOnlyViolation) as excinfo:
        assert_append_only([1, 2, 3], [1, 9, 3, 4])

    assert "index 1" in str(excinfo.value)


def _fake_evaluate(mapping):
    """Build an evaluate() stand-in from {(artist, title): Evaluation}."""
    def evaluate(artist, title):
        return mapping[(artist, title)]
    return evaluate


def _accepted(deezer_id, artist, title, year):
    from tools.build_tracks import Evaluation
    return Evaluation("accepted", track={
        "deezer_id": deezer_id, "artist": artist, "title": title,
        "year": year, "sources": {"musicbrainz": year, "wikidata": year},
    })


def _run(tmp_path, seeds_text, mapping, refresh=False):
    from tools.build_tracks import main
    seeds = tmp_path / "seeds.txt"
    seeds.write_text(seeds_text)
    argv = ["--seeds", str(seeds)] + (["--refresh"] if refresh else [])
    main(argv, evaluate=_fake_evaluate(mapping), data_dir=str(tmp_path))
    return json.loads((tmp_path / "daily_order.json").read_text())


def test_main_preserves_daily_order_prefix_across_runs(tmp_path):
    """The real regression test: main() must never disturb an existing order.

    This exercises the production write path, not list concatenation. Deleting
    assert_append_only from the source must make this fail.
    """
    mapping = {
        ("Queen", "Bohemian Rhapsody"): _accepted(1, "Queen", "Bohemian Rhapsody", 1975),
        ("Blur", "Song 2"): _accepted(2, "Blur", "Song 2", 1997),
    }
    first = _run(tmp_path, "Queen - Bohemian Rhapsody\n", mapping)
    assert first == [1]

    mapping[("Blur", "Song 2")] = _accepted(2, "Blur", "Song 2", 1997)
    second = _run(tmp_path, "Queen - Bohemian Rhapsody\nBlur - Song 2\n", mapping)

    assert second[: len(first)] == first, "existing days were disturbed"
    assert second == [1, 2]


def test_main_rerun_with_no_new_seeds_appends_nothing(tmp_path):
    mapping = {("Queen", "Bohemian Rhapsody"): _accepted(1, "Queen", "Bohemian Rhapsody", 1975)}
    text = "Queen - Bohemian Rhapsody\n"

    first = _run(tmp_path, text, mapping)
    second = _run(tmp_path, text, mapping)

    assert first == second == [1]


def test_refresh_never_appends_a_changed_deezer_id(tmp_path):
    """A drifted Deezer id must not strand a day on a track that is not stored.

    daily_order is append-only, so an id appended here could never be removed.
    """
    text = "Blur - Song 2\n"
    mapping = {("Blur", "Song 2"): _accepted(2, "Blur", "Song 2", 1997)}
    first = _run(tmp_path, text, mapping)
    assert first == [2]

    # Deezer's search ranking shifts and now returns a different id.
    mapping[("Blur", "Song 2")] = _accepted(999, "Blur", "Song 2", 1997)
    second = _run(tmp_path, text, mapping, refresh=True)

    assert second == [2], "refresh must not append a drifted id"

    tracks = json.loads((tmp_path / "tracks.json").read_text())
    ids = [t["deezer_id"] for t in tracks]
    assert set(second) <= set(ids), "daily_order references a track not in tracks.json"


def test_main_heals_a_track_recorded_without_its_order_entry(tmp_path):
    """Simulates a kill between the tracks.json and daily_order.json writes."""
    (tmp_path / "tracks.json").write_text(json.dumps([{
        "deezer_id": 7, "artist": "Blur", "title": "Song 2", "year": 1997,
        "sources": {"musicbrainz": 1997, "wikidata": 1997},
    }]))
    (tmp_path / "daily_order.json").write_text("[]")

    order = _run(tmp_path, "", {})

    assert order == [7], "an orphaned track must be given a day on the next run"


def test_main_runs_the_guard_before_every_daily_order_write(tmp_path, monkeypatch):
    """Pin that the guard is invoked, and invoked before the write.

    assert_append_only cannot fire in correct code — order is only ever
    appended to — so its value is as a tripwire for future changes. That makes
    it worth pinning that it actually runs, and runs before the write it
    protects. Deleting the call, or moving it after the write, must fail here.
    """
    import tools.build_tracks as bt

    events = []
    real_assert = bt.assert_append_only
    real_write = bt._write_json

    def spy_assert(existing, updated):
        events.append("guard")
        return real_assert(existing, updated)

    def spy_write(path, payload):
        if path.name == "daily_order.json":
            events.append("write")
        return real_write(path, payload)

    monkeypatch.setattr(bt, "assert_append_only", spy_assert)
    monkeypatch.setattr(bt, "_write_json", spy_write)

    mapping = {("Queen", "Bohemian Rhapsody"): _accepted(1, "Queen", "Bohemian Rhapsody", 1975)}
    _run(tmp_path, "Queen - Bohemian Rhapsody\n", mapping)

    assert "write" in events, "no daily_order write occurred, so nothing was proven"
    assert "guard" in events, "assert_append_only was never called"
    assert events.index("guard") < events.index("write"), \
        "daily_order was written before the append-only guard ran"
    assert events.count("guard") >= events.count("write"), \
        "some daily_order write was not preceded by its own guard"


def _rejected(reason):
    from tools.build_tracks import Evaluation
    return Evaluation("rejected", reason=reason)


def test_refresh_updates_a_changed_rejection_reason(tmp_path):
    """A stale reason would mislead curation triage in Task 13."""
    text = "Radiohead - Creep\n"
    mapping = {("Radiohead", "Creep"): _rejected("wd_missing")}
    _run(tmp_path, text, mapping)

    rejects = json.loads((tmp_path / "rejects.json").read_text())
    assert [r["reason"] for r in rejects] == ["wd_missing"]

    mapping[("Radiohead", "Creep")] = _rejected("year_conflict")
    _run(tmp_path, text, mapping, refresh=True)

    rejects = json.loads((tmp_path / "rejects.json").read_text())
    assert [r["reason"] for r in rejects] == ["year_conflict"], "stale reason kept"
    assert len(rejects) == 1, "refresh duplicated the reject entry"
