"use strict";

/* Serverless backend for the GitHub Pages build.
 *
 * Same four calls as api-server.js, resolved in the browser instead. Two
 * things have to be solved without a server:
 *
 * 1. The answers. They ship inside pool.json, sealed per track. See vault.py
 *    for what that does and does not buy.
 * 2. The audio. api.deezer.com sends no access-control-allow-origin, so fetch
 *    is blocked outright, but it still honours JSONP. The preview MP3 it
 *    points at *does* send `access-control-allow-origin: *`, so once the URL
 *    is in hand Web Audio can decode it directly, same as under Flask.
 *
 * Rules are not restated here. The ladder, guess ceiling, epoch and proximity
 * boundaries are all baked into pool.json from chronotune/game.py and
 * chronotune/puzzle.py at build time, so Python stays the only definition.
 */

const POOL_URL = "pool.json";
const DEEZER_TRACK_URL = "https://api.deezer.com/track";
const JSONP_TIMEOUT_MS = 10000;

const MIN_YEAR = 1900;
const MAX_YEAR = 2100;

let poolPromise = null;

function loadPool() {
  // One fetch per page load, shared by every later call.
  poolPromise =
    poolPromise ||
    fetch(POOL_URL).then((response) => {
      if (!response.ok) throw new Error("Could not load the track pool.");
      return response.json();
    });
  return poolPromise;
}

/* ---------- puzzle selection (port of chronotune/puzzle.py) ---------- */

function daysSinceEpoch(pool) {
  const [y, m, d] = pool.epoch.split("-").map(Number);
  const epoch = Date.UTC(y, m - 1, d);

  // The player's local calendar day, projected onto UTC midnight. Subtracting
  // two UTC midnights makes the difference exact whole days, which plain local
  // Date arithmetic would not be across a DST boundary.
  const now = new Date();
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());

  return Math.round((today - epoch) / 86400000);
}

/* ---------- answers ---------- */

function trackFor(pool, deezerId) {
  const entry = pool.tracks.find((t) => t.id === deezerId);
  if (!entry) throw new Error("unknown track");
  // Decoded on demand, never up front. An eager pass would leave all 100-odd
  // answers sitting in plaintext in a live object for the whole session.
  return unseal(entry.id, entry.sealed);
}

function evaluateGuess(guess, answer) {
  if (guess === answer) return "correct";
  return guess < answer ? "later" : "earlier";
}

function proximityBand(pool, guess, answer) {
  const distance = Math.abs(guess - answer);
  for (const [limit, band] of pool.proximity_bands) {
    if (distance <= limit) return band;
  }
  return pool.far_band;
}

/* ---------- audio ---------- */

let jsonpSeq = 0;

function jsonp(url) {
  return new Promise((resolve, reject) => {
    const callback = `__chronotune_jsonp_${Date.now()}_${jsonpSeq++}`;
    const script = document.createElement("script");
    let timer = null;

    const cleanup = () => {
      clearTimeout(timer);
      delete window[callback];
      script.remove();
    };

    window[callback] = (payload) => {
      cleanup();
      resolve(payload);
    };
    script.onerror = () => {
      cleanup();
      reject(new Error("Deezer request failed."));
    };
    // A JSONP script that never calls back fires no error event either, so
    // without this the promise would hang forever and the round would sit on
    // a dead deck.
    timer = setTimeout(() => {
      cleanup();
      reject(new Error("Deezer request timed out."));
    }, JSONP_TIMEOUT_MS);

    script.src = `${url}${url.includes("?") ? "&" : "?"}output=jsonp&callback=${callback}`;
    document.head.append(script);
  });
}

async function resolvePreviewUrl(deezerId, attempts = 2) {
  let lastError = null;

  for (let i = 0; i < attempts; i++) {
    try {
      const payload = await jsonp(`${DEEZER_TRACK_URL}/${deezerId}`);
      if (payload && payload.preview) return payload.preview;
      lastError = new Error(`track ${deezerId} has no preview`);
    } catch (error) {
      lastError = error;
    }
  }
  throw new Error("Audio unavailable. Try again.", { cause: lastError });
}

/* ---------- the four calls ---------- */

window.ChronotuneAPI = {
  async daily() {
    const pool = await loadPool();
    const elapsed = daysSinceEpoch(pool);
    const order = pool.daily_order;

    // Python's % is always non-negative; JS's is not. Someone playing with a
    // clock set before the epoch would otherwise index out of the array.
    const index = ((elapsed % order.length) + order.length) % order.length;

    return {
      deezer_id: order[index],
      puzzle_number: elapsed + 1,
      max_guesses: pool.max_guesses,
      ladder: pool.ladder,
    };
  },

  async infinite(seen) {
    const pool = await loadPool();
    const seenSet = new Set(seen);
    const candidates = pool.tracks
      .map((t) => t.id)
      .filter((id) => !seenSet.has(id));

    if (!candidates.length) return { exhausted: true };

    return {
      deezer_id: candidates[Math.floor(Math.random() * candidates.length)],
      max_guesses: pool.max_guesses,
      ladder: pool.ladder,
    };
  },

  async audioUrl(deezerId) {
    const pool = await loadPool();
    if (!pool.tracks.some((t) => t.id === deezerId)) {
      throw new Error("unknown track");
    }
    return resolvePreviewUrl(deezerId);
  },

  async guess({ deezerId, guess, guessNumber }) {
    const pool = await loadPool();

    if (!Number.isInteger(guess) || guess < MIN_YEAR || guess > MAX_YEAR) {
      throw new Error(`guess must be between ${MIN_YEAR} and ${MAX_YEAR}`);
    }

    const track = trackFor(pool, deezerId);
    const result = evaluateGuess(guess, track.year);
    const over = result === "correct" || guessNumber >= pool.max_guesses;

    const payload = {
      result,
      band: proximityBand(pool, guess, track.year),
      snippet_seconds: pool.ladder[Math.min(guessNumber, pool.max_guesses - 1)],
    };
    if (over) {
      payload.answer = track.year;
      payload.artist = track.artist;
      payload.title = track.title;
    }
    return payload;
  },
};
