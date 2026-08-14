"""The static build.

Two things matter here. The bundle must be self-contained and path-agnostic,
because it is deployed under /chronotune/ on a host that is not its origin. And
the rules baked into pool.json must come from the Python modules, so the
browser cannot quietly disagree with the server about how the game works.
"""

from __future__ import annotations

import json

import pytest

import build_static
from chronotune import puzzle, vault
from chronotune.game import FAR, MAX_GUESSES, PROXIMITY_BANDS, SNIPPET_LADDER


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> "Path":
    return build_static.build(tmp_path_factory.mktemp("build") / "out")


@pytest.fixture(scope="module")
def pool_json(built) -> dict:
    return json.loads((built / "pool.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def index(built) -> str:
    return (built / "index.html").read_text(encoding="utf-8")


class TestBundle:
    def test_emits_every_asset(self, built) -> None:
        expected = {"index.html", "pool.json", *build_static.STATIC_ASSETS}
        assert {p.name for p in built.iterdir()} == expected

    def test_omits_the_flask_backend(self, built) -> None:
        """api-server.js talks to /api/* routes that do not exist here."""
        assert not (built / "api-server.js").exists()

    def test_replaces_a_previous_build(self, tmp_path) -> None:
        out = tmp_path / "out"
        out.mkdir()
        (out / "stale.js").write_text("old")
        build_static.build(out)
        assert not (out / "stale.js").exists()

    def test_copies_app_js_unchanged(self, built) -> None:
        source = (build_static.ROOT / "static" / "app.js").read_text(encoding="utf-8")
        assert (built / "app.js").read_text(encoding="utf-8") == source


class TestIndexHtml:
    def test_resolves_url_for(self, index: str) -> None:
        assert "url_for" not in index

    def test_asset_references_are_relative(self, index: str) -> None:
        """The bundle is served from /chronotune/, not the site root. A leading
        slash would send every asset request to the portfolio instead."""
        for asset in ("style.css", "app.js", "vault.js", "api-static.js"):
            assert f'"{asset}"' in index, f"{asset} is not referenced relatively"
            assert f'"/{asset}"' not in index

    def test_scripts_load_in_dependency_order(self, index: str) -> None:
        """vault.js defines unseal, api-static.js uses it to define
        window.ChronotuneAPI, and app.js reads that at startup. Matching on the
        script tags rather than the bare filenames — the surrounding comment
        mentions app.js too."""
        order = [
            index.index(f'<script src="{name}">')
            for name in ("vault.js", "api-static.js", "app.js")
        ]
        assert order == sorted(order)

    def test_fails_loudly_if_the_template_stops_matching(self) -> None:
        """Silently emitting a build with no backend would produce a page that
        loads and then does nothing."""
        with pytest.raises(SystemExit):
            build_static.render_index("<html><body>no backend here</body></html>")


class TestPoolJson:
    def test_carries_the_rules_from_python(self, pool_json: dict) -> None:
        assert pool_json["ladder"] == list(SNIPPET_LADDER)
        assert pool_json["max_guesses"] == MAX_GUESSES
        assert pool_json["proximity_bands"] == [list(b) for b in PROXIMITY_BANDS]
        assert pool_json["far_band"] == FAR
        assert pool_json["epoch"] == puzzle.EPOCH.isoformat()

    def test_daily_order_is_preserved_exactly(self, pool_json: dict) -> None:
        """Order fixes which track each calendar day serves. Reordering it
        would change songs players already played and invalidate shared grids."""
        source = json.loads((build_static.ROOT / "data/daily_order.json").read_text())
        assert pool_json["daily_order"] == source

    def test_every_daily_order_entry_has_a_track(self, pool_json: dict) -> None:
        ids = {track["id"] for track in pool_json["tracks"]}
        assert set(pool_json["daily_order"]) <= ids

    def test_every_track_unseals_to_its_answer(self, pool_json: dict) -> None:
        source = json.loads((build_static.ROOT / "data/tracks.json").read_text())
        expected = {t["deezer_id"]: t for t in source}

        for entry in pool_json["tracks"]:
            answer = vault.unseal(entry["id"], entry["sealed"])
            original = expected[entry["id"]]
            assert answer == {
                "year": original["year"],
                "artist": original["artist"],
                "title": original["title"],
            }

    def test_ships_no_plaintext_answers(self, built) -> None:
        """The point of sealing. A year or title left readable here is one
        Ctrl-F away from spoiling the puzzle."""
        raw = (built / "pool.json").read_text(encoding="utf-8")
        source = json.loads((build_static.ROOT / "data/tracks.json").read_text())

        for track in source:
            assert track["title"] not in raw, f"{track['title']} is in the clear"
            assert track["artist"] not in raw, f"{track['artist']} is in the clear"

    def test_omits_the_curation_metadata(self, pool_json: dict) -> None:
        """tracks.json carries per-source year votes from the builder. They are
        build-time evidence, and each one is a plaintext copy of the answer."""
        assert all(set(t) == {"id", "sealed"} for t in pool_json["tracks"])
