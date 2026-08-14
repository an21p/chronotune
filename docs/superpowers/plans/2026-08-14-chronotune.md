# Chronotune Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Flask prototype of a daily music game where a growing audio snippet plays and the player guesses the track's release year, plus an infinite mode and a Wordle-style share grid.

**Architecture:** Two independent halves joined by a JSON contract. An offline builder (`tools/`) curates a track pool by cross-checking Deezer, MusicBrainz and Wikidata, writing `data/tracks.json` and an append-only `data/daily_order.json`. A stateless Flask app (`chronotune/`) serves puzzles from those files and resolves expiring Deezer preview URLs per request. No database; player progress lives in `localStorage`.

**Tech Stack:** Python 3.14, Flask, pytest. Standard library `urllib` for all HTTP (no `requests` dependency). Vanilla JS with the Web Audio API on the frontend — no framework, no build step.

## Global Constraints

- **Python 3.14.6**, in a project-local `.venv`. Neither Flask nor pytest is currently installed.
- **`tools/` must never import from `chronotune/`, and `chronotune/` must never import from `tools/` or call MusicBrainz/Wikidata.** `data/*.json` is the only contract between them.
- **No network access in the test suite.** Every network-touching function takes an injectable `fetch_json` parameter defaulting to the real implementation; tests pass fixtures.
- **MusicBrainz rate limit: 1 request/second**, with a descriptive User-Agent identifying the app and a contact address. This is their published rule, not a suggestion.
- **User-Agent for MusicBrainz and Wikidata:** `Chronotune/0.1 (pishias92@gmail.com)`
- **Preview URLs expire (~7h) and must never be persisted** — resolve per request, store only `deezer_id`.
- **Deezer's `release_date` gets no vote on the year.** Year consensus is MusicBrainz == Wikidata only.
- **`data/daily_order.json` is append-only**, enforced by a pre-write prefix assertion, a startup validation, and a regression test.
- **Snippet ladder:** `(1, 2, 4, 7, 11, 16)` seconds. **Max guesses: 6.**
- **Proximity bands:** 🟩 correct · 🟨 within 2 years · 🟧 within 10 years · 🟥 more than 10 · ⬜ guess unused.

---

## File Structure

| File | Responsibility |
|---|---|
| `tools/sources/deezer.py` | Loose search, variant rejection, fuzzy match → track ID + preview availability |
| `tools/sources/musicbrainz.py` | Release-group `first-release-date` → year |
| `tools/sources/wikidata.py` | SPARQL earliest `P577` → year |
| `tools/build_tracks.py` | Consensus rule, rejects, caching, incremental reruns, append-only guard |
| `chronotune/store.py` | Load + validate `tracks.json` and `daily_order.json` |
| `chronotune/game.py` | Snippet ladder, guess evaluation, proximity bands |
| `chronotune/share.py` | Emoji share grid |
| `chronotune/puzzle.py` | Date → daily track; random unseen → infinite track |
| `chronotune/deezer.py` | Runtime preview URL resolution with retry |
| `app.py` | Flask routes, startup validation, error mapping |
| `templates/index.html`, `static/` | Web Audio player, guess UI, localStorage, share button |

Tasks 2–4 (the three sources) are mutually independent and may be built in any order. Tasks 6–9 (`store`, `game`, `share`, `puzzle`) are pure logic and depend only on Task 1.

---

### Task 1: Project scaffold and green test suite

**Files:**
- Create: `.venv/` (via command), `requirements.txt`, `pytest.ini`, `chronotune/__init__.py`, `tools/__init__.py`, `tools/sources/__init__.py`, `tests/__init__.py`, `tests/test_scaffold.py`

**Interfaces:**
- Consumes: nothing
- Produces: a working `.venv` with Flask and pytest, and a `pytest` command that exits 0

- [ ] **Step 1: Create the virtual environment and install dependencies**

```bash
cd /Users/pishias/code/chronotune
python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet flask pytest
.venv/bin/pip freeze | grep -iE '^(flask|pytest)' > requirements.txt
cat requirements.txt
```

Expected: `requirements.txt` lists Flask and pytest with pinned versions.

- [ ] **Step 2: Create package directories and config**

```bash
mkdir -p chronotune tools/sources tests data templates static
touch chronotune/__init__.py tools/__init__.py tools/sources/__init__.py tests/__init__.py
```

Write `pytest.ini`:

```ini
[pytest]
testpaths = tests
pythonpath = .
addopts = -v
```

The `pythonpath = .` line lets tests import `chronotune` and `tools` without installing the project as a package.

- [ ] **Step 3: Write a scaffold test that proves imports work**

Write `tests/test_scaffold.py`:

```python
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
    Wikidata — those are build-time concerns. Deezer is exempt: the app calls it
    at runtime to resolve preview URLs.
    """
    from pathlib import Path

    forbidden = ("import tools", "from tools", "musicbrainz", "wikidata")
    for path in Path("chronotune").rglob("*.py"):
        source = path.read_text().lower()
        for needle in forbidden:
            assert needle not in source, f"{path} references {needle}"
```

Both directions are guarded because the Global Constraints state the boundary
bidirectionally. Each test is a placeholder guard until the directory it scans
contains real code — Task 2 gives the first one teeth, Task 6 the second.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest`
Expected: PASS, 2 passed.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt pytest.ini chronotune tools tests
git commit -m "chore: scaffold project with venv, pytest, and package boundary test"
```

---

### Task 2: Deezer source adapter

Deezer supplies availability and audio only — never the year. Loose search is required because strict field syntax (`artist:"…" track:"…"`) returned nothing for Daft Punk during research. Loose search in turn returns live and remix variants (verified: `Bohemian Rhapsody (Live At Wembley Stadium / July 1986)` and `(Live Aid)` both rank above nothing), so variant rejection is essential.

**Files:**
- Create: `tools/sources/deezer.py`
- Test: `tests/test_source_deezer.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `normalise(text: str) -> str`
  - `is_variant(title: str) -> bool`
  - `DeezerMatch` dataclass with fields `deezer_id: int`, `artist: str`, `title: str`
  - `search_track(artist: str, title: str, *, fetch_json=...) -> DeezerMatch | None`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_source_deezer.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_source_deezer.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.sources.deezer'`

- [ ] **Step 3: Write the implementation**

Write `tools/sources/deezer.py`:

```python
"""Deezer lookup: availability and audio only.

Deezer's release_date is NOT used. It reflects whichever album edition the
search lands on, which for catalogue artists is usually a remaster or
compilation (it dates Billie Jean to 2009). Years come from MusicBrainz and
Wikidata instead.
"""

from __future__ import annotations

import json
import re
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import dataclass

SEARCH_URL = "https://api.deezer.com/search"

# Markers of alternate recordings. Loose search ranks these highly, and their
# release years differ from the original, so they must never enter the pool.
VARIANT_MARKERS = (
    "live",
    "remix",
    "remaster",
    "remastered",
    "acoustic",
    "radio edit",
    "edit",
    "version",
    "instrumental",
    "karaoke",
    "cover",
    "demo",
    "reprise",
    "mix",
)


@dataclass(frozen=True)
class DeezerMatch:
    deezer_id: int
    artist: str
    title: str


def normalise(text: str) -> str:
    """Casefold, strip accents and punctuation, collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    lowered = without_accents.casefold()
    cleaned = re.sub(r"[^\w\s]", "", lowered)
    return re.sub(r"\s+", " ", cleaned).strip()


def is_variant(title: str) -> bool:
    """True if the title advertises itself as an alternate recording.

    Only text inside brackets or after a dash is examined, so a song genuinely
    called "Live Forever" or "Mixed Emotions" is not rejected.
    """
    qualifiers = re.findall(r"\(([^)]*)\)|\[([^\]]*)\]|\s-\s(.*)$", title)
    for groups in qualifiers:
        text = normalise(" ".join(g for g in groups if g))
        for marker in VARIANT_MARKERS:
            if re.search(rf"\b{re.escape(marker)}\b", text):
                return True
    return False


def _fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "Chronotune/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def search_track(artist: str, title: str, *, fetch_json=_fetch_json) -> DeezerMatch | None:
    """Find a streamable, non-variant Deezer track matching artist and title.

    Uses loose search deliberately: strict field syntax
    (artist:"…" track:"…") returns nothing for some tracks that loose search
    finds, so results are filtered client-side instead.
    """
    query = urllib.parse.quote(f"{artist} {title}")
    payload = fetch_json(f"{SEARCH_URL}?q={query}&limit=25")

    wanted_artist = normalise(artist)
    wanted_title = normalise(title)

    for entry in payload.get("data", []):
        found_title = entry.get("title", "")
        found_artist = entry.get("artist", {}).get("name", "")

        if not entry.get("preview"):
            continue
        if is_variant(found_title):
            continue
        if normalise(found_artist) != wanted_artist:
            continue
        if normalise(found_title) != wanted_title:
            continue

        return DeezerMatch(
            deezer_id=int(entry["id"]),
            artist=found_artist,
            title=found_title,
        )

    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_source_deezer.py`
Expected: PASS, all tests green.

- [ ] **Step 5: Sanity-check against the live API (manual, not part of the suite)**

