from tools.sources.wikidata import build_query, first_publication_year


def _bindings(*dates):
    return {
        "results": {
            "bindings": [
                {"song": {"value": f"http://wd/Q{i}"}, "first": {"value": d}}
                for i, d in enumerate(dates)
            ]
        }
    }


def test_returns_earliest_year():
    payload = _bindings("1997-03-17T00:00:00Z", "2001-01-01T00:00:00Z")

    assert first_publication_year("Daft Punk", "Around the World",
                                  fetch_json=lambda url: payload) == 1997


def test_returns_none_when_wikidata_has_nothing():
    """Absence is the safe failure mode: abstain rather than guess."""
    assert first_publication_year("Rick Astley", "Never Gonna Give You Up",
                                  fetch_json=lambda url: _bindings()) is None


def test_ignores_malformed_dates():
    payload = _bindings("not-a-date", "1985-08-05T00:00:00Z")

    assert first_publication_year("Kate Bush", "Running Up That Hill",
                                  fetch_json=lambda url: payload) == 1985


def test_query_escapes_double_quotes_in_titles():
    """An unescaped quote would produce invalid SPARQL and a 400."""
    query = build_query('Weird "Al" Yankovic', 'Eat It')

    assert '\\"Al\\"' in query
