"""Chronotune Flask app.

Stateless: player progress lives in localStorage. The answer year is withheld
until the round is over so it cannot be read from the network tab.
"""

from __future__ import annotations

from datetime import date

from flask import Flask, jsonify, render_template, request

from chronotune import puzzle
from chronotune.deezer import PreviewUnavailable, resolve_preview_url
from chronotune.game import MAX_GUESSES, SNIPPET_LADDER, evaluate_guess, proximity_band
from chronotune.store import load_pool

MIN_YEAR = 1900
MAX_YEAR = 2100


def _is_int(value) -> bool:
    """Reject bools: `isinstance(True, int)` is True in Python, and a JSON
    `true` arriving as a guess should be a 400, not the year 1."""
    return isinstance(value, int) and not isinstance(value, bool)


def create_app(pool=None, resolve_preview=None, today=None) -> Flask:
    app = Flask(__name__)

    # Loaded once at startup so bad data fails loudly here, not mid-request.
    app.pool = pool if pool is not None else load_pool(
        "data/tracks.json", "data/daily_order.json"
    )
    resolve = resolve_preview or resolve_preview_url
    now = today or date.today

    def _track_or_none(deezer_id):
        if not _is_int(deezer_id):
            return None
        try:
            return app.pool.by_id(deezer_id)
        except KeyError:
            return None

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/daily")
    def daily():
        return jsonify(
            deezer_id=puzzle.daily_track_id(app.pool, now()),
            puzzle_number=puzzle.puzzle_number(now()),
            max_guesses=MAX_GUESSES,
            ladder=list(SNIPPET_LADDER),
        )

    @app.post("/api/infinite")
    def infinite():
        seen = (request.get_json(silent=True) or {}).get("seen", [])
        if not isinstance(seen, list):
            return jsonify(error="seen must be a list"), 400

        track_id = puzzle.pick_unseen_track_id(app.pool, seen)
        if track_id is None:
            return jsonify(error="You have played every track in the pool."), 409

        return jsonify(
            deezer_id=track_id, max_guesses=MAX_GUESSES, ladder=list(SNIPPET_LADDER)
        )

    @app.get("/api/audio/<int:deezer_id>")
    def audio(deezer_id):
        if _track_or_none(deezer_id) is None:
            return jsonify(error="unknown track"), 404
        try:
            return jsonify(url=resolve(deezer_id))
        except PreviewUnavailable:
            return jsonify(error="Audio unavailable. Try again."), 503

    @app.post("/api/guess")
    def guess():
        body = request.get_json(silent=True) or {}

        track = _track_or_none(body.get("deezer_id"))
        if track is None:
            return jsonify(error="unknown track"), 404

        raw_guess = body.get("guess")
        if not _is_int(raw_guess):
            return jsonify(error="guess must be an integer year"), 400
        if not MIN_YEAR <= raw_guess <= MAX_YEAR:
            return jsonify(error=f"guess must be between {MIN_YEAR} and {MAX_YEAR}"), 400

        guess_number = body.get("guess_number", 1)
        if not _is_int(guess_number) or not 1 <= guess_number <= MAX_GUESSES:
            return jsonify(error="guess_number out of range"), 400

        result = evaluate_guess(raw_guess, track.year)
        over = result == "correct" or guess_number >= MAX_GUESSES

        payload = {
            "result": result,
            "band": proximity_band(raw_guess, track.year),
            "snippet_seconds": SNIPPET_LADDER[min(guess_number, MAX_GUESSES - 1)],
        }
        if over:
            payload.update(answer=track.year, artist=track.artist, title=track.title)

        return jsonify(payload)

    return app


if __name__ == "__main__":
    create_app().run(debug=True, port=5000)