```bash
.venv/bin/python -c "
from tools.sources.deezer import search_track
for a, t in [('Queen','Bohemian Rhapsody'), ('Daft Punk','Around the World'), ('Michael Jackson','Billie Jean')]:
    print(a, '-', t, '->', search_track(a, t))
"
```

Expected: a `DeezerMatch` for each, and none of them a live or remastered variant.

- [ ] **Step 6: Commit**

```bash
git add tools/sources/deezer.py tests/test_source_deezer.py
git commit -m "feat: add Deezer source adapter with variant rejection"
```

---

### Task 3: MusicBrainz source adapter

Must query **release-groups**, not recordings. Recording search dated Daft Punk's "Around the World" to 2004; the release-group query returns 1996–1997. The 1 request/second limit is mandatory.

**Files:**
- Create: `tools/sources/musicbrainz.py`
- Test: `tests/test_source_musicbrainz.py`

**Interfaces:**
- Consumes: nothing
- Produces: `first_release_year(artist: str, title: str, *, fetch_json=..., sleep=...) -> int | None`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_source_musicbrainz.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_source_musicbrainz.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.sources.musicbrainz'`

- [ ] **Step 3: Write the implementation**

Write `tools/sources/musicbrainz.py`:

```python
"""MusicBrainz lookup for a track's original release year.

Queries release-GROUPS, not recordings. Recording search returns reissue dates
(it dates Daft Punk's "Around the World" to 2004; the answer is 1997).

MusicBrainz requires a descriptive User-Agent and roughly 1 request/second.
Both are honoured here.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

SEARCH_URL = "https://musicbrainz.org/ws/2/release-group"
USER_AGENT = "Chronotune/0.1 (pishias92@gmail.com)"
RATE_LIMIT_SECONDS = 1.1


def _fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def _escape(value: str) -> str:
    """Escape backslashes and quotes for a Lucene phrase query.

    An unescaped quote closes the phrase early, producing a malformed query
    that returns wrong results or a 400 — which would halt a builder run
    partway through. Mirrors the equivalent escaping in the Wikidata adapter.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')


def first_release_year(
    artist: str,
    title: str,
    *,
    fetch_json=_fetch_json,
    sleep=time.sleep,
) -> int | None:
    """Earliest first-release-date year across matching release groups."""
    lucene = f'releasegroup:"{_escape(title)}" AND artist:"{_escape(artist)}"'
    query = urllib.parse.urlencode({"query": lucene, "fmt": "json", "limit": 10})

    try:
        payload = fetch_json(f"{SEARCH_URL}?{query}")
    finally:
        sleep(RATE_LIMIT_SECONDS)

    years = []
    for group in payload.get("release-groups", []):
        date = (group.get("first-release-date") or "").strip()
        if len(date) >= 4 and date[:4].isdigit():
            years.append(int(date[:4]))

    return min(years) if years else None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_source_musicbrainz.py`
Expected: PASS, 6 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/sources/musicbrainz.py tests/test_source_musicbrainz.py
git commit -m "feat: add MusicBrainz release-group year lookup"
```

---

### Task 4: Wikidata source adapter

Wikidata fails safe: when it lacks data it returns nothing rather than a wrong year. The loose label match (`rdfs:label|skos:altLabel`, prefix match) is required — a strict query returned results for only 1 of 5 test tracks, while the loose one got 7 of 8.

**Files:**
- Create: `tools/sources/wikidata.py`
- Test: `tests/test_source_wikidata.py`

**Interfaces:**
- Consumes: nothing
- Produces: `first_publication_year(artist: str, title: str, *, fetch_json=...) -> int | None`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_source_wikidata.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_source_wikidata.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.sources.wikidata'`

- [ ] **Step 3: Write the implementation**

Write `tools/sources/wikidata.py`:

```python
"""Wikidata lookup for a track's earliest publication date (P577).

Deliberately loose: matches rdfs:label OR skos:altLabel by prefix, and applies
no entity-type constraint, because tracks are typed inconsistently as song
(Q7366) or single (Q134556). A strict query found 1 of 5 test tracks; this one
found 7 of 8.

Wikidata fails safe — when it has no data it returns nothing rather than a
wrong year, so it can never silently poison the pool.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

SPARQL_URL = "https://query.wikidata.org/sparql"
USER_AGENT = "Chronotune/0.1 (pishias92@gmail.com)"

QUERY_TEMPLATE = """
SELECT ?song (MIN(?date) AS ?first) WHERE {
  ?artist rdfs:label|skos:altLabel "%(artist)s"@en .
  ?song wdt:P175 ?artist ;
        wdt:P577 ?date ;
        rdfs:label|skos:altLabel ?name .
  FILTER(LANG(?name) = "en" && STRSTARTS(LCASE(STR(?name)), LCASE("%(title)s")))
}
GROUP BY ?song
ORDER BY ?first
LIMIT 5
"""


def _escape(value: str) -> str:
    """Escape backslashes and quotes for a SPARQL string literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_query(artist: str, title: str) -> str:
    return QUERY_TEMPLATE % {"artist": _escape(artist), "title": _escape(title)}


def _fetch_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def first_publication_year(artist: str, title: str, *, fetch_json=_fetch_json) -> int | None:
    """Earliest P577 year for a song by this performer, or None."""
    query = build_query(artist, title)
    url = SPARQL_URL + "?" + urllib.parse.urlencode({"query": query, "format": "json"})
    payload = fetch_json(url)

    years = []
    for binding in payload.get("results", {}).get("bindings", []):
        raw = binding.get("first", {}).get("value", "")
        if len(raw) >= 4 and raw[:4].isdigit():
            years.append(int(raw[:4]))

    return min(years) if years else None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_source_wikidata.py`
Expected: PASS, 4 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/sources/wikidata.py tests/test_source_wikidata.py
git commit -m "feat: add Wikidata P577 year lookup"
```

---

### Task 5: The builder

Applies the consensus rule, writes `tracks.json`, `rejects.json` and the append-only `daily_order.json`. The append-only prefix assertion is the highest-stakes logic in the project: violating it silently rewrites already-played dailies and invalidates every shared grid.

**Files:**
- Create: `tools/build_tracks.py`, `data/seeds.txt`
- Test: `tests/test_build_tracks.py`

**Interfaces:**
- Consumes: `tools.sources.deezer.search_track`, `tools.sources.musicbrainz.first_release_year`, `tools.sources.wikidata.first_publication_year`
- Produces:
  - `parse_seeds(text: str) -> list[tuple[str, str]]`
  - `AppendOnlyViolation(Exception)`
  - `assert_append_only(existing: list[int], updated: list[int]) -> None`
  - `Evaluation` dataclass: `status: str` (`"accepted"` / `"rejected"`), `track: dict | None`, `reason: str | None`
  - `evaluate_seed(artist, title, *, search_track=..., mb_year=..., wd_year=...) -> Evaluation`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_build_tracks.py`:

