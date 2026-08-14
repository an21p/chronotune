"use strict";

/* The deck. Knows nothing about where puzzles come from: every call goes to
 * window.ChronotuneAPI, which is api-server.js under Flask and api-static.js
 * in the GitHub Pages build. One UI, two backends, no forked copy. */

// Defaults only. Both are replaced by the values the API sends with every
// round, so the ladder is defined once — in chronotune/game.py.
let LADDER = [1, 5, 10, 15, 20, 25];
let MAX_GUESSES = 6;
const UNUSED = "⬜";
// Kept in step with PLAY_URL in chronotune/share.py — a test pins the two.
const PLAY_URL = "https://an21p.github.io/chronotune/";
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

  const url = await window.ChronotuneAPI.audioUrl(deezerId);

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

/* The tape stripe: unlocked audio is inked in oxide and amber, the rest of the
   reel is still sealed. Colours come from style.css so the two never drift. */
const readToken = (name) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function drawWaveform(progressSeconds = 0) {
  const canvas = $("waveform");
  const ctx = canvas.getContext("2d");
  const { width, height } = canvas;
  ctx.clearRect(0, 0, width, height);

  const oxide = readToken("--oxide") || "#7A5230";
  const amber = readToken("--amber") || "#F0A93B";
  const sealed = "#2A2E34";

  if (!audioBuffer) {
    // An empty deck still shows the reel, so the panel never looks broken.
    ctx.fillStyle = sealed;
    for (let x = 0; x < width; x += 4) ctx.fillRect(x, height / 2 - 1, 1, 2);
    return;
  }

  const unlockedRatio = Math.min(unlockedSeconds() / audioBuffer.duration, 1);
  const data = audioBuffer.getChannelData(0);
  const step = Math.max(1, Math.floor(data.length / width));

  for (let x = 0; x < width; x++) {
    let peak = 0;
    for (let i = 0; i < step; i++) {
      peak = Math.max(peak, Math.abs(data[x * step + i] || 0));
    }
    const barHeight = Math.max(1, peak * height);
    const unlocked = x / width <= unlockedRatio;
    ctx.fillStyle = unlocked ? (x % 3 === 0 ? amber : oxide) : sealed;
    ctx.globalAlpha = unlocked ? 1 : 0.55;
    ctx.fillRect(x, (height - barHeight) / 2, 1, barHeight);
  }

  ctx.globalAlpha = 1;
  if (progressSeconds > 0) {
    // The playhead, the one thing on the panel that moves.
    const x = (progressSeconds / audioBuffer.duration) * width;
    ctx.fillStyle = amber;
    ctx.shadowColor = amber;
    ctx.shadowBlur = 12;
    ctx.fillRect(x, 0, 2, height);
    ctx.shadowBlur = 0;
  }
}

function setTransport(elapsed) {
  const total = unlockedSeconds();
  $("vu-fill").style.width = `${Math.min(elapsed / total, 1) * 100}%`;
  $("secs").textContent = Math.min(elapsed, total).toFixed(1).padStart(4, "0");
}

function animateProgress(seconds) {
  const started = performance.now();
  const tick = (now) => {
    const elapsed = (now - started) / 1000;
    if (elapsed >= seconds || !audioBuffer) {
      drawWaveform();
      setTransport(0);
      return;
    }
    drawWaveform(elapsed);
    setTransport(elapsed);
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

/* ---------- odometer ---------- */

// The wells are a readout of #guess-input, never a second source of truth.
function renderOdometer(value = $("guess-input").value) {
  const typed = String(value).slice(0, 4);
  const wells = $("odo").children;

  for (let i = 0; i < wells.length; i++) {
    const well = wells[i];
    const char = typed[i];
    const filled = char !== undefined;
    const next = filled ? char : "–";

    if (well.textContent !== next) {
      well.textContent = next;
      if (filled) {
        well.classList.remove("landed");
        void well.offsetWidth; // restart the drop animation
        well.classList.add("landed");
      }
    }
    well.classList.toggle("empty", !filled);
  }
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
  $("remaining").hidden = false;
  showError("");
  updateSnippetLabel();
  renderOdometer();
  renderRemaining();
  setTransport(0);
  drawWaveform();

  try {
    let data;
    if (state.mode === "daily") {
      data = await window.ChronotuneAPI.daily();
      state.puzzleNumber = data.puzzle_number;
      $("puzzle-no").textContent = `DAILY ${state.puzzleNumber}`;
    } else {
      $("puzzle-no").textContent = "INFINITE";
      data = await window.ChronotuneAPI.infinite(readJSON(SEEN_KEY, []));
      if (data.exhausted) {
        showError("You have played every track in the pool.");
        $("guess-form").hidden = true;
        return;
      }
    }

    state.deezerId = data.deezer_id;
    if (Array.isArray(data.ladder) && data.ladder.length) LADDER = data.ladder;
    if (Number.isInteger(data.max_guesses)) MAX_GUESSES = data.max_guesses;
    updateSnippetLabel();
    renderRemaining();

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
  const seconds = unlockedSeconds();
  $("snippet-length").textContent = seconds;
  $("secs").textContent = seconds.toFixed(1).padStart(4, "0");
}

function renderRemaining() {
  const left = MAX_GUESSES - state.guesses.length;
  $("remaining").querySelector(".dir").textContent =
    left === 1 ? "1 left" : `${left} left`;
  $("remaining").hidden = left <= 0;
}

function renderGuess(guess, result, band) {
  const reading = result === "correct" ? "Match" : result === "later" ? "Later ↑" : "Earlier ↓";
  const row = document.createElement("div");
  row.className = result === "correct" ? "row solved" : "row";

  const left = document.createElement("span");
  const chip = document.createElement("span");
  chip.className = "band";
  chip.textContent = band;
  left.append(chip, document.createTextNode(String(guess)));

  const right = document.createElement("span");
  right.className = "dir";
  right.textContent = reading;

  row.append(left, right);
  $("guesses").append(row);
}

async function submitGuess(year) {
  if (state.over || state.deezerId === null) return;

  let data;
  try {
    data = await window.ChronotuneAPI.guess({
      deezerId: state.deezerId,
      guess: year,
      guessNumber: state.guesses.length + 1,
    });
  } catch (error) {
    showError(error.message || "Something went wrong.");
    return;
  }

  showError("");
  state.guesses.push(year);
  state.bands.push(data.band);
  renderGuess(year, data.result, data.band);
  renderRemaining();
  updateSnippetLabel();
  renderOdometer();
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
  return `${header}\n${padded.join("")}\n${summary}\n${PLAY_URL}`;
}

function finishRound(data) {
  state.over = true;
  $("guess-form").hidden = true;
  $("remaining").hidden = true;
  $("result").hidden = false;
  $("next").hidden = state.mode === "daily";

  // The counter lands on the real year — the round's payoff.
  renderOdometer(data.answer);

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

// Wrapped so the input Event is not passed in as the value to render.
$("guess-input").addEventListener("input", () => renderOdometer());

$("guess-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const value = Number.parseInt($("guess-input").value, 10);
  if (Number.isNaN(value)) return;
  $("guess-input").value = "";
  renderOdometer();
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
    $("mode-daily").classList.toggle("on", mode === "daily");
    $("mode-infinite").classList.toggle("on", mode === "infinite");
    startRound();
  });
}

startRound();
