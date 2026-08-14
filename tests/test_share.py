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


def test_no_answer_year_leaks_into_the_share_text():
    """Sharing must not spoil the answer for anyone reading it."""
    text = share_text(142, [1980, 1991], 1991)

    assert "1991" not in text
    assert "1980" not in text


def test_speaker_count_matches_guesses_used():
    assert "🔊🔊" in share_text(3, [1985, 1991], 1991)
    assert share_text(3, [1991], 1991).count("🔊") == 1