```python
import json

import pytest

from tools.build_tracks import (
    AppendOnlyViolation,
    assert_append_only,
    evaluate_seed,
    parse_seeds,
)
from tools.sources.deezer import DeezerMatch

MATCH = DeezerMatch(deezer_id=42, artist="Queen", title="Bohemian Rhapsody")


def _evaluate(match=MATCH, mb=1975, wd=1975):
    return evaluate_seed(
        "Queen",
        "Bohemian Rhapsody",
        search_track=lambda a, t: match,
        mb_year=lambda a, t: mb,
        wd_year=lambda a, t: wd,
    )


def test_parse_seeds_splits_on_the_first_dash_only():
    text = "Queen - Bohemian Rhapsody\nJay-Z - 99 Problems\n"

    assert parse_seeds(text) == [("Queen", "Bohemian Rhapsody"), ("Jay-Z", "99 Problems")]


def test_parse_seeds_ignores_blanks_and_comments():
    text = "\n# a comment\nQueen - Bohemian Rhapsody\n   \n"

    assert parse_seeds(text) == [("Queen", "Bohemian Rhapsody")]


def test_accepts_when_musicbrainz_and_wikidata_agree():
    result = _evaluate(mb=1975, wd=1975)

    assert result.status == "accepted"
    assert result.track == {
        "deezer_id": 42,
        "artist": "Queen",
        "title": "Bohemian Rhapsody",
        "year": 1975,
        "sources": {"musicbrainz": 1975, "wikidata": 1975},
    }


def test_rejects_on_year_conflict():
    result = _evaluate(mb=1984, wd=1985)

    assert result.status == "rejected"
    assert result.reason == "year_conflict"


def test_rejects_when_musicbrainz_is_missing():
    assert _evaluate(mb=None).reason == "mb_missing"


def test_rejects_when_wikidata_is_missing():
    assert _evaluate(wd=None).reason == "wd_missing"


def test_rejects_when_deezer_has_no_match():
    assert _evaluate(match=None).reason == "no_deezer_match"


def test_deezer_is_checked_before_the_slow_sources():
    """Deezer is fast and unrated; skip MusicBrainz/Wikidata when it misses."""
    called = []

    evaluate_seed(
        "X", "Y",
        search_track=lambda a, t: None,
        mb_year=lambda a, t: called.append("mb"),
        wd_year=lambda a, t: called.append("wd"),
    )

    assert called == []


def test_append_only_allows_pure_appends():
    assert_append_only([1, 2, 3], [1, 2, 3, 4])
    assert_append_only([], [1])
    assert_append_only([1, 2], [1, 2])


def test_append_only_rejects_reordering():
    with pytest.raises(AppendOnlyViolation) as excinfo:
        assert_append_only([1, 2, 3], [1, 3, 2])

    assert "index 1" in str(excinfo.value)


def test_append_only_rejects_removal():
    with pytest.raises(AppendOnlyViolation):
        assert_append_only([1, 2, 3], [1, 2])


def test_append_only_rejects_edits_in_place():
    with pytest.raises(AppendOnlyViolation) as excinfo:
        assert_append_only([1, 2, 3], [1, 9, 3, 4])

    assert "index 1" in str(excinfo.value)


def _fake_evaluate(mapping):
    """Build an evaluate() stand-in from {(artist, title): Evaluation}."""
    def evaluate(artist, title):
        return mapping[(artist, title)]
    return evaluate


def _accepted(deezer_id, artist, title, year):
    from tools.build_tracks import Evaluation
    return Evaluation("accepted", track={
        "deezer_id": deezer_id, "artist": artist, "title": title,
        "year": year, "sources": {"musicbrainz": year, "wikidata": year},
    })


def _run(tmp_path, seeds_text, mapping, refresh=False):
    from tools.build_tracks import main
    seeds = tmp_path / "seeds.txt"
    seeds.write_text(seeds_text)
    argv = ["--seeds", str(seeds)] + (["--refresh"] if refresh else [])
    main(argv, evaluate=_fake_evaluate(mapping), data_dir=str(tmp_path))
    return json.loads((tmp_path / "daily_order.json").read_text())


def test_main_preserves_daily_order_prefix_across_runs(tmp_path):
    """The real regression test: main() must never disturb an existing order.

    This exercises the production write path, not list concatenation. Deleting
    assert_append_only from the source must make this fail.
    """
    mapping = {
        ("Queen", "Bohemian Rhapsody"): _accepted(1, "Queen", "Bohemian Rhapsody", 1975),
        ("Blur", "Song 2"): _accepted(2, "Blur", "Song 2", 1997),
    }
    first = _run(tmp_path, "Queen - Bohemian Rhapsody\n", mapping)
    assert first == [1]

    mapping[("Blur", "Song 2")] = _accepted(2, "Blur", "Song 2", 1997)
    second = _run(tmp_path, "Queen - Bohemian Rhapsody\nBlur - Song 2\n", mapping)

    assert second[: len(first)] == first, "existing days were disturbed"
    assert second == [1, 2]


def test_main_rerun_with_no_new_seeds_appends_nothing(tmp_path):
    mapping = {("Queen", "Bohemian Rhapsody"): _accepted(1, "Queen", "Bohemian Rhapsody", 1975)}
    text = "Queen - Bohemian Rhapsody\n"

    first = _run(tmp_path, text, mapping)
    second = _run(tmp_path, text, mapping)

    assert first == second == [1]


def test_refresh_never_appends_a_changed_deezer_id(tmp_path):
    """A drifted Deezer id must not strand a day on a track that is not stored.

    daily_order is append-only, so an id appended here could never be removed.
    """
    text = "Blur - Song 2\n"
    mapping = {("Blur", "Song 2"): _accepted(2, "Blur", "Song 2", 1997)}
    first = _run(tmp_path, text, mapping)
    assert first == [2]

    # Deezer's search ranking shifts and now returns a different id.
    mapping[("Blur", "Song 2")] = _accepted(999, "Blur", "Song 2", 1997)
    second = _run(tmp_path, text, mapping, refresh=True)

    assert second == [2], "refresh must not append a drifted id"

    tracks = json.loads((tmp_path / "tracks.json").read_text())
    ids = [t["deezer_id"] for t in tracks]
    assert set(second) <= set(ids), "daily_order references a track not in tracks.json"


def test_main_heals_a_track_recorded_without_its_order_entry(tmp_path):
    """Simulates a kill between the tracks.json and daily_order.json writes."""
    (tmp_path / "tracks.json").write_text(json.dumps([{
        "deezer_id": 7, "artist": "Blur", "title": "Song 2", "year": 1997,
        "sources": {"musicbrainz": 1997, "wikidata": 1997},
    }]))
    (tmp_path / "daily_order.json").write_text("[]")

    order = _run(tmp_path, "", {})

    assert order == [7], "an orphaned track must be given a day on the next run"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_build_tracks.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.build_tracks'`

- [ ] **Step 3: Write the implementation**

Write `tools/build_tracks.py`:

```python
"""Build the curated track pool.

Consensus rule: a track is accepted only when MusicBrainz and Wikidata report
the same year. Deezer decides availability and supplies the audio, but gets no
vote on the year — its release_date reflects whichever album edition the search
lands on (it dates Billie Jean to 2009).

Usage:
    python tools/build_tracks.py --seeds data/seeds.txt
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

# Allow `python tools/build_tracks.py` as well as `python -m tools.build_tracks`.
# Running a script by path puts tools/ on sys.path rather than the repo root, so
# the absolute `tools.sources` imports below would fail with ModuleNotFoundError.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.sources import deezer, musicbrainz, wikidata

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = REPO_ROOT / "data"

TRACKS_NAME = "tracks.json"
ORDER_NAME = "daily_order.json"
REJECTS_NAME = "rejects.json"


class AppendOnlyViolation(Exception):
    """Raised when a write would reorder, edit or remove daily_order entries."""


@dataclass
class Evaluation:
    status: str
    track: dict | None = None
    reason: str | None = None


def parse_seeds(text: str) -> list[tuple[str, str]]:
    """Parse 'Artist - Title' lines, ignoring blanks and # comments."""
    seeds = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if " - " not in line:
            continue
        artist, title = line.split(" - ", 1)
        seeds.append((artist.strip(), title.strip()))
    return seeds


def evaluate_seed(
    artist: str,
    title: str,
    *,
    search_track=deezer.search_track,
    mb_year=musicbrainz.first_release_year,
    wd_year=wikidata.first_publication_year,
) -> Evaluation:
    """Apply the acceptance rule to a single seed."""
    # Deezer first: it is fast and unrated, so a miss saves two slow lookups.
    match = search_track(artist, title)
    if match is None:
        return Evaluation("rejected", reason="no_deezer_match")

    mb = mb_year(artist, title)
    if mb is None:
        return Evaluation("rejected", reason="mb_missing")

    wd = wd_year(artist, title)
    if wd is None:
        return Evaluation("rejected", reason="wd_missing")

    if mb != wd:
        return Evaluation("rejected", reason="year_conflict")

    return Evaluation(
        "accepted",
        track={
            "deezer_id": match.deezer_id,
            "artist": match.artist,
            "title": match.title,
            "year": mb,
            "sources": {"musicbrainz": mb, "wikidata": wd},
        },
    )


def assert_append_only(existing: list[int], updated: list[int]) -> None:
    """Guarantee `existing` is an exact prefix of `updated`.

    Reordering or removing entries silently changes which song players got on
    days they have already played, and invalidates every shared grid. This is
    an enforced invariant, not a convention.
    """
    if len(updated) < len(existing):
        raise AppendOnlyViolation(
            f"daily_order shrank from {len(existing)} to {len(updated)} entries; "
            "entries must never be removed"
        )

    for index, (old, new) in enumerate(zip(existing, updated)):
        if old != new:
            raise AppendOnlyViolation(
                f"daily_order diverges at index {index}: {old} != {new}. "
                "Existing entries must never be reordered or edited."
            )


def _load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def _write_json(path: Path, payload) -> None:
    """Write atomically.

    daily_order.json is rewritten once per accepted seed. A plain write_text
    truncates before writing, so a kill inside that window leaves a truncated
    file — and for the file whose corruption invalidates every shared grid,
    "recoverable from git" is not the bar. Stage then os.replace.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def _cache_key(artist: str, title: str) -> str:
    return f"{deezer.normalise(artist)}|{deezer.normalise(title)}"


def main(argv=None, *, evaluate=evaluate_seed, data_dir=None) -> int:
    parser = argparse.ArgumentParser(description="Build the Chronotune track pool.")
    parser.add_argument("--seeds", default=str(DEFAULT_DATA_DIR / "seeds.txt"))
    parser.add_argument("--data-dir", default=None,
                        help="Directory holding tracks.json, daily_order.json and "
                             "rejects.json. All three move together — they are one "
                             "consistent set and must never be split across dirs.")
    parser.add_argument("--refresh", action="store_true",
                        help="Re-evaluate seeds already recorded. Updates a track's "
                             "year in place; never changes its daily_order position.")
    args = parser.parse_args(argv)

    # All three files derive from one directory. Parameterising only tracks.json
    # would let a scratch run write its pool elsewhere while still appending to
    # the real daily_order.json — corrupting the file it looks safest to avoid.
    base = Path(data_dir or args.data_dir or DEFAULT_DATA_DIR)
    tracks_path = base / TRACKS_NAME
    order_path = base / ORDER_NAME
    rejects_path = base / REJECTS_NAME

    tracks = _load_json(tracks_path, [])
    order = _load_json(order_path, [])
    rejects = _load_json(rejects_path, [])

    # Self-heal a kill between the tracks.json and daily_order.json writes: a
    # track recorded without its order entry would otherwise be skipped forever
    # on rerun and never get a day.
    in_order = set(order)
    for track in tracks:
        if track["deezer_id"] not in in_order:
            order.append(track["deezer_id"])
            in_order.add(track["deezer_id"])

    original_order = list(order)
    by_key = {_cache_key(t["artist"], t["title"]): t for t in tracks}
    rejects_by_key = {_cache_key(r["artist"], r["title"]): r for r in rejects}

    seeds = parse_seeds(Path(args.seeds).read_text())
    print(f"{len(seeds)} seeds, {len(tracks)} already accepted, {len(rejects)} rejected")

    errors = 0
    for artist, title in seeds:
        key = _cache_key(artist, title)
        if not args.refresh and (key in by_key or key in rejects_by_key):
            continue

        try:
            result = evaluate(artist, title)
        except Exception as error:  # network failures must not lose progress
            errors += 1
            print(f"  ERROR {artist} - {title}: {type(error).__name__}: {error}")
            continue

        if result.status == "rejected":
            print(f"  reject {artist} - {title} ({result.reason})")
            # Update the reason in place when it changes. Skipping on mere
            # membership would keep a stale reason forever under --refresh,
            # and rejects.json is what curation triage reads.
            previous = rejects_by_key.get(key)
            if previous is None:
                entry = {"artist": artist, "title": title, "reason": result.reason}
                rejects.append(entry)
                rejects_by_key[key] = entry
                _write_json(rejects_path, rejects)
            elif previous["reason"] != result.reason:
                previous["reason"] = result.reason
                _write_json(rejects_path, rejects)
            continue

        track = result.track
        print(f"  accept {artist} - {title} -> {track['year']}")

        existing = by_key.get(key)
        if existing is None:
            tracks.append(track)
            by_key[key] = track
            if track["deezer_id"] not in in_order:
                order.append(track["deezer_id"])
                in_order.add(track["deezer_id"])
        else:
            # Refresh updates the year in place. The deezer_id is deliberately
            # NOT replaced: daily_order already points at it, and swapping it
            # would strand that day on an id tracks.json no longer contains.
            existing["year"] = track["year"]
            existing["sources"] = track["sources"]

        # Resumable: persist after every acceptance so a crash loses nothing.
        assert_append_only(original_order, order)
        _write_json(tracks_path, tracks)
        _write_json(order_path, order)

    assert_append_only(original_order, order)
    _write_json(tracks_path, tracks)
    _write_json(order_path, order)

    print(f"\n{len(tracks)} tracks, {len(order)} daily slots, {len(rejects)} rejects")
    if errors:
        print(f"{errors} seed(s) errored")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_build_tracks.py`
