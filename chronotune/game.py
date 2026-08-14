"""Core game rules. Pure functions, no I/O."""

from __future__ import annotations

SNIPPET_LADDER: tuple[int, ...] = (1, 2, 4, 7, 11, 16)
MAX_GUESSES: int = len(SNIPPET_LADDER)

CORRECT = "🟩"
CLOSE = "🟨"
NEAR = "🟧"
FAR = "🟥"
UNUSED = "⬜"


def snippet_seconds(wrong_guesses: int) -> int:
    """Audio length unlocked after this many wrong guesses."""
    if wrong_guesses < 0:
        raise ValueError("wrong_guesses must not be negative")
    index = min(wrong_guesses, len(SNIPPET_LADDER) - 1)
    return SNIPPET_LADDER[index]


def evaluate_guess(guess: int, answer: int) -> str:
    """Directional feedback for a single guess."""
    if guess == answer:
        return "correct"
    return "later" if guess < answer else "earlier"


def proximity_band(guess: int, answer: int) -> str:
    """Emoji band for the share grid. Boundaries are inclusive."""
    distance = abs(guess - answer)
    if distance == 0:
        return CORRECT
    if distance <= 2:
        return CLOSE
    if distance <= 10:
        return NEAR
    return FAR


def is_round_over(guesses: list[int], answer: int) -> bool:
    return answer in guesses or len(guesses) >= MAX_GUESSES
