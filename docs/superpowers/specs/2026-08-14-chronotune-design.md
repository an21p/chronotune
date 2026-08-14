# Chronotune — Design

**Date:** 2026-08-14
**Status:** Approved

## Summary

A daily music guessing game. A snippet of a track plays; the player guesses the year it
was released. Each wrong guess unlocks more audio and narrows the range. Results share as
a Wordle-style emoji grid. An infinite mode drops the daily constraint and tracks a streak.

Python Flask prototype. No database. Audio comes from Deezer's free 30-second preview
MP3s. The song pool is curated offline by a reusable builder script.

## Research findings

These determined the design and are recorded because they are non-obvious.

**Spotify stream counts are unavailable.** The Spotify Web API has never exposed a play
count endpoint and exposes only a relative `popularity` score (0–100). Real stream numbers
require scraping or paid third parties. The originally-proposed "streamguesser" mode is
therefore out of scope.

**Deezer's `release_date` is unreliable and gets no vote on the year.** It reflects
whichever album edition a search lands on, which for catalogue artists is usually a
remaster or compilation. Measured against 15 well-known tracks:

| Track | Deezer | MusicBrainz | Wikidata | Truth |
|---|---|---|---|---|
| Billie Jean | 2009 | 1982 | 1982 | 1982 |
| Bohemian Rhapsody | 2005 | 1975 | 1975 | 1975 |
| Smells Like Teen Spirit | 2011 | 1991 | 1991 | 1991 |
| Mr. Brightside | 2006 | 2003 | 2003 | 2003 |

Requiring all three sources to agree yielded **3/15 (20%)** and discarded correct tracks.
Requiring only MusicBrainz and Wikidata to agree yielded **11/15 (73%)**, and all 11 were
independently verified correct.

