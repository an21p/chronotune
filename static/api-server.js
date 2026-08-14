"use strict";

/* Flask backend. Every rule lives on the server; this is a thin wire.
 *
 * The static build swaps in api-static.js instead. app.js talks only to
 * window.ChronotuneAPI and never knows which one it got.
 */

async function readOr(response, fallback) {
  const body = await response.json().catch(() => ({}));
  return body.error || fallback;
}

window.ChronotuneAPI = {
  async daily() {
    const response = await fetch("/api/daily");
    if (!response.ok) throw new Error("Could not load today's puzzle.");
    return response.json();
  },

  async infinite(seen) {
    const response = await fetch("/api/infinite", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ seen }),
    });
    // 409 means the pool is exhausted — a normal end state, not a failure, so
    // it is signalled in the payload rather than thrown.
    if (response.status === 409) return { exhausted: true };
    if (!response.ok) throw new Error("Could not load a track.");
    return response.json();
  },

  async audioUrl(deezerId) {
    const response = await fetch(`/api/audio/${deezerId}`);
    if (!response.ok) {
      throw new Error(await readOr(response, "Audio unavailable — try again."));
    }
    const { url } = await response.json();
    return url;
  },

  async guess({ deezerId, guess, guessNumber }) {
    const response = await fetch("/api/guess", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        deezer_id: deezerId,
        guess,
        guess_number: guessNumber,
      }),
    });
    if (!response.ok) {
      throw new Error(await readOr(response, "Something went wrong."));
    }
    return response.json();
  },
};