Expected: PASS, 13 passed.

- [ ] **Step 5: Create a starter seed file**

Write `data/seeds.txt`:

```
# One "Artist - Title" per line. Blank lines and # comments are ignored.
# Expect roughly 70% to survive the MusicBrainz/Wikidata consensus check.
Queen - Bohemian Rhapsody
Michael Jackson - Billie Jean
Nirvana - Smells Like Teen Spirit
Fleetwood Mac - Dreams
Gotye - Somebody That I Used to Know
Kate Bush - Running Up That Hill
Outkast - Hey Ya!
Blur - Song 2
The Killers - Mr. Brightside
Amy Winehouse - Rehab
Daft Punk - Around the World
Radiohead - Creep
a-ha - Take On Me
Rick Astley - Never Gonna Give You Up
Eminem - Lose Yourself
```

- [ ] **Step 6: Run the builder against the live APIs**

```bash
.venv/bin/python tools/build_tracks.py --seeds data/seeds.txt
```

Expected: roughly 10–12 accepted of 15, rejects recorded with reasons. This takes about a minute because of the MusicBrainz rate limit. Inspect `data/rejects.json` and confirm the reasons look sane.

- [ ] **Step 7: Verify the append-only guard on a real rerun**

```bash
.venv/bin/python -c "
import json; print('order before:', json.load(open('data/daily_order.json')))"
.venv/bin/python tools/build_tracks.py --seeds data/seeds.txt
.venv/bin/python -c "
import json; print('order after: ', json.load(open('data/daily_order.json')))"
```

Expected: identical output both times — a rerun with no new seeds appends nothing and reorders nothing.

- [ ] **Step 8: Commit**

```bash
git add tools/build_tracks.py tests/test_build_tracks.py data/seeds.txt data/tracks.json data/daily_order.json data/rejects.json
git commit -m "feat: add track pool builder with append-only daily order"
```

---

### Task 6: Pool store with startup validation

Failures here must be loud at startup, never silent at request time. A `daily_order` entry with no matching track cannot be skipped — skipping shifts every later day.

**Files:**
- Create: `chronotune/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `data/tracks.json`, `data/daily_order.json`
- Produces:
  - `Track` dataclass: `deezer_id: int`, `artist: str`, `title: str`, `year: int`
  - `PoolError(Exception)`
  - `Pool` with `.tracks: list[Track]`, `.daily_order: list[int]`, `.by_id(deezer_id) -> Track`, `.__len__()`
  - `load_pool(tracks_path, order_path) -> Pool`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_store.py`:

```python
import json

import pytest

from chronotune.store import Pool, PoolError, Track, load_pool


def _write(tmp_path, tracks, order):
    tracks_path = tmp_path / "tracks.json"
    order_path = tmp_path / "daily_order.json"
    tracks_path.write_text(json.dumps(tracks))
    order_path.write_text(json.dumps(order))
    return tracks_path, order_path


TRACK = {
    "deezer_id": 42,
    "artist": "Queen",
    "title": "Bohemian Rhapsody",
    "year": 1975,
    "sources": {"musicbrainz": 1975, "wikidata": 1975},
}


def test_loads_tracks_and_order(tmp_path):
    pool = load_pool(*_write(tmp_path, [TRACK], [42]))

    assert len(pool) == 1
    assert pool.daily_order == [42]
    assert pool.by_id(42) == Track(deezer_id=42, artist="Queen",
                                   title="Bohemian Rhapsody", year=1975)


def test_raises_when_tracks_file_is_missing(tmp_path):
    order_path = tmp_path / "daily_order.json"
    order_path.write_text("[]")

    with pytest.raises(PoolError, match="not found"):
        load_pool(tmp_path / "missing.json", order_path)


def test_raises_when_pool_is_empty(tmp_path):
    with pytest.raises(PoolError, match="empty"):
        load_pool(*_write(tmp_path, [], []))


def test_raises_when_daily_order_references_an_unknown_track(tmp_path):
    """Never skip — skipping shifts every subsequent day."""
    with pytest.raises(PoolError, match="99"):
        load_pool(*_write(tmp_path, [TRACK], [42, 99]))


def test_raises_on_duplicate_deezer_ids(tmp_path):
    with pytest.raises(PoolError, match="duplicate"):
        load_pool(*_write(tmp_path, [TRACK, TRACK], [42]))


def test_by_id_raises_keyerror_for_unknown_track(tmp_path):
    pool = load_pool(*_write(tmp_path, [TRACK], [42]))

    with pytest.raises(KeyError):
        pool.by_id(999)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_store.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'chronotune.store'`

- [ ] **Step 3: Write the implementation**

Write `chronotune/store.py`:

```python
"""Load and validate the curated pool.

All validation happens at startup and fails loudly. A daily_order entry with no
matching track is a hard error rather than a skip: skipping would shift every
subsequent day and invalidate already-shared grids.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


class PoolError(Exception):
    """Raised when the curated data files are missing or inconsistent."""


@dataclass(frozen=True)
class Track:
    deezer_id: int
    artist: str
    title: str
    year: int


class Pool:
    def __init__(self, tracks: list[Track], daily_order: list[int]):
        self.tracks = tracks
        self.daily_order = daily_order
        self._by_id = {track.deezer_id: track for track in tracks}

    def by_id(self, deezer_id: int) -> Track:
        return self._by_id[deezer_id]

    def __len__(self) -> int:
        return len(self.tracks)


def _read_json(path: Path):
    if not path.exists():
        raise PoolError(f"{path} not found. Run tools/build_tracks.py first.")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise PoolError(f"{path} is not valid JSON: {error}") from error


def load_pool(tracks_path, order_path) -> Pool:
    tracks_path = Path(tracks_path)
    raw_tracks = _read_json(tracks_path)
    raw_order = _read_json(Path(order_path))

    if not raw_tracks:
        raise PoolError("Track pool is empty. Run tools/build_tracks.py first.")

    tracks = []
    for index, entry in enumerate(raw_tracks):
        # Every load failure must surface as PoolError so callers can wrap
        # startup in a single except and print something usable. A malformed
        # record would otherwise escape as a raw KeyError/TypeError/ValueError.
        try:
            tracks.append(
                Track(
                    deezer_id=int(entry["deezer_id"]),
                    artist=entry["artist"],
                    title=entry["title"],
                    year=int(entry["year"]),
                )
            )
        except (KeyError, TypeError, ValueError) as error:
            raise PoolError(
                f"{tracks_path} entry {index} is malformed: {error!r}"
            ) from error

    ids = [track.deezer_id for track in tracks]
    if len(ids) != len(set(ids)):
        duplicates = sorted(i for i, n in Counter(ids).items() if n > 1)
        raise PoolError(f"duplicate deezer_id in tracks.json: {duplicates}")

    known = set(ids)
    missing = [i for i in raw_order if i not in known]
    if missing:
        raise PoolError(
            f"daily_order references tracks missing from tracks.json: {missing}. "
            "Do not remove them from daily_order — that shifts every later day. "
            "Restore the track data or fix the entry deliberately."
        )

    return Pool(tracks, list(raw_order))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_store.py`
