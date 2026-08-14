import pytest

from chronotune.game import (
    MAX_GUESSES,
    SNIPPET_LADDER,
    evaluate_guess,
    is_round_over,
    proximity_band,
    snippet_seconds,
)


def test_ladder_matches_the_spec():
    assert SNIPPET_LADDER == (1, 5, 10, 15, 20, 25)
    assert MAX_GUESSES == 6
    assert len(SNIPPET_LADDER) == MAX_GUESSES


@pytest.mark.parametrize(
    "wrong_guesses,expected",
    [(0, 1), (1, 5), (2, 10), (3, 15), (4, 20), (5, 25)],
)
def test_snippet_grows_with_each_wrong_guess(wrong_guesses, expected):
    assert snippet_seconds(wrong_guesses) == expected


def test_snippet_caps_at_the_final_rung():
    assert snippet_seconds(6) == 25
    assert snippet_seconds(99) == 25


def test_negative_guess_count_is_rejected():
    with pytest.raises(ValueError):
        snippet_seconds(-1)


def test_evaluate_guess_directions():
    assert evaluate_guess(1991, 1991) == "correct"
    assert evaluate_guess(1985, 1991) == "later"
    assert evaluate_guess(1998, 1991) == "earlier"


@pytest.mark.parametrize(
    "guess,answer,band",
    [
        (1991, 1991, "🟩"),
        (1993, 1991, "🟨"),
        (1989, 1991, "🟨"),
        (2001, 1991, "🟧"),
        (1981, 1991, "🟧"),
        (2002, 1991, "🟥"),
        (1900, 1991, "🟥"),
    ],
)
def test_proximity_bands(guess, answer, band):
    assert proximity_band(guess, answer) == band


def test_band_boundaries_are_inclusive():
    assert proximity_band(1993, 1991) == "🟨"  # exactly 2 off
    assert proximity_band(1994, 1991) == "🟧"  # 3 off
    assert proximity_band(2001, 1991) == "🟧"  # exactly 10 off
    assert proximity_band(2002, 1991) == "🟥"  # 11 off


def test_round_ends_on_a_correct_guess():
    assert is_round_over([1985, 1991], 1991) is True


def test_round_ends_after_six_wrong_guesses():
    assert is_round_over([1, 2, 3, 4, 5, 6], 1991) is True


def test_round_continues_while_guesses_remain():
    assert is_round_over([1985, 1998], 1991) is False
    assert is_round_over([], 1991) is False
