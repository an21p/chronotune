"""Core game rules. Pure functions, no I/O."""

from __future__ import annotations

# One second to open, then +4, then +5 for every guess after that. The last
# rung stays inside the 30s preview.
SNIPPET_LADDER: tuple[int, ...] = (1, 5, 10, 15, 20, 25)
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


# (max inclusive distance, emoji), nearest first. A table rather than an if
# ladder so the static build can ship the exact same boundaries to the browser
# instead of restating them in JavaScript and drifting.
PROXIMITY_BANDS: tuple[tuple[int, str], ...] = ((0, CORRECT), (2, CLOSE), (10, NEAR))


def proximity_band(guess: int, answer: int) -> str:
    """Emoji band for the share grid. Boundaries are inclusive."""
    distance = abs(guess - answer)
    for limit, band in PROXIMITY_BANDS:
        if distance <= limit:
            return band
    return FAR


def is_round_over(guesses: list[int], answer: int) -> bool:
    return answer in guesses or len(guesses) >= MAX_GUESSES
