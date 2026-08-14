import pytest

from chronotune.deezer import PreviewUnavailable, resolve_preview_url


def test_returns_the_preview_url():
    payload = {"id": 42, "preview": "https://cdn/x.mp3?hdnea=exp=1"}

    assert resolve_preview_url(42, fetch_json=lambda url: payload) == payload["preview"]


def test_retries_once_before_giving_up():
    attempts = []

    def flaky(url):
        attempts.append(url)
        if len(attempts) == 1:
            raise OSError("connection reset")
        return {"preview": "https://cdn/x.mp3"}

    assert resolve_preview_url(42, fetch_json=flaky) == "https://cdn/x.mp3"
    assert len(attempts) == 2


def test_raises_after_exhausting_attempts():
    def always_fails(url):
        raise OSError("connection reset")

    with pytest.raises(PreviewUnavailable):
        resolve_preview_url(42, fetch_json=always_fails)


def test_raises_when_the_track_has_no_preview():
    with pytest.raises(PreviewUnavailable):
        resolve_preview_url(42, fetch_json=lambda url: {"preview": ""})


def test_raises_when_deezer_reports_an_error():
    payload = {"error": {"type": "DataException", "message": "no data"}}

    with pytest.raises(PreviewUnavailable):
        resolve_preview_url(42, fetch_json=lambda url: payload)


def test_does_not_retry_forever_when_attempts_is_one():
    attempts = []

    def counting(url):
        attempts.append(url)
        raise OSError("down")

    with pytest.raises(PreviewUnavailable):
        resolve_preview_url(42, fetch_json=counting, attempts=1)

    assert len(attempts) == 1


def test_the_original_cause_is_chained_for_debugging():
    """A bare PreviewUnavailable with no __cause__ hides why it failed."""
    original = OSError("connection reset")

    def always_fails(url):
        raise original

    with pytest.raises(PreviewUnavailable) as excinfo:
        resolve_preview_url(42, fetch_json=always_fails)

    assert excinfo.value.__cause__ is original
