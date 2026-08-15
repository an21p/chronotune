"""Obfuscate the answers shipped to a static build.

The Flask app withholds ``track.year`` until a round is over, so it never
reaches the client early. A static build has no server to withhold anything:
``tracks.json`` would have to ship whole, answers included, one Ctrl-F away.

This is not a fix for that. It cannot be: the browser must be able to decode
every answer, so the key travels with the ciphertext and anyone determined can
follow it. What it buys is that the shipped file is not *readable*: no years,
no titles in plain sight, nothing a curious player stumbles into by opening
devtools or viewing the JSON. Defeating it is deliberate work, which for a
guessing game is the whole bar.

Do not reach for this anywhere the secret actually matters.

The keystream is xorshift32 seeded from the track id. ``vault.js`` implements
the same generator byte for byte, and ``test_vault.py`` runs both and asserts
they agree. That cross-language pin is the only thing keeping them honest.
"""

from __future__ import annotations

import base64
import json

# Mixed into the seed so the keystream is not simply a function of a public
# Deezer id. Public by construction, since it ships in vault.js.
SALT = 0x43484E54  # "CHNT"

MASK = 0xFFFFFFFF


def keystream(seed: int, length: int) -> bytes:
    """`length` bytes of xorshift32 output.

    A zero state is xorshift's fixed point: it would emit an all-zero stream
    and turn the XOR into a no-op, publishing the plaintext. Seed 0 is
    reachable (a track id equal to SALT), so it is redirected.
    """
    state = (seed ^ SALT) & MASK or 0x9E3779B9

    out = bytearray(length)
    for i in range(length):
        state = (state ^ (state << 13)) & MASK
        state ^= state >> 17
        state = (state ^ (state << 5)) & MASK
        out[i] = state & 0xFF
    return bytes(out)


def _xor(data: bytes, seed: int) -> bytes:
    return bytes(a ^ b for a, b in zip(data, keystream(seed, len(data))))


def seal(seed: int, payload: dict) -> str:
    """Encode `payload` as base64 ciphertext bound to `seed`."""
    # Compact + sorted so the output is byte-stable across builds; an unstable
    # encoding would churn the diff of every rebuilt pool.json.
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(_xor(raw, seed)).decode("ascii")


def unseal(seed: int, sealed: str) -> dict:
    """Inverse of `seal`. Used by tests; the client uses vault.js."""
    return json.loads(_xor(base64.b64decode(sealed), seed).decode("utf-8"))
