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


def test_append_only_regression_on_frozen_order():
    """A frozen earlier order must survive an append byte-identically."""
    frozen = [101, 102, 103, 104, 105]
    updated = frozen + [106, 107]

    assert_append_only(frozen, updated)
    assert updated[: len(frozen)] == frozen
