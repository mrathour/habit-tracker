"""Reference sealer for the hand-off protocol, and the shared test vectors it generates.

The app never encrypts hand-offs (the Worker does), so sealing lives here, in tests only. It
follows docs/handoff-protocol.md step by step. The vectors are deterministic, so the file in
service/test/fixtures/handoff-v1.json can be regenerated and checked for drift:

    uv run python -m tests.support.handoff_reference
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from app.notion.handoff import ENVELOPE_VERSION_BYTE, HKDF_INFO, KEY_BYTES, b64url_encode

VECTORS_PATH: Final = (
    Path(__file__).resolve().parents[2] / "service" / "test" / "fixtures" / "handoff-v1.json"
)

#: The vectors' fixed "current time", for checking expiry deterministically.
VECTOR_NOW: Final = 1_792_310_400


def derived_bytes(label: str, length: int) -> bytes:
    return hashlib.sha256(f"habit-tracker test vector: {label}".encode()).digest()[:length]


def private_key(label: str) -> X25519PrivateKey:
    return X25519PrivateKey.from_private_bytes(derived_bytes(label, 32))


def raw_public(key: X25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def raw_private(key: X25519PrivateKey) -> bytes:
    return key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())


def seal(
    app_public: bytes,
    state: str,
    plaintext: bytes,
    *,
    ephemeral: X25519PrivateKey | None = None,
    nonce: bytes | None = None,
) -> str:
    """Encrypt ``plaintext`` to ``app_public``, exactly as the Worker does."""
    ephemeral = ephemeral or X25519PrivateKey.generate()
    nonce = nonce if nonce is not None else derived_bytes("random nonce", 12)
    ephemeral_public = raw_public(ephemeral)
    shared = ephemeral.exchange(X25519PublicKey.from_public_bytes(app_public))
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_BYTES,
        salt=ephemeral_public + app_public,
        info=HKDF_INFO,
    ).derive(shared)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, state.encode("ascii"))
    return b64url_encode(bytes([ENVELOPE_VERSION_BYTE]) + ephemeral_public + nonce + ciphertext)


def plaintext_json(body: dict[str, Any]) -> bytes:
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


FAKE_STATE: Final = "eyJ2IjoxLCJuIjoidGVzdCIsInAiOjUyNzMxLCJrIjoidGVzdCIsImUiOjB9.c2lnbmF0dXJl"

_CASES: Final[list[tuple[str, dict[str, Any]]]] = [
    (
        "ok_full",
        {
            "v": 1,
            "exp": VECTOR_NOW + 120,
            "result": "ok",
            "token": {
                "access_token": "ntn_" + "A" * 40,
                "refresh_token": "nrt_" + "B" * 40,
                "bot_id": "2f1b4c1e-0000-4000-8000-000000000001",
                "workspace_id": "2f1b4c1e-0000-4000-8000-000000000002",
                "workspace_name": "Mayank's Notion · Työtila",
                "workspace_icon": "https://example.test/icon.png",
            },
        },
    ),
    (
        "ok_null_workspace_details",
        {
            "v": 1,
            "exp": VECTOR_NOW + 120,
            "result": "ok",
            "token": {
                "access_token": "ntn_" + "C" * 40,
                "refresh_token": "nrt_" + "D" * 40,
                "bot_id": "bot-3",
                "workspace_id": "ws-3",
                "workspace_name": None,
                "workspace_icon": None,
            },
        },
    ),
    (
        "error_access_denied",
        {"v": 1, "exp": VECTOR_NOW + 120, "result": "error", "error": "access_denied"},
    ),
    (
        "error_notion_unreachable",
        {"v": 1, "exp": VECTOR_NOW + 120, "result": "error", "error": "notion_unreachable"},
    ),
    ("expired", {"v": 1, "exp": VECTOR_NOW - 1, "result": "error", "error": "access_denied"}),
]


def build_vectors() -> dict[str, Any]:
    app_key = private_key("app")
    app_public = raw_public(app_key)
    cases: list[dict[str, Any]] = []
    for name, body in _CASES:
        ephemeral = private_key(f"ephemeral {name}")
        nonce = derived_bytes(f"nonce {name}", 12)
        plaintext = plaintext_json(body)
        envelope = seal(app_public, FAKE_STATE, plaintext, ephemeral=ephemeral, nonce=nonce)
        cases.append(
            {
                "name": name,
                "ephemeral_private_key": b64url_encode(raw_private(ephemeral)),
                "ephemeral_public_key": b64url_encode(raw_public(ephemeral)),
                "nonce": b64url_encode(nonce),
                "plaintext": plaintext.decode("utf-8"),
                "envelope": envelope,
                "expect": "expired" if name == "expired" else body["result"],
            }
        )
    return {
        "protocol": "habit-tracker handoff v1 (docs/handoff-protocol.md)",
        "note": (
            "Test-only keys and fake tokens. "
            "Regenerate: uv run python -m tests.support.handoff_reference"
        ),
        "now": VECTOR_NOW,
        "state": FAKE_STATE,
        "app_private_key": b64url_encode(raw_private(app_key)),
        "app_public_key": b64url_encode(app_public),
        "cases": cases,
    }


def render_vectors() -> str:
    return json.dumps(build_vectors(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    VECTORS_PATH.write_text(render_vectors(), encoding="utf-8", newline="\n")