Expected: PASS, 6 passed.

- [ ] **Step 5: Commit**

```bash
git add chronotune/store.py tests/test_store.py
git commit -m "feat: add pool store with loud startup validation"
```

---

### Task 7: Game logic

Pure functions, no I/O.

**Files:**
- Create: `chronotune/game.py`
- Test: `tests/test_game.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `SNIPPET_LADDER: tuple[int, ...]` = `(1, 2, 4, 7, 11, 16)`
  - `MAX_GUESSES: int` = `6`
  - `snippet_seconds(wrong_guesses: int) -> int`
  - `evaluate_guess(guess: int, answer: int) -> str` → `"correct"` / `"earlier"` / `"later"`
  - `proximity_band(guess: int, answer: int) -> str` → an emoji
  - `is_round_over(guesses: list[int], answer: int) -> bool`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_game.py`:

```python
import pytest

from chronotune.game import (
    MAX_GUESSES,
    SNIPPET_LADDER,
    evaluate_guess,
    is_round_over,
    proximity_band,
    snippet_seconds,
)


def test_ladder_matches_the_spec():
    assert SNIPPET_LADDER == (1, 2, 4, 7, 11, 16)
    assert MAX_GUESSES == 6
    assert len(SNIPPET_LADDER) == MAX_GUESSES


@pytest.mark.parametrize(
    "wrong_guesses,expected",
    [(0, 1), (1, 2), (2, 4), (3, 7), (4, 11), (5, 16)],
)
def test_snippet_grows_with_each_wrong_guess(wrong_guesses, expected):
    assert snippet_seconds(wrong_guesses) == expected


def test_snippet_caps_at_the_final_rung():
    assert snippet_seconds(6) == 16
    assert snippet_seconds(99) == 16


def test_negative_guess_count_is_rejected():
    with pytest.raises(ValueError):
        snippet_seconds(-1)


def test_evaluate_guess_directions():
    assert evaluate_guess(1991, 1991) == "correct"
    assert evaluate_guess(1985, 1991) == "later"
    assert evaluate_guess(1998, 1991) == "earlier"


@pytest.mark.parametrize(
    "guess,answer,band",
    [
        (1991, 1991, "🟩"),
        (1993, 1991, "🟨"),
        (1989, 1991, "🟨"),
        (2001, 1991, "🟧"),
        (1981, 1991, "🟧"),
        (2002, 1991, "🟥"),
        (1900, 1991, "🟥"),
    ],
)
def test_proximity_bands(guess, answer, band):
    assert proximity_band(guess, answer) == band


def test_band_boundaries_are_inclusive():
    assert proximity_band(1993, 1991) == "🟨"  # exactly 2 off
    assert proximity_band(1994, 1991) == "🟧"  # 3 off
    assert proximity_band(2001, 1991) == "🟧"  # exactly 10 off
    assert proximity_band(2002, 1991) == "🟥"  # 11 off


def test_round_ends_on_a_correct_guess():
    assert is_round_over([1985, 1991], 1991) is True


def test_round_ends_after_six_wrong_guesses():
    assert is_round_over([1, 2, 3, 4, 5, 6], 1991) is True


def test_round_continues_while_guesses_remain():
    assert is_round_over([1985, 1998], 1991) is False
    assert is_round_over([], 1991) is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_game.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'chronotune.game'`

- [ ] **Step 3: Write the implementation**

Write `chronotune/game.py`:

```python
"""Core game rules. Pure functions, no I/O."""

from __future__ import annotations

SNIPPET_LADDER: tuple[int, ...] = (1, 2, 4, 7, 11, 16)
MAX_GUESSES: int = len(SNIPPET_LADDER)

CORRECT = "🟩"
CLOSE = "🟨"
NEAR = "🟧"
FAR = "🟥"
UNUSED = "⬜"


def snippet_seconds(wrong_guesses: int) -> int:
    """Audio length unlocked after this many wrong guesses."""
    if wrong_guesses < 0:
        raise ValueError("wrong_guesses must not be negative")
    index = min(wrong_guesses, len(SNIPPET_LADDER) - 1)
    return SNIPPET_LADDER[index]


def evaluate_guess(guess: int, answer: int) -> str:
    """Directional feedback for a single guess."""
    if guess == answer:
        return "correct"
    return "later" if guess < answer else "earlier"


def proximity_band(guess: int, answer: int) -> str:
    """Emoji band for the share grid. Boundaries are inclusive."""
    distance = abs(guess - answer)
    if distance == 0:
        return CORRECT
    if distance <= 2:
        return CLOSE
    if distance <= 10:
        return NEAR
    return FAR


def is_round_over(guesses: list[int], answer: int) -> bool:
    return answer in guesses or len(guesses) >= MAX_GUESSES
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_game.py`
Expected: PASS, all green.

- [ ] **Step 5: Commit**

```bash
git add chronotune/game.py tests/test_game.py
git commit -m "feat: add game rules for snippet ladder and guess evaluation"
```

---

### Task 8: Share grid

**Files:**
- Create: `chronotune/share.py`
- Test: `tests/test_share.py`

**Interfaces:**
- Consumes: `chronotune.game.proximity_band`, `MAX_GUESSES`, `UNUSED`
- Produces: `share_text(puzzle_number: int, guesses: list[int], answer: int) -> str`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_share.py`:

```python
from chronotune.share import share_text


def test_solved_round_grid_and_summary():
    text = share_text(142, [1985, 1998, 1991], 1991)

    assert text == "CHRONOTUNE #142\n🟥🟧🟩⬜⬜⬜\nSolved in 3 · 🔊🔊🔊"


def test_unsolved_round_shows_an_x():
    text = share_text(7, [1960, 1965, 1970, 1975, 1980, 1985], 2020)

    assert text.startswith("CHRONOTUNE #7\n")
    assert text.endswith("X/6")
    assert "⬜" not in text


def test_grid_always_has_six_cells():
    """Each band emoji is a single codepoint, so the grid is exactly 6 chars."""
    grid = share_text(1, [1991], 1991).splitlines()[1]

    assert len(grid) == 6
    assert grid == "🟩⬜⬜⬜⬜⬜"


def test_no_answer_year_leaks_into_the_share_text():
    """Sharing must not spoil the answer for anyone reading it."""
    text = share_text(142, [1985, 1991], 1991)

    assert "1991" not in text
    assert "1985" not in text


def test_speaker_count_matches_guesses_used():
    assert "🔊🔊" in share_text(3, [1985, 1991], 1991)
    assert share_text(3, [1991], 1991).count("🔊") == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_share.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'chronotune.share'`

- [ ] **Step 3: Write the implementation**

Write `chronotune/share.py`:

```python
"""Wordle-style share grid.

Never includes any year — a shared result must not spoil the puzzle.
"""

from __future__ import annotations

from chronotune.game import MAX_GUESSES, UNUSED, proximity_band


def share_text(puzzle_number: int, guesses: list[int], answer: int) -> str:
    bands = [proximity_band(guess, answer) for guess in guesses]
    padding = [UNUSED] * (MAX_GUESSES - len(bands))
    grid = "".join(bands + padding)

    solved = answer in guesses
    if solved:
        summary = f"Solved in {len(guesses)} · " + "🔊" * len(guesses)
    else:
        summary = "X/6"

    return f"CHRONOTUNE #{puzzle_number}\n{grid}\n{summary}"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_share.py`
Expected: PASS, 5 passed.

- [ ] **Step 5: Commit**

```bash
git add chronotune/share.py tests/test_share.py
git commit -m "feat: add spoiler-free share grid"
```

---

### Task 9: Puzzle selection

**Files:**
- Create: `chronotune/puzzle.py`
- Test: `tests/test_puzzle.py`

**Interfaces:**
- Consumes: `chronotune.store.Pool`
- Produces:
  - `EPOCH: datetime.date` = `date(2026, 1, 1)`
  - `puzzle_number(today: date) -> int` (1-based)
  - `daily_track_id(pool: Pool, today: date) -> int`
  - `pick_unseen_track_id(pool: Pool, seen: list[int], *, rng=random) -> int | None`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_puzzle.py`:

