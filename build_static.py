"""Build the serverless bundle deployed to GitHub Pages.

Emits a directory that can be dropped at any path on any static host. Every
asset reference is relative, so the same output works at the site root and at
/chronotune/ with no base-path substitution.

    python build_static.py --out build

It sits beside app.py rather than in tools/ on purpose. tools/ is the offline
curation builder, walled off from the runtime and sharing only data/*.json;
this is a packaging step *for* the runtime and has to read its rules, so it
belongs on this side of that wall.

What it produces:

    index.html   the Flask template with its url_for() calls resolved
    app.js       unchanged
    style.css    unchanged
    vault.js     the answer decoder
    api-static.js the serverless backend
    pool.json    sealed answers plus the rules read out of the Python modules

The rules in pool.json are read from chronotune.game and chronotune.puzzle
rather than restated, so the browser cannot disagree with the server about the
ladder, the guess ceiling, the epoch or the proximity bands.

Only the track pool is transformed. Everything else is a copy, which keeps the
Flask app and the static build the same application rather than two that drift.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

from chronotune import puzzle, vault
from chronotune.game import FAR, MAX_GUESSES, PROXIMITY_BANDS, SNIPPET_LADDER
from chronotune.store import load_pool

ROOT = Path(__file__).resolve().parent

# Copied verbatim. api-server.js is deliberately absent, because the static build
# would only be able to 404 against it.
STATIC_ASSETS = ("app.js", "style.css", "vault.js", "api-static.js")

URL_FOR = re.compile(r"""\{\{\s*url_for\('static',\s*filename='([^']+)'\)\s*\}\}""")

SERVER_BACKEND = '<script src="api-server.js"></script>'
STATIC_BACKEND = (
    '<script src="vault.js"></script>\n'
    '  <script src="api-static.js"></script>'
)


def build_pool_json(tracks_path: Path, order_path: Path) -> dict:
    pool = load_pool(tracks_path, order_path)

    return {
        "epoch": puzzle.EPOCH.isoformat(),
        "ladder": list(SNIPPET_LADDER),
        "max_guesses": MAX_GUESSES,
        "proximity_bands": [list(band) for band in PROXIMITY_BANDS],
        "far_band": FAR,
        "daily_order": list(pool.daily_order),
        "tracks": [
            {
                "id": track.deezer_id,
                "sealed": vault.seal(
                    track.deezer_id,
                    {
                        "year": track.year,
                        "artist": track.artist,
                        "title": track.title,
                    },
                ),
            }
            for track in pool.tracks
        ],
    }


def render_index(template: str) -> str:
    """Resolve url_for() to relative paths and swap in the static backend."""
    html = URL_FOR.sub(lambda match: match.group(1), template)

    if SERVER_BACKEND not in html:
        # The template moved out from under us. Failing here beats shipping a
        # build whose only backend is one that 404s.
        raise SystemExit(
            f"expected {SERVER_BACKEND!r} in templates/index.html; "
            "update tools/build_static.py to match"
        )
    return html.replace(SERVER_BACKEND, STATIC_BACKEND)


def build(out_dir: Path, root: Path = ROOT) -> Path:
    pool_json = build_pool_json(root / "data/tracks.json", root / "data/daily_order.json")
    index = render_index((root / "templates/index.html").read_text(encoding="utf-8"))

    # Only after both succeed, so a failed build never leaves a half-written
    # directory behind for a deploy to pick up.
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    (out_dir / "index.html").write_text(index, encoding="utf-8")
    (out_dir / "pool.json").write_text(
        json.dumps(pool_json, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    for asset in STATIC_ASSETS:
        shutil.copy2(root / "static" / asset, out_dir / asset)

    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="build", help="output directory (default: build)")
    args = parser.parse_args()

    out = build(Path(args.out).resolve())
    tracks = len(json.loads((out / "pool.json").read_text())["tracks"])
    print(f"built {out}: {tracks} tracks sealed")


if __name__ == "__main__":
    main()
