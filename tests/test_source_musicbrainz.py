from tools.sources.musicbrainz import first_release_year


def _payload(*dates):
    return {
        "release-groups": [
            {"title": "x", "first-release-date": d} for d in dates if d is not None
        ]
    }


def test_returns_earliest_year_across_release_groups():
    payload = _payload("1997-03-17", "1996-01-20", "2004-11-29")

    assert first_release_year("Daft Punk", "Around the World",
                              fetch_json=lambda url: payload, sleep=lambda s: None) == 1996


def test_handles_year_only_dates():
    payload = _payload("1991")

    assert first_release_year("Nirvana", "Smells Like Teen Spirit",
                              fetch_json=lambda url: payload, sleep=lambda s: None) == 1991


def test_returns_none_when_no_release_groups():
    assert first_release_year("Eminem", "Lose Yourself",
                              fetch_json=lambda url: {"release-groups": []},
                              sleep=lambda s: None) is None


def test_ignores_release_groups_missing_a_date():
    payload = {"release-groups": [{"title": "x"}, {"title": "y", "first-release-date": "2003"}]}

    assert first_release_year("Outkast", "Hey Ya!",
                              fetch_json=lambda url: payload, sleep=lambda s: None) == 2003


def test_returns_none_on_empty_date_strings():
    payload = {"release-groups": [{"title": "x", "first-release-date": ""}]}

    assert first_release_year("A", "B", fetch_json=lambda url: payload,
                              sleep=lambda s: None) is None


def test_rate_limit_sleep_is_called():
    calls = []
    first_release_year("A", "B", fetch_json=lambda url: _payload("2000"),
                       sleep=calls.append)

    assert calls == [1.1], "MusicBrainz requires 1 req/s; must sleep after each call"