```python
import random
from datetime import date

from chronotune.puzzle import EPOCH, daily_track_id, pick_unseen_track_id, puzzle_number
from chronotune.store import Pool, Track


def _pool(ids):
    tracks = [Track(deezer_id=i, artist="A", title=f"T{i}", year=2000) for i in ids]
    return Pool(tracks, list(ids))


def test_puzzle_number_starts_at_one_on_the_epoch():
    assert puzzle_number(EPOCH) == 1
    assert puzzle_number(date(2026, 1, 2)) == 2


def test_daily_is_deterministic_for_a_given_date():
    pool = _pool([10, 20, 30])
    day = date(2026, 3, 5)

    assert daily_track_id(pool, day) == daily_track_id(pool, day)


def test_consecutive_days_walk_the_order():
    pool = _pool([10, 20, 30])

    assert daily_track_id(pool, date(2026, 1, 1)) == 10
    assert daily_track_id(pool, date(2026, 1, 2)) == 20
    assert daily_track_id(pool, date(2026, 1, 3)) == 30


def test_daily_wraps_when_the_list_is_exhausted():
    pool = _pool([10, 20, 30])

    assert daily_track_id(pool, date(2026, 1, 4)) == 10


def test_appending_to_the_order_does_not_change_earlier_days():
    """The whole point of append-only: past dailies must be stable."""
    before = _pool([10, 20, 30])
    after = _pool([10, 20, 30, 40, 50])

    for offset in range(3):
        day = date(2026, 1, 1 + offset)
        assert daily_track_id(before, day) == daily_track_id(after, day)


def test_pick_unseen_excludes_seen_tracks():
    pool = _pool([10, 20, 30])

    assert pick_unseen_track_id(pool, [10, 20], rng=random.Random(0)) == 30


def test_pick_unseen_returns_none_when_everything_is_seen():
    pool = _pool([10, 20])

    assert pick_unseen_track_id(pool, [10, 20], rng=random.Random(0)) is None


def test_pick_unseen_is_deterministic_for_a_seeded_rng():
    pool = _pool([10, 20, 30, 40])

    first = pick_unseen_track_id(pool, [], rng=random.Random(7))
    second = pick_unseen_track_id(pool, [], rng=random.Random(7))

    assert first == second
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_puzzle.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'chronotune.puzzle'`

- [ ] **Step 3: Write the implementation**

Write `chronotune/puzzle.py`:

```python
"""Puzzle selection.

The daily walks data/daily_order.json directly rather than shuffling the pool.
A seeded shuffle would be recomputed over the whole pool, so every builder run
that added tracks would reorder the sequence and change which song players got
on days they had already played. Because daily_order is append-only, indexing
into it keeps past dailies stable forever.
"""

from __future__ import annotations

import random as _random
from datetime import date

from chronotune.store import Pool

EPOCH = date(2026, 1, 1)


def _days_since_epoch(today: date) -> int:
    return (today - EPOCH).days


def puzzle_number(today: date) -> int:
    """1-based puzzle number shown to players and used in share text."""
    return _days_since_epoch(today) + 1


def daily_track_id(pool: Pool, today: date) -> int:
    order = pool.daily_order
    return order[_days_since_epoch(today) % len(order)]


def pick_unseen_track_id(pool: Pool, seen: list[int], *, rng=_random) -> int | None:
    """A random track the player has not played in infinite mode."""
    seen_set = set(seen)
    candidates = sorted(t.deezer_id for t in pool.tracks if t.deezer_id not in seen_set)
    if not candidates:
        return None
    return rng.choice(candidates)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_puzzle.py`
Expected: PASS, 8 passed.

- [ ] **Step 5: Commit**

```bash
git add chronotune/puzzle.py tests/test_puzzle.py
git commit -m "feat: add deterministic daily and random infinite selection"
```

---

### Task 10: Runtime preview URL resolution

Preview URLs carry an expiry token with roughly a 7-hour life, so they are resolved per request and never persisted.

**Files:**
- Create: `chronotune/deezer.py`
- Test: `tests/test_runtime_deezer.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `PreviewUnavailable(Exception)`
  - `resolve_preview_url(deezer_id: int, *, fetch_json=..., attempts: int = 2) -> str`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_runtime_deezer.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_runtime_deezer.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'chronotune.deezer'`

- [ ] **Step 3: Write the implementation**

Write `chronotune/deezer.py`:

```python
"""Resolve a Deezer preview URL at request time.

Preview URLs embed an expiry token (~7h), so they are never stored in
tracks.json — only the track id is. The MP3 responds with
`access-control-allow-origin: *`, so the browser can read it with the Web Audio
API without a proxy.
"""

from __future__ import annotations

import json
import urllib.request

TRACK_URL = "https://api.deezer.com/track"


class PreviewUnavailable(Exception):
    """Raised when no playable preview URL could be obtained."""


def _fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "Chronotune/0.1"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def resolve_preview_url(deezer_id: int, *, fetch_json=_fetch_json, attempts: int = 2) -> str:
    last_error: Exception | None = None

    for _ in range(attempts):
        try:
            payload = fetch_json(f"{TRACK_URL}/{deezer_id}")
        except Exception as error:
            last_error = error
            continue

        if "error" in payload:
            last_error = PreviewUnavailable(f"Deezer error: {payload['error']}")
            continue

        preview = payload.get("preview") or ""
        if preview:
            return preview

        last_error = PreviewUnavailable(f"track {deezer_id} has no preview")

    raise PreviewUnavailable(f"could not resolve preview for {deezer_id}") from last_error
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_runtime_deezer.py`
Expected: PASS, 5 passed.

- [ ] **Step 5: Commit**

```bash
git add chronotune/deezer.py tests/test_runtime_deezer.py
git commit -m "feat: resolve expiring Deezer preview URLs at request time"
```

---

### Task 11: Flask app and API

The answer year is never sent to the client until the round is over, so it cannot be read out of the network tab.

**Files:**
- Create: `app.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `chronotune.store.load_pool`, `chronotune.puzzle`, `chronotune.game`, `chronotune.deezer.resolve_preview_url`
- Produces: `create_app(pool=None, resolve_preview=None, today=None) -> Flask`

Routes:
| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/` | — | HTML page |
| GET | `/api/daily` | — | `{deezer_id, puzzle_number, max_guesses, ladder}` |
| POST | `/api/infinite` | `{seen: [int]}` | `{deezer_id}` or 409 when exhausted |
| GET | `/api/audio/<int:deezer_id>` | — | `{url}` or 503 |
| POST | `/api/guess` | `{deezer_id, guess, guess_number}` | `{result, band, snippet_seconds, answer?, artist?, title?}` |

- [ ] **Step 1: Write the failing tests**

Write `tests/test_app.py`:

```python
from datetime import date

import pytest

from app import create_app
from chronotune.deezer import PreviewUnavailable
from chronotune.store import Pool, Track

TRACKS = [
    Track(deezer_id=10, artist="Queen", title="Bohemian Rhapsody", year=1975),
    Track(deezer_id=20, artist="Nirvana", title="Smells Like Teen Spirit", year=1991),
]


@pytest.fixture
def client():
    pool = Pool(TRACKS, [10, 20])
    app = create_app(
        pool=pool,
        resolve_preview=lambda deezer_id: f"https://cdn/{deezer_id}.mp3",
        today=lambda: date(2026, 1, 2),
    )
    app.config.update(TESTING=True)
    return app.test_client()


def test_daily_returns_the_track_for_today(client):
    body = client.get("/api/daily").get_json()

    assert body["deezer_id"] == 20
    assert body["puzzle_number"] == 2
    assert body["max_guesses"] == 6
    assert body["ladder"] == [1, 2, 4, 7, 11, 16]


def test_daily_never_leaks_the_answer(client):
    body = client.get("/api/daily").get_json()

    assert "year" not in body
    assert "title" not in body


def test_audio_returns_a_resolved_url(client):
    body = client.get("/api/audio/10").get_json()

    assert body["url"] == "https://cdn/10.mp3"


def test_audio_returns_503_when_unavailable():
    def broken(deezer_id):
        raise PreviewUnavailable("nope")

    app = create_app(pool=Pool(TRACKS, [10]), resolve_preview=broken,
                     today=lambda: date(2026, 1, 1))
    app.config.update(TESTING=True)
    response = app.test_client().get("/api/audio/10")

    assert response.status_code == 503
    assert "unavailable" in response.get_json()["error"]


def test_audio_404s_for_a_track_outside_the_pool(client):
    assert client.get("/api/audio/999").status_code == 404


def test_wrong_guess_gives_direction_without_the_answer(client):
    body = client.post("/api/guess", json={"deezer_id": 20, "guess": 1985,
                                           "guess_number": 1}).get_json()

    assert body["result"] == "later"
    assert body["snippet_seconds"] == 2
    assert "answer" not in body


def test_correct_guess_reveals_the_track(client):
    body = client.post("/api/guess", json={"deezer_id": 20, "guess": 1991,
                                           "guess_number": 1}).get_json()

    assert body["result"] == "correct"
    assert body["answer"] == 1991
    assert body["artist"] == "Nirvana"


def test_final_wrong_guess_reveals_the_answer(client):
    body = client.post("/api/guess", json={"deezer_id": 20, "guess": 1985,
                                           "guess_number": 6}).get_json()

    assert body["result"] == "later"
    assert body["answer"] == 1991
    assert body["title"] == "Smells Like Teen Spirit"


def test_non_integer_guess_is_rejected(client):
    response = client.post("/api/guess", json={"deezer_id": 20, "guess": "abc",
                                               "guess_number": 1})

    assert response.status_code == 400


def test_out_of_range_guess_is_rejected(client):
    response = client.post("/api/guess", json={"deezer_id": 20, "guess": 1200,
                                               "guess_number": 1})

    assert response.status_code == 400


def test_infinite_returns_an_unseen_track(client):
    body = client.post("/api/infinite", json={"seen": [10]}).get_json()

    assert body["deezer_id"] == 20


def test_infinite_409s_when_the_pool_is_exhausted(client):
    response = client.post("/api/infinite", json={"seen": [10, 20]})

    assert response.status_code == 409


def test_index_page_renders(client):
    assert client.get("/").status_code == 200
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_app.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Write the implementation**

Write `app.py`:

```python
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


