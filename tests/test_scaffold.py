"""Proves the package layout and pytest config are wired correctly."""


def test_packages_are_importable():
    import chronotune
    import tools.sources

    assert chronotune is not None
    assert tools.sources is not None


def test_tools_does_not_import_chronotune():
    """The builder and the app share only data/*.json. Guard that boundary."""
    from pathlib import Path

    for path in Path("tools").rglob("*.py"):
        source = path.read_text()
        assert "import chronotune" not in source, f"{path} imports chronotune"
        assert "from chronotune" not in source, f"{path} imports chronotune"


def test_chronotune_does_not_import_tools_or_call_curation_apis():
    """The reverse direction of the same boundary.

    The app must never import the builder, and must never reach MusicBrainz or
    Wikidata. Those are build-time concerns. Deezer is exempt: the app calls it
    at runtime to resolve preview URLs.
    """
    from pathlib import Path

    forbidden = ("import tools", "from tools", "musicbrainz", "wikidata")
    for path in Path("chronotune").rglob("*.py"):
        source = path.read_text().lower()
        for needle in forbidden:
            assert needle not in source, f"{path} references {needle}"
