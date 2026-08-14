import pytest

from tools.sources.deezer import DeezerMatch, is_variant, normalise, search_track


def test_normalise_strips_case_punctuation_and_accents():
    assert normalise("Hey Ya!") == "hey ya"
    assert normalise("  The   Killers ") == "the killers"
    assert normalise("Beyoncé") == "beyonce"


@pytest.mark.parametrize(
    "title",
    [
        "Bohemian Rhapsody (Live At Wembley Stadium / July 1986)",
        "Bohemian Rhapsody (Live Aid)",
        "Take On Me (2017 Acoustic)",
        "Song 2 - Radio Edit",
        "Dreams (2004 Remaster)",
        "Creep (Acoustic Version)",
        "Rehab - Hot Chip Remix",
    ],
)
def test_is_variant_rejects_alternate_recordings(title):
    assert is_variant(title) is True


@pytest.mark.parametrize(
    "title",
    ["Bohemian Rhapsody", "Hey Ya!", "Somebody That I Used to Know", "Mr. Brightside"],
)
def test_is_variant_accepts_plain_titles(title):
    assert is_variant(title) is False


def _payload(*tracks):
    return {"data": list(tracks)}


def _track(track_id, title, artist, preview="https://cdn/x.mp3"):
    return {
        "id": track_id,
        "title": title,
        "preview": preview,
        "artist": {"name": artist},
    }


def test_search_track_skips_variants_and_returns_first_clean_match():
    payload = _payload(
        _track(1, "Bohemian Rhapsody (Live Aid)", "Queen"),
        _track(2, "Bohemian Rhapsody", "Queen"),
    )
    match = search_track("Queen", "Bohemian Rhapsody", fetch_json=lambda url: payload)

    assert match == DeezerMatch(deezer_id=2, artist="Queen", title="Bohemian Rhapsody")


def test_search_track_rejects_tracks_without_a_preview():
    payload = _payload(_track(3, "Bohemian Rhapsody", "Queen", preview=""))

    assert search_track("Queen", "Bohemian Rhapsody", fetch_json=lambda url: payload) is None


def test_search_track_rejects_a_different_artist():
    payload = _payload(_track(4, "Bohemian Rhapsody", "The Muppets"))

    assert search_track("Queen", "Bohemian Rhapsody", fetch_json=lambda url: payload) is None


def test_search_track_rejects_a_different_title():
    payload = _payload(_track(5, "Under Pressure", "Queen"))

    assert search_track("Queen", "Bohemian Rhapsody", fetch_json=lambda url: payload) is None


def test_search_track_returns_none_on_empty_results():
    assert search_track("Nobody", "Nothing", fetch_json=lambda url: {"data": []}) is None


def test_variant_seed_does_not_match_an_alternate_recording():
    """is_variant's real job: a variant-shaped SEED must not match.

    Exact title equality alone would accept this, because the seed and the
    Deezer title agree. Only the variant check rejects it.
    """
    payload = _payload(_track(9, "Take On Me (Live)", "a-ha"))

    assert search_track("a-ha", "Take On Me (Live)", fetch_json=lambda url: payload) is None


def test_search_track_returns_none_when_every_result_is_a_variant():
    payload = _payload(
        _track(1, "Bohemian Rhapsody (Live Aid)", "Queen"),
        _track(2, "Bohemian Rhapsody (2011 Remaster)", "Queen"),
    )

    assert search_track("Queen", "Bohemian Rhapsody", fetch_json=lambda url: payload) is None


def test_search_track_survives_a_null_artist_field():
    payload = {"data": [{"id": 7, "title": "X", "preview": "https://cdn/x.mp3", "artist": None}]}

    assert search_track("Queen", "X", fetch_json=lambda url: payload) is None
