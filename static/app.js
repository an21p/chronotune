"use strict";

const LADDER = [1, 2, 4, 7, 11, 16];
const MAX_GUESSES = 6;
const UNUSED = "⬜";
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
  node.textContent = message || "";
  node.hidden = !message;
}

function readJSON(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? fallback : JSON.parse(raw);
  } catch {
    // Corrupt or unavailable storage must not brick the game.
    return fallback;
  }
}

function writeJSON(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* private mode or quota — progress just won't persist */
  }
}

function unlockedSeconds() {
  return LADDER[Math.min(state.guesses.length, LADDER.length - 1)];
}

/* ---------- audio ---------- */

async function loadAudio(deezerId) {
  audioBuffer = null;
  drawWaveform();

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
  if (activeSource) {
    try { activeSource.stop(); } catch { /* already stopped */ }
  }
  // Browsers start the context suspended until a user gesture.
  if (audioContext.state === "suspended") audioContext.resume();

  const seconds = unlockedSeconds();
  activeSource = audioContext.createBufferSource();
  activeSource.buffer = audioBuffer;
  activeSource.connect(audioContext.destination);
  // Sample-accurate hard stop at the snippet boundary.
  activeSource.start(0, 0, seconds);
  animateProgress(seconds);
}

function drawWaveform(progressSeconds = 0) {
  const canvas = $("waveform");
  const ctx = canvas.getContext("2d");
  const { width, height } = canvas;
  ctx.clearRect(0, 0, width, height);
  if (!audioBuffer) return;

  const unlockedRatio = Math.min(unlockedSeconds() / audioBuffer.duration, 1);
  const data = audioBuffer.getChannelData(0);
  const step = Math.max(1, Math.floor(data.length / width));
  ctx.fillStyle = "currentColor";

  for (let x = 0; x < width; x++) {
    let peak = 0;
    for (let i = 0; i < step; i++) {
      peak = Math.max(peak, Math.abs(data[x * step + i] || 0));
    }
    const barHeight = Math.max(1, peak * height);
    ctx.globalAlpha = x / width <= unlockedRatio ? 1 : 0.15;
    ctx.fillRect(x, (height - barHeight) / 2, 1, barHeight);
  }

  if (progressSeconds > 0) {
    ctx.globalAlpha = 1;
    ctx.fillRect((progressSeconds / audioBuffer.duration) * width, 0, 2, height);
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
    drawWaveform(elapsed);
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
  $("guess-input").value = "";
  showError("");
  updateSnippetLabel();

  try {
    let data;
    if (state.mode === "daily") {
      const response = await fetch("/api/daily");
      if (!response.ok) throw new Error("Could not load today's puzzle.");
      data = await response.json();
      state.puzzleNumber = data.puzzle_number;
    } else {
      const response = await fetch("/api/infinite", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ seen: readJSON(SEEN_KEY, []) }),
      });
      if (response.status === 409) {
        showError("You have played every track in the pool.");
        $("guess-form").hidden = true;
        return;
      }
      if (!response.ok) throw new Error("Could not load a track.");
      data = await response.json();
    }

    state.deezerId = data.deezer_id;

    try {
      await loadAudio(state.deezerId);
    } catch (audioError) {
      // Infinite mode can substitute a different track; the daily cannot
      // without breaking determinism across players, so it reports honestly.
      if (state.mode === "infinite" && attempt < 3) {
        const seen = readJSON(SEEN_KEY, []);
        seen.push(state.deezerId);
        writeJSON(SEEN_KEY, seen);
        return startRound(attempt + 1);
      }
      throw audioError;
    }
  } catch (error) {
    showError(error.message);
  }
}

function updateSnippetLabel() {
  $("snippet-length").textContent = unlockedSeconds();
}

function renderGuess(guess, result, band) {
  const arrow = result === "correct" ? "✓" : result === "later" ? "↑ later" : "↓ earlier";
  const row = document.createElement("div");
  row.className = "guess-row";
  const left = document.createElement("span");
  left.textContent = `${band} ${guess}`;
  const right = document.createElement("span");
  right.textContent = arrow;
  row.append(left, right);
  $("guesses").append(row);
}

async function submitGuess(year) {
  if (state.over || state.deezerId === null) return;

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

  showError("");
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

function buildShareText() {
  const padded = state.bands
    .slice(0, MAX_GUESSES)
    .concat(Array(Math.max(0, MAX_GUESSES - state.bands.length)).fill(UNUSED));
  const solved = state.bands.includes("\u{1F7E9}");
  const summary = solved
    ? `Solved in ${state.guesses.length} · ${"\u{1F50A}".repeat(state.guesses.length)}`
    : "X/6";
  const header =
    state.mode === "daily" ? `CHRONOTUNE #${state.puzzleNumber}` : "CHRONOTUNE ∞";
  return `${header}\n${padded.join("")}\n${summary}`;
}

function finishRound(data) {
  state.over = true;
  $("guess-form").hidden = true;
  $("result").hidden = false;
  $("next").hidden = state.mode === "daily";

  const solved = data.result === "correct";
  $("reveal").textContent =
    `${solved ? "Got it" : "The answer was"} — ${data.artist} · ${data.title} (${data.answer})`;
  $("share-grid").textContent = buildShareText();

  if (state.mode === "daily") {
    writeJSON(DAILY_KEY, {
      puzzleNumber: state.puzzleNumber,
      guesses: state.guesses,
      bands: state.bands,
    });
  } else {
    const seen = readJSON(SEEN_KEY, []);
    if (!seen.includes(state.deezerId)) seen.push(state.deezerId);
    writeJSON(SEEN_KEY, seen);
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

// A skip burns a turn and unlocks more audio. 1900 is outside any plausible
// answer, so the directional hint it earns gives nothing away.
$("skip").addEventListener("click", () => submitGuess(1900));

$("share").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("share-grid").textContent);
    $("share").textContent = "Copied";
  } catch {
    $("share").textContent = "Press ⌘C to copy";
  }
  setTimeout(() => ($("share").textContent = "Copy result"), 1500);
});

// Wrapped so the click Event is not passed in as `attempt`.
$("next").addEventListener("click", () => startRound());

for (const mode of ["daily", "infinite"]) {
  $(`mode-${mode}`).addEventListener("click", () => {
    if (state.mode === mode) return;
    state.mode = mode;
    $("mode-daily").classList.toggle("active", mode === "daily");
    $("mode-infinite").classList.toggle("active", mode === "infinite");
    startRound();
  });
}

startRound();
