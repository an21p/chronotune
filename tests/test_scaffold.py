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
