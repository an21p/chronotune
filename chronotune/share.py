"""Wordle-style share grid.

Never includes any year — a shared result must not spoil the puzzle.
"""

from __future__ import annotations

from chronotune.game import MAX_GUESSES, UNUSED, proximity_band


def share_text(puzzle_number: int, guesses: list[int], answer: int) -> str:
    bands = [proximity_band(guess, answer) for guess in guesses]
    padding = [UNUSED] * (MAX_GUESSES - len(bands))
    grid = "".join(bands + padding)

    solved = answer in guesses
    if solved:
        summary = f"Solved in {len(guesses)} · " + "🔊" * len(guesses)
    else:
        summary = "X/6"

    return f"CHRONOTUNE #{puzzle_number}\n{grid}\n{summary}"
