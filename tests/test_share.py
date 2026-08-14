import pytest

from chronotune.share import share_text


def test_solved_round_grid_and_summary():
    text = share_text(142, [1980, 1998, 1991], 1991)

    assert text == "CHRONOTUNE #142\n🟥🟧🟩⬜⬜⬜\nSolved in 3 · 🔊🔊🔊"


def test_unsolved_round_shows_an_x():
    text = share_text(7, [1960, 1965, 1970, 1975, 1980, 1985], 2020)

    assert text.startswith("CHRONOTUNE #7\n")
    assert text.endswith("X/6")
    assert "⬜" not in text


def test_grid_always_has_six_cells():
    """Each band emoji is a single codepoint, so the grid is exactly 6 chars."""
    grid = share_text(1, [1991], 1991).splitlines()[1]

    assert len(grid) == 6
    assert grid == "🟩⬜⬜⬜⬜⬜"


@pytest.mark.parametrize(
    "guesses,answer",
    [([1980, 1991], 1991), ([1960, 1965, 1970, 1975, 1980, 1985], 2020), ([], 1999)],
)
def test_no_year_leaks_into_the_share_text(guesses, answer):
    """Sharing must not spoil the puzzle for anyone reading it.

    Asserts the property directly rather than enumerating two literals, so a
    future format change that interpolated any year would fail here.
    """
    text = share_text(142, guesses, answer)

    for year in list(guesses) + [answer]:
        assert str(year) not in text


def test_grid_stays_six_cells_when_given_too_many_guesses():
    """[x] * negative is [] in Python, so an unclipped pad would overflow."""
    grid = share_text(1, [1960, 1961, 1962, 1963, 1964, 1965, 1966], 1991).splitlines()[1]

    assert len(grid) == 6


def test_empty_guess_list_renders_an_untouched_grid():
    """Pinned so the Task 12 JavaScript port has a defined behaviour to match."""
    text = share_text(9, [], 1991)

    assert text == "CHRONOTUNE #9\n⬜⬜⬜⬜⬜⬜\nX/6"


def test_speaker_count_matches_guesses_used():
    assert "🔊🔊" in share_text(3, [1985, 1991], 1991)
    assert share_text(3, [1991], 1991).count("🔊") == 1
