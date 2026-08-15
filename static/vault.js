"use strict";

/* Decoder for the sealed answers in pool.json.
 *
 * Mirrors chronotune/vault.py byte for byte. tests/test_vault.py seals in
 * Python, decodes here under node, and asserts the two agree. Change one side
 * and that test fails; change both and it passes. Never change only one.
 *
 * See vault.py for why this is obfuscation and not secrecy.
 */

const VAULT_SALT = 0x43484e54; // "CHNT"

function keystream(seed, length) {
  // >>> 0 after every step keeps the state unsigned, matching Python's
  // & 0xFFFFFFFF. Without it JS sign-extends and the streams diverge.
  let state = (seed ^ VAULT_SALT) >>> 0 || 0x9e3779b9;

  const out = new Uint8Array(length);
  for (let i = 0; i < length; i++) {
    state = (state ^ (state << 13)) >>> 0;
    state = (state ^ (state >>> 17)) >>> 0;
    state = (state ^ (state << 5)) >>> 0;
    out[i] = state & 0xff;
  }
  return out;
}

function unseal(seed, sealed) {
  const binary = atob(sealed);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);

  const key = keystream(seed, bytes.length);
  for (let i = 0; i < bytes.length; i++) bytes[i] ^= key[i];

  // Titles and artist names carry accents and non-Latin scripts, so the
  // payload is decoded as UTF-8 rather than read byte-wise.
  return JSON.parse(new TextDecoder("utf-8").decode(bytes));
}

// Loaded as a plain script in the browser; required as a module by the test.
if (typeof module !== "undefined" && module.exports) {
  module.exports = { keystream, unseal, VAULT_SALT };
}