def create_app(pool=None, resolve_preview=None, today=None) -> Flask:
    app = Flask(__name__)

    # Loaded once at startup so bad data fails loudly here, not mid-request.
    app.pool = pool if pool is not None else load_pool(
        "data/tracks.json", "data/daily_order.json"
    )
    resolve = resolve_preview or resolve_preview_url
    now = today or date.today

    def _track_or_404(deezer_id):
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

        return jsonify(deezer_id=track_id, max_guesses=MAX_GUESSES,
                       ladder=list(SNIPPET_LADDER))

    @app.get("/api/audio/<int:deezer_id>")
    def audio(deezer_id):
        if _track_or_404(deezer_id) is None:
            return jsonify(error="unknown track"), 404
        try:
            return jsonify(url=resolve(deezer_id))
        except PreviewUnavailable:
            return jsonify(error="Audio unavailable — try again."), 503

    @app.post("/api/guess")
    def guess():
        body = request.get_json(silent=True) or {}

        track = _track_or_404(body.get("deezer_id"))
        if track is None:
            return jsonify(error="unknown track"), 404

        raw_guess = body.get("guess")
        if isinstance(raw_guess, bool) or not isinstance(raw_guess, int):
            return jsonify(error="guess must be an integer year"), 400
        if not MIN_YEAR <= raw_guess <= MAX_YEAR:
            return jsonify(error=f"guess must be between {MIN_YEAR} and {MAX_YEAR}"), 400

        guess_number = body.get("guess_number", 1)
        if not isinstance(guess_number, int) or not 1 <= guess_number <= MAX_GUESSES:
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
```

- [ ] **Step 4: Create a placeholder template, then run the full suite**

`test_index_page_renders` needs `templates/index.html`, which Task 12 replaces with the
real UI. Create a stub so the suite is green in the meantime:

```bash
printf '<!doctype html><title>Chronotune</title><p>placeholder</p>\n' > templates/index.html
.venv/bin/pytest
```

Expected: PASS, all tests green.

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app.py templates/index.html
git commit -m "feat: add Flask API for daily, infinite, audio and guesses"
```

---

### Task 12: Frontend player and UI

Vanilla JS, no build step. The Web Audio API is used because the MP3 serves `access-control-allow-origin: *`, giving a sample-accurate stop at the snippet boundary and real waveform data. Client-side snippet enforcement is not tamper-proof; that is accepted.

**Files:**
- Create: `static/app.js`, `static/style.css`
- Modify: `templates/index.html` (replace the placeholder)

**Interfaces:**
- Consumes: `/api/daily`, `/api/infinite`, `/api/audio/<id>`, `/api/guess`
- Produces: browser UI only; no Python interface

- [ ] **Step 1: Write the page markup**

Replace `templates/index.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Chronotune</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
  <main id="app">
    <header>
      <h1>Chronotune</h1>
      <p id="subtitle">Guess the year</p>
      <nav>
        <button id="mode-daily" class="mode active">Daily</button>
        <button id="mode-infinite" class="mode">Infinite</button>
      </nav>
    </header>

    <section id="player">
      <canvas id="waveform" width="600" height="80"></canvas>
      <button id="play">Play <span id="snippet-length">1</span>s</button>
    </section>

    <section id="guesses"></section>

    <form id="guess-form">
      <input id="guess-input" type="number" inputmode="numeric"
             min="1900" max="2100" placeholder="Year" required>
      <button type="submit">Guess</button>
      <button type="button" id="skip">Skip</button>
    </form>

    <section id="result" hidden>
      <p id="reveal"></p>
      <pre id="share-grid"></pre>
      <button id="share">Copy result</button>
      <button id="next" hidden>Next track</button>
    </section>

    <p id="error" role="alert" hidden></p>
  </main>
  <script src="{{ url_for('static', filename='app.js') }}"></script>
</body>
</html>
```

- [ ] **Step 2: Write the stylesheet**

Write `static/style.css`. Keep it minimal and unopinionated — visual design is deliberately deferred to a later `/frontend-design` pass:

```css
:root { color-scheme: light dark; --gap: 1rem; }
body { font-family: system-ui, sans-serif; margin: 0; padding: var(--gap);
       display: grid; place-items: center; min-height: 100vh; }
#app { width: min(600px, 100%); display: grid; gap: var(--gap); }
header { text-align: center; }
h1 { margin: 0; letter-spacing: -0.02em; }
#subtitle { margin: 0.25rem 0 var(--gap); opacity: 0.7; }
nav { display: flex; gap: 0.5rem; justify-content: center; }
button { padding: 0.6rem 1rem; border: 1px solid currentColor; border-radius: 6px;
         background: transparent; color: inherit; font: inherit; cursor: pointer; }
button.active { background: currentColor; }
button.active { color: canvas; }
#waveform { width: 100%; height: 80px; border: 1px solid; border-radius: 6px; }
#guess-form { display: flex; gap: 0.5rem; }
#guess-input { flex: 1; padding: 0.6rem; font: inherit; border-radius: 6px;
               border: 1px solid currentColor; background: transparent; color: inherit; }
.guess-row { display: flex; justify-content: space-between; padding: 0.4rem 0.6rem;
             border-bottom: 1px solid currentColor; }
#share-grid { font-size: 1.2rem; line-height: 1.4; }
#error { color: #c0392b; font-weight: 600; }
```

- [ ] **Step 3: Write the player and game loop**

Write `static/app.js`:

```javascript
"use strict";

const LADDER = [1, 2, 4, 7, 11, 16];
const MAX_GUESSES = 6;
const SEEN_KEY = "chronotune.seen";
const DAILY_KEY = "chronotune.daily";

const state = {
  mode: "daily",
  deezerId: null,
  puzzleNumber: null,
  guesses: [],
  bands: [],
  over: false,
};

let audioContext = null;
let audioBuffer = null;
let activeSource = null;

const $ = (id) => document.getElementById(id);

function showError(message) {
  const node = $("error");
  node.textContent = message;
  node.hidden = !message;
}

/* ---------- audio ---------- */

async function loadAudio(deezerId) {
  audioBuffer = null;
  const response = await fetch(`/api/audio/${deezerId}`);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || "Audio unavailable — try again.");
  }
  const { url } = await response.json();

  // The preview MP3 sends access-control-allow-origin: *, so Web Audio can
  // decode it directly — no proxy needed.
  const audio = await fetch(url);
  const bytes = await audio.arrayBuffer();

  audioContext = audioContext || new (window.AudioContext || window.webkitAudioContext)();
  audioBuffer = await audioContext.decodeAudioData(bytes);
  drawWaveform();
}

function playSnippet() {
  if (!audioBuffer) return;
  if (activeSource) activeSource.stop();

  const seconds = LADDER[Math.min(state.guesses.length, LADDER.length - 1)];
  activeSource = audioContext.createBufferSource();
  activeSource.buffer = audioBuffer;
  activeSource.connect(audioContext.destination);
  // Sample-accurate hard stop at the snippet boundary.
  activeSource.start(0, 0, seconds);
  animateProgress(seconds);
}

function drawWaveform(progressRatio = 0) {
  const canvas = $("waveform");
  const ctx = canvas.getContext("2d");
  const { width, height } = canvas;
  ctx.clearRect(0, 0, width, height);
  if (!audioBuffer) return;

  const unlocked = LADDER[Math.min(state.guesses.length, LADDER.length - 1)];
  const unlockedRatio = Math.min(unlocked / audioBuffer.duration, 1);

  const data = audioBuffer.getChannelData(0);
  const step = Math.floor(data.length / width);
  ctx.fillStyle = "currentColor";

  for (let x = 0; x < width; x++) {
    let peak = 0;
    for (let i = 0; i < step; i++) {
      peak = Math.max(peak, Math.abs(data[x * step + i] || 0));
    }
    const barHeight = Math.max(1, peak * height);
    const ratio = x / width;
    ctx.globalAlpha = ratio <= unlockedRatio ? 1 : 0.15;
    ctx.fillRect(x, (height - barHeight) / 2, 1, barHeight);
  }

  if (progressRatio > 0) {
    ctx.globalAlpha = 1;
    ctx.fillRect(progressRatio * width, 0, 2, height);
  }
  ctx.globalAlpha = 1;
}

function animateProgress(seconds) {
  const started = performance.now();
  const tick = (now) => {
    const elapsed = (now - started) / 1000;
    if (elapsed >= seconds || !audioBuffer) {
      drawWaveform();
      return;
    }
    drawWaveform(elapsed / audioBuffer.duration);
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

/* ---------- rounds ---------- */

async function startRound(attempt = 0) {
  state.guesses = [];
  state.bands = [];
  state.over = false;
  $("result").hidden = true;
  $("guess-form").hidden = false;
  $("guesses").innerHTML = "";
  showError("");

  try {
    let data;
    if (state.mode === "daily") {
      data = await (await fetch("/api/daily")).json();
      state.puzzleNumber = data.puzzle_number;
    } else {
      const seen = JSON.parse(localStorage.getItem(SEEN_KEY) || "[]");
      const response = await fetch("/api/infinite", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ seen }),
      });
      if (response.status === 409) {
        showError("You have played every track in the pool.");
        return;
      }
      data = await response.json();
    }

    state.deezerId = data.deezer_id;
    updateSnippetLabel();

    try {
      await loadAudio(state.deezerId);
    } catch (audioError) {
      // Infinite mode can substitute a different track; the daily cannot
      // without breaking determinism across players, so it reports honestly.
      if (state.mode === "infinite" && attempt < 3) {
        const seen = JSON.parse(localStorage.getItem(SEEN_KEY) || "[]");
        seen.push(state.deezerId);
        localStorage.setItem(SEEN_KEY, JSON.stringify(seen));
        return startRound(attempt + 1);
      }
      throw audioError;
    }
  } catch (error) {
    showError(error.message);
  }
}

function updateSnippetLabel() {
  $("snippet-length").textContent =
    LADDER[Math.min(state.guesses.length, LADDER.length - 1)];
}

function renderGuess(guess, result, band) {
  const arrow = result === "correct" ? "✓" : result === "later" ? "↑ later" : "↓ earlier";
  const row = document.createElement("div");
  row.className = "guess-row";
  row.innerHTML = `<span>${band} ${guess}</span><span>${arrow}</span>`;
  $("guesses").append(row);
}

async function submitGuess(year) {
  if (state.over) return;

  const response = await fetch("/api/guess", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      deezer_id: state.deezerId,
      guess: year,
      guess_number: state.guesses.length + 1,
    }),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    showError(body.error || "Something went wrong.");
    return;
  }

  const data = await response.json();
  state.guesses.push(year);
  state.bands.push(data.band);
  renderGuess(year, data.result, data.band);
  updateSnippetLabel();
  drawWaveform();

  if (data.answer !== undefined) {
    finishRound(data);
  } else {
    playSnippet();
  }
}

function finishRound(data) {
  state.over = true;
  $("guess-form").hidden = true;
  $("result").hidden = false;
  $("next").hidden = state.mode === "daily";

  const solved = data.result === "correct";
  $("reveal").textContent =
    `${solved ? "Got it" : "The answer was"} — ${data.artist} · ${data.title} (${data.answer})`;

  const padded = state.bands.concat(Array(MAX_GUESSES - state.bands.length).fill("⬜"));
  const summary = solved
    ? `Solved in ${state.guesses.length} · ${"🔊".repeat(state.guesses.length)}`
    : "X/6";
  const header = state.mode === "daily" ? `CHRONOTUNE #${state.puzzleNumber}` : "CHRONOTUNE ∞";
  $("share-grid").textContent = `${header}\n${padded.join("")}\n${summary}`;

  if (state.mode === "daily") {
    localStorage.setItem(DAILY_KEY, JSON.stringify({
      puzzleNumber: state.puzzleNumber,
      guesses: state.guesses,
      bands: state.bands,
    }));
  } else {
    const seen = JSON.parse(localStorage.getItem(SEEN_KEY) || "[]");
    seen.push(state.deezerId);
    localStorage.setItem(SEEN_KEY, JSON.stringify(seen));
  }
}

