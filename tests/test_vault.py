"""The vault codec, and the pin holding its two implementations together.

vault.py seals; vault.js unseals in the browser. Nothing about the language
makes them agree. A sign-extension slip in the JS keystream would produce
plausible-looking garbage on every track. So the important test here is not the
Python round trip, it is the one that runs node.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from chronotune import vault

NODE = shutil.which("node")
VAULT_JS = Path(__file__).resolve().parent.parent / "static" / "vault.js"

CASES = [
    (4091937401, {"year": 1975, "artist": "Queen", "title": "Bohemian Rhapsody"}),
    (1, {"year": 1900, "artist": "A", "title": "B"}),
    # Accented and non-Latin text is decoded with TextDecoder on the JS side;
    # a byte-wise read would mangle exactly these.
    (12345, {"year": 2003, "artist": "Sigur Rós", "title": "Hoppípolla"}),
    (999, {"year": 1999, "artist": "Мумий Тролль", "title": "Владивосток 2000"}),
    (vault.SALT, {"year": 2000, "artist": "Zero", "title": "Seed"}),
]


class TestKeystream:
    def test_is_deterministic(self) -> None:
        assert vault.keystream(42, 32) == vault.keystream(42, 32)

    def test_differs_per_seed(self) -> None:
        assert vault.keystream(42, 32) != vault.keystream(43, 32)

    def test_is_a_prefix_of_a_longer_run(self) -> None:
        # Sealing depends on this: a payload's bytes must key the same way
        # regardless of how long the payload is.
        assert vault.keystream(7, 64)[:16] == vault.keystream(7, 16)

    def test_salt_seed_does_not_collapse_to_zeros(self) -> None:
        """seed ^ SALT == 0 is xorshift's fixed point and would emit zeros,
        making the XOR a no-op and publishing the plaintext."""
        assert set(vault.keystream(vault.SALT, 64)) != {0}


class TestSeal:
    @pytest.mark.parametrize("seed,payload", CASES)
    def test_round_trips(self, seed: int, payload: dict) -> None:
        assert vault.unseal(seed, vault.seal(seed, payload)) == payload

    def test_hides_the_plaintext(self) -> None:
        sealed = vault.seal(4091937401, CASES[0][1])
        assert "1975" not in sealed
        assert "Queen" not in sealed
        assert "Bohemian" not in sealed

    def test_is_byte_stable_across_calls(self) -> None:
        # An unstable encoding would churn every line of pool.json on rebuild.
        payload = {"year": 1975, "artist": "Queen", "title": "Bohemian Rhapsody"}
        reordered = {"title": "Bohemian Rhapsody", "artist": "Queen", "year": 1975}
        assert vault.seal(1, payload) == vault.seal(1, reordered)

    def test_wrong_seed_does_not_decode(self) -> None:
        sealed = vault.seal(100, CASES[0][1])
        with pytest.raises(Exception):
            vault.unseal(101, sealed)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
class TestJavaScriptAgrees:
    """Seal in Python, unseal in node. If these two ever disagree, every
    answer in the deployed build decodes to garbage."""

    def test_unseals_every_case(self, tmp_path) -> None:
        sealed = [
            {"seed": seed, "sealed": vault.seal(seed, payload)}
            for seed, payload in CASES
        ]
        script = tmp_path / "check.js"
        script.write_text(
            "const { unseal } = require(process.argv[2]);\n"
            "const cases = JSON.parse(process.argv[3]);\n"
            "console.log(JSON.stringify("
            "cases.map((c) => unseal(c.seed, c.sealed))));\n"
        )

        result = subprocess.run(
            [NODE, str(script), str(VAULT_JS), json.dumps(sealed)],
            capture_output=True,
            text=True,
            check=True,
        )

        assert json.loads(result.stdout) == [payload for _, payload in CASES]
