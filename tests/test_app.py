from datetime import date

import pytest

from app import create_app
from chronotune.deezer import PreviewUnavailable
from chronotune.store import Pool, Track

TRACKS = [
    Track(deezer_id=10, artist="Queen", title="Bohemian Rhapsody", year=1975),
    Track(deezer_id=20, artist="Nirvana", title="Smells Like Teen Spirit", year=1991),
]


def _client(resolve=None, today=date(2026, 1, 2), tracks=TRACKS, order=(10, 20)):
    app = create_app(
        pool=Pool(list(tracks), list(order)),
        resolve_preview=resolve or (lambda deezer_id: f"https://cdn/{deezer_id}.mp3"),
        today=lambda: today,
    )
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture
def client():
    return _client()


def test_daily_returns_the_track_for_today(client):
    body = client.get("/api/daily").get_json()

    assert body["deezer_id"] == 20
    assert body["puzzle_number"] == 2
    assert body["max_guesses"] == 6
    assert body["ladder"] == [1, 5, 10, 15, 20, 25]


def test_daily_never_leaks_the_answer(client):
    body = client.get("/api/daily").get_json()

    assert "year" not in body
    assert "title" not in body
    assert "artist" not in body


def test_audio_returns_a_resolved_url(client):
    assert client.get("/api/audio/10").get_json()["url"] == "https://cdn/10.mp3"


def test_audio_returns_503_when_unavailable():
    def broken(deezer_id):
        raise PreviewUnavailable("nope")

    response = _client(resolve=broken).get("/api/audio/10")

    assert response.status_code == 503
    assert "unavailable" in response.get_json()["error"].lower()


def test_audio_404s_for_a_track_outside_the_pool(client):
    assert client.get("/api/audio/999").status_code == 404


def test_wrong_guess_gives_direction_without_the_answer(client):
    body = client.post(
        "/api/guess", json={"deezer_id": 20, "guess": 1985, "guess_number": 1}
    ).get_json()

    assert body["result"] == "later"
    assert body["snippet_seconds"] == 5
    assert "answer" not in body


def test_correct_guess_reveals_the_track(client):
    body = client.post(
        "/api/guess", json={"deezer_id": 20, "guess": 1991, "guess_number": 1}
    ).get_json()

    assert body["result"] == "correct"
    assert body["answer"] == 1991
    assert body["artist"] == "Nirvana"


def test_final_wrong_guess_reveals_the_answer(client):
    body = client.post(
        "/api/guess", json={"deezer_id": 20, "guess": 1985, "guess_number": 6}
    ).get_json()

    assert body["result"] == "later"
    assert body["answer"] == 1991
    assert body["title"] == "Smells Like Teen Spirit"


@pytest.mark.parametrize("bad", ["abc", None, 12.5, True, [1991]])
def test_non_integer_guess_is_rejected(client, bad):
    response = client.post(
        "/api/guess", json={"deezer_id": 20, "guess": bad, "guess_number": 1}
    )

    assert response.status_code == 400


@pytest.mark.parametrize("bad", [1200, 2500, -5])
def test_out_of_range_guess_is_rejected(client, bad):
    response = client.post(
        "/api/guess", json={"deezer_id": 20, "guess": bad, "guess_number": 1}
    )

    assert response.status_code == 400


@pytest.mark.parametrize("bad", [0, 7, "x", None])
def test_out_of_range_guess_number_is_rejected(client, bad):
    response = client.post(
        "/api/guess", json={"deezer_id": 20, "guess": 1991, "guess_number": bad}
    )

    assert response.status_code == 400


def test_guess_for_an_unknown_track_404s(client):
    response = client.post(
        "/api/guess", json={"deezer_id": 999, "guess": 1991, "guess_number": 1}
    )

    assert response.status_code == 404


def test_guess_with_no_body_is_rejected_not_crashed(client):
    assert client.post("/api/guess").status_code in (400, 404)


def test_infinite_returns_an_unseen_track(client):
    assert client.post("/api/infinite", json={"seen": [10]}).get_json()["deezer_id"] == 20


def test_infinite_409s_when_the_pool_is_exhausted(client):
    assert client.post("/api/infinite", json={"seen": [10, 20]}).status_code == 409


def test_infinite_rejects_a_non_list_seen(client):
    assert client.post("/api/infinite", json={"seen": "10"}).status_code == 400


def test_infinite_tolerates_a_missing_body(client):
    assert client.post("/api/infinite").status_code == 200


def test_index_page_renders(client):
    assert client.get("/").status_code == 200
