"""Wordle-style share grid.

Never includes any year — a shared result must not spoil the puzzle.
"""

from __future__ import annotations

from chronotune.game import MAX_GUESSES, UNUSED, proximity_band

# Trailing the grid, so a pasted result is playable by whoever reads it. Last
# line rather than first: chat clients unfurl the final link, and the grid is
# what should be read before the preview card.
PLAY_URL = "https://an21p.github.io/chronotune/"


def share_text(puzzle_number: int, guesses: list[int], answer: int) -> str:
    # Clip before padding. With more than MAX_GUESSES guesses the padding
    # multiplier goes negative, and Python evaluates [x] * -1 to [] rather
    # than raising — which would emit a grid LONGER than MAX_GUESSES cells.
    # Rendering never crashes the end-of-round screen; is_round_over is the
    # enforcement point for the guess count.
    bands = [proximity_band(guess, answer) for guess in guesses][:MAX_GUESSES]
    padding = [UNUSED] * (MAX_GUESSES - len(bands))
    grid = "".join(bands + padding)

    solved = answer in guesses
    if solved:
        summary = f"Solved in {len(guesses)} · " + "🔊" * len(guesses)
    else:
        summary = "X/6"

    return f"CHRONOTUNE #{puzzle_number}\n{grid}\n{summary}\n{PLAY_URL}"