/* ---------- wiring ---------- */

$("play").addEventListener("click", playSnippet);

$("guess-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const value = Number.parseInt($("guess-input").value, 10);
  if (Number.isNaN(value)) return;
  $("guess-input").value = "";
  submitGuess(value);
});

$("skip").addEventListener("click", () => {
  // A skip is a deliberately impossible guess: it burns a turn and unlocks
  // more audio without giving directional information away.
  submitGuess(1900);
});

$("share").addEventListener("click", async () => {
  await navigator.clipboard.writeText($("share-grid").textContent);
  $("share").textContent = "Copied";
  setTimeout(() => ($("share").textContent = "Copy result"), 1500);
});

// Wrapped so the click Event is not passed in as `attempt`.
$("next").addEventListener("click", () => startRound());

for (const mode of ["daily", "infinite"]) {
  $(`mode-${mode}`).addEventListener("click", () => {
    state.mode = mode;
    $("mode-daily").classList.toggle("active", mode === "daily");
    $("mode-infinite").classList.toggle("active", mode === "infinite");
    startRound();
  });
}

startRound();
```

- [ ] **Step 4: Run the app and verify the loop by hand**

```bash
.venv/bin/python app.py
```

Open `http://127.0.0.1:5000`. Verify each of these:
1. A waveform renders and only the first ~1s is drawn at full opacity.
2. Play stops audibly at 1 second.
3. A wrong guess shows `↑ later` or `↓ earlier`, and the unlocked waveform region grows.
4. A correct guess reveals artist, title and year, and shows a share grid.
5. "Copy result" puts the grid on the clipboard, and the copied text contains no year.
6. Infinite mode serves a different track and shows a "Next track" button.

- [ ] **Step 5: Run the full test suite**

Run: `.venv/bin/pytest`
Expected: PASS, all tests green.

- [ ] **Step 6: Commit**

```bash
git add templates/index.html static/app.js static/style.css
git commit -m "feat: add Web Audio player, guess UI and share grid"
```

---

### Task 13: Grow the pool and document the project

**Files:**
- Modify: `data/seeds.txt`
- Create: `README.md`

**Interfaces:**
- Consumes: `tools/build_tracks.py`
- Produces: a populated `data/tracks.json` and `data/daily_order.json`

- [ ] **Step 1: Expand the seed list**

Add seeds to `data/seeds.txt`, spreading across decades so the game does not become a single-era quiz. Target ~550 lines to land ~400 accepted tracks at the observed ~73% acceptance rate. Keep the existing lines in place and append below them.

Practical sourcing: year-end singles charts per decade, "best of" lists, and personal favourites. Every line must be `Artist - Title` with the canonical studio-single title — no "(Live)", "(Remix)" or "(Remastered)" suffixes, since those are rejected by design.

- [ ] **Step 2: Run the builder**

```bash
.venv/bin/python tools/build_tracks.py --seeds data/seeds.txt
```

Expected: roughly 70% accepted. This is slow — at 1 request/second to MusicBrainz, 550 seeds takes about 20 minutes. The builder is resumable, so interrupting and rerunning is safe.

- [ ] **Step 3: Review the rejects**

```bash
.venv/bin/python -c "
import json, collections
rejects = json.load(open('data/rejects.json'))
print(collections.Counter(r['reason'] for r in rejects))
for r in rejects[:20]:
    print(' ', r['reason'], '|', r['artist'], '-', r['title'])
"
```

Expected: mostly `wd_missing` (Wikidata coverage thins outside well-known releases) and `year_conflict`. A large `no_deezer_match` count suggests seed titles are misspelled or carry variant suffixes — fix those lines and rerun.

- [ ] **Step 4: Verify the pool loads and the daily is stable**

```bash
.venv/bin/python -c "
from datetime import date
from chronotune.store import load_pool
from chronotune.puzzle import daily_track_id, puzzle_number
pool = load_pool('data/tracks.json', 'data/daily_order.json')
print(len(pool), 'tracks,', len(pool.daily_order), 'daily slots')
today = date.today()
print('puzzle #', puzzle_number(today), '->', pool.by_id(daily_track_id(pool, today)))
"
```

Expected: the pool loads without a `PoolError`, and today's puzzle resolves to a real track.

- [ ] **Step 5: Write the README**

Write `README.md`:

```markdown
# Chronotune

A daily music game. A snippet plays; you guess the year the track was released.
Each wrong guess unlocks more audio and narrows the range. Results share as an
emoji grid. Infinite mode drops the daily constraint.

## Running

    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
    .venv/bin/python app.py

Then open http://127.0.0.1:5000

## Tests

    .venv/bin/pytest

The suite never touches the network — every network call is injected.

## Growing the track pool

Add `Artist - Title` lines to `data/seeds.txt`, then:

    .venv/bin/python tools/build_tracks.py --seeds data/seeds.txt

A track is accepted only when **MusicBrainz and Wikidata agree on the year**.
Deezer decides availability and supplies the audio but gets no vote on the year —
its `release_date` reflects whichever album edition the search lands on (it dates
Billie Jean to 2009). Expect roughly 70% of seeds to survive.

Rejections land in `data/rejects.json` with a reason.

### daily_order.json is append-only

`data/daily_order.json` fixes which track each day serves. The builder only ever
appends to it. Reordering or removing entries would change the song players got
on days they have already played and invalidate every shared grid, so the builder
refuses to write such a change and the app refuses to start on an inconsistent file.

## Design

See `docs/superpowers/specs/2026-08-14-chronotune-design.md`.
```

- [ ] **Step 6: Run the full suite and commit**

```bash
.venv/bin/pytest
git add data/seeds.txt data/tracks.json data/daily_order.json data/rejects.json README.md
git commit -m "feat: grow curated track pool and document the project"
```

---

## Deferred

Out of scope for this plan, per the spec:

- Spotify stream-count mode — no free or licit data source exists.
- YouTube embed audio fallback — Deezer previews need no extraction.
- Accounts, server-side persistence, leaderboards.
- Visual design beyond the functional player — handled by a later `/frontend-design` pass against the running app.