**Wikidata fails safe.** When it lacks data it returns nothing rather than a wrong year,
so it cannot silently poison the pool. MusicBrainz recording-level search *can* return
wrong years (it dated Daft Punk's "Around the World" to 2004; the answer is 1997), so the
builder queries **release-groups**, not recordings.

**Deezer preview MP3s are directly usable.** No auth, no key. They serve
`access-control-allow-origin: *`, enabling Web Audio API use without a proxy. URLs carry
an expiry token with roughly a 7-hour life, so they must be resolved per-request and never
cached.

**Re-recordings are genuinely ambiguous.** a-ha's "Take On Me" was released in 1984, but
the famous version — and the one Deezer streams — is the 1985 re-recording. Rule: the
answer is the year of the version the player hears, since that is all they can judge from
audio. Conflicts beyond the two-source consensus are rejected rather than guessed at.

## Architecture

Stateless Flask server, no database. Player progress lives in `localStorage`. The server
serves puzzles, resolves audio URLs, and validates guesses.

```
chronotune/
  app.py                    # Flask app factory + routes
  chronotune/
    game.py                 # guess evaluation, snippet ladder, proximity bands
    puzzle.py               # date -> deterministic track selection
    deezer.py               # preview URL resolution at serve time
    share.py                # emoji grid generation
    store.py                # tracks.json loading + indexing
  tools/
    build_tracks.py         # the builder
    sources/
      deezer.py             # availability, track id, preview check
      musicbrainz.py        # release-group first-release-date
      wikidata.py           # earliest P577
  data/
    seeds.txt               # input: "Artist - Title" per line
    tracks.json             # curated pool (committed)
    daily_order.json        # append-only daily sequence (committed)
    rejects.json            # rejected tracks + reason (committed)
  templates/ static/
  tests/
```

**Boundary that matters:** `tools/` never imports from `chronotune/`, and `chronotune/`
never calls MusicBrainz or Wikidata. Curation is build-time; gameplay is runtime;
`tracks.json` is the only contract between them. This is what allows the pool to grow by
rerunning the builder without touching game code.

## The builder

```bash
python tools/build_tracks.py --seeds data/seeds.txt --out data/tracks.json
```

Per seed:

1. Loose Deezer search (`q=<artist> <title>`), then filter results by fuzzy artist and
   title match. Strict field syntax (`artist:"…" track:"…"`) is **not** used — it silently
   returned nothing for Daft Punk where loose search succeeded.
2. Require a non-empty `preview` field.
3. MusicBrainz release-group search → earliest `first-release-date`.
4. Wikidata SPARQL → earliest `P577` for a matching song by that performer.
5. Accept only if MusicBrainz year == Wikidata year.

Rejections are written to `rejects.json` with a reason: `no_deezer_match`, `no_preview`,
`mb_missing`, `wd_missing`, `year_conflict`.

Operational requirements:

- **Incremental** — keyed on normalised `artist|title`; reruns skip already-accepted
  tracks. `--refresh` forces re-evaluation.
- **Cached** — raw API responses cached under `.cache/`, so adding 20 seeds to a 400-track
  pool costs 20 lookups, not 400.
- **Rate-limited** — MusicBrainz at 1 request/second (their published rule) with a
  descriptive User-Agent; Wikidata polite; both with retry and backoff.
- **Resumable** — output written after each acceptance so a crash does not lose progress.

Accepted track record:

```json
{
  "deezer_id": 3129775,
  "artist": "Daft Punk",
  "title": "Around the World",
  "year": 1997,
  "sources": { "musicbrainz": 1997, "wikidata": 1997 }
}
```

Source years are retained for auditability. The preview URL is deliberately **not** stored,
because it expires.

## Gameplay

Six guesses per round. Snippet ladder in seconds: **1, 2, 4, 7, 11, 16**. Each wrong guess
unlocks the next step.

Feedback per guess is directional: `↑ later` or `↓ earlier`, or correct.

Proximity bands, used only for the share grid:

| Band | Meaning |
|---|---|
| 🟩 | correct |
| 🟨 | within 2 years |
| 🟧 | within 10 years |
| 🟥 | more than 10 years off |
| ⬜ | guess not used (round solved earlier) |

**Daily mode.** Day N serves `daily_order[N % len(daily_order)]`, where `daily_order` is an
explicit, committed list of Deezer track IDs in `data/daily_order.json`.

This is a separate file rather than a shuffle of `tracks.json` on purpose. A seeded shuffle
would be recomputed over the whole pool, so every builder rerun that adds tracks would
reorder the sequence and change which song people get on a given day — including days
already played. Instead the builder **appends** newly accepted track IDs to the end of
`daily_order` and never reorders existing entries. Growing the pool then only extends the
tail, leaving past and near-future dailies untouched.

Deterministic, identical for all players, no repeats until the list wraps, and no server
state. A 400-track list is over a year of dailies.

**Append-only is an enforced invariant, not a convention.** Violating it silently rewrites
history — players who already solved day 12 would see a different song there, and shared
grids would stop matching. It is therefore guarded in three places:

1. **Before writing**, the builder asserts that the existing file's contents are an exact
   prefix of the new list. Any reorder, edit, or removal aborts the write with a non-zero
   exit and a diff of the first divergent index. `--refresh` does not exempt this;
   re-evaluating a track's *year* is allowed, changing its *position* is not.
2. **At startup**, the app validates that every ID in `daily_order` resolves to a track in
   `tracks.json`, and fails loudly if not.
3. **In tests**, a regression test loads a frozen fixture of an earlier `daily_order`,
   runs an append, and asserts the prefix is byte-identical.

A track rejected on a later rerun is *not* removed from `daily_order`; removal would shift
every subsequent day. It stays, and the startup check surfaces it as a hard error to be
resolved deliberately.

**Infinite mode.** The client keeps a seen-list in `localStorage` and posts it; the server
returns a random unseen track. Same guess loop, no share grid, tracks a streak instead.

**Share format** is generated client-side from guess history — no server call:

```
CHRONOTUNE #142
🟥🟥🟩⬜⬜⬜
Solved in 3 · 🔊🔊🔊
```

## Audio

`tracks.json` stores only the Deezer track ID. `GET /api/round/<id>/audio` resolves a fresh
preview URL per request.

Because the MP3 serves `access-control-allow-origin: *`, the custom player uses the Web
Audio API directly: real waveform rendering and a sample-accurate hard stop at the snippet
boundary, with no Flask proxy in the path.

Client-side enforcement of the snippet limit is not tamper-proof. This is accepted — it is
a game, and the cost of defeating it exceeds the reward.

## Error handling

| Failure | Behaviour |
|---|---|
| Preview URL resolution fails | Retry once. Then surface an explicit "audio unavailable" state. |
| Daily track unplayable | Show the error. Substituting would break cross-player determinism. |
| Infinite track unplayable | Client requests a different track. |
| `tracks.json` missing or empty | Fail loudly at startup, not at first request. |
| `daily_order` entry missing from `tracks.json` | Fail loudly at startup. Never silently skip — skipping shifts every later day. |
| Builder would reorder `daily_order` | Abort the write, non-zero exit, report first divergent index. |
| Malformed guess (non-integer, out of range) | Rejected server-side with a 400; the client constrains input too. |

## Testing

`pytest`, with **no network access in the suite**.

- Guess evaluation, snippet ladder, proximity banding, share-grid generation and daily
  selection are pure functions, tested directly.
- The three source adapters are tested against recorded fixtures captured from the research
  spike, including the known-difficult cases: Billie Jean (Deezer says 2009), Take On Me
  (1984 vs 1985), Creep and Never Gonna Give You Up (Wikidata absent), and Lose Yourself
  (both sources absent). These keep the reject logic honest as the builder evolves.
- Daily determinism is tested by asserting the same date yields the same track across
  independent invocations.

## Out of scope

- Spotify stream-count mode — no free or licit data source exists.
- YouTube embed audio fallback — deferred; Deezer previews require no extraction.
- Accounts, server-side persistence, leaderboards.
- Visual design beyond a functional player. Handled separately via `/frontend-design`
  once the prototype runs.
