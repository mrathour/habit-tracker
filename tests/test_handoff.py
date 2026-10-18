"""The app side of the OAuth hand-off (docs/handoff-protocol.md)."""

from __future__ import annotations

import json
import threading
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from app.notion.handoff import (
    HandoffError,
    OneTimeKey,
    ServerClock,
    SignInFailed,
    TokenGrant,
    b64url_decode,
    b64url_encode,
)
from app.redaction import REDACTED, redact
from tests.support.handoff_reference import (
    VECTORS_PATH,
    plaintext_json,
    render_vectors,
    seal,
)

VECTORS: dict[str, Any] = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
CASES = {case["name"]: case for case in VECTORS["cases"]}
STATE: str = VECTORS["state"]


def vector_key() -> OneTimeKey:
    raw = b64url_decode(VECTORS["app_private_key"])
    return OneTimeKey(X25519PrivateKey.from_private_bytes(raw))


def vector_clock() -> ServerClock:
    return ServerClock.from_start(server_time=VECTORS["now"])


def fresh(body: dict[str, Any] | None = None) -> tuple[OneTimeKey, str, ServerClock]:
    """A new key and an envelope sealed to it, valid now."""
    clock = ServerClock()
    key = OneTimeKey()
    body = body or {
        "v": 1,
        "exp": int(clock.now()) + 120,
        "result": "ok",
        "token": {
            "access_token": "ntn_" + "x" * 40,
            "refresh_token": "nrt_" + "y" * 40,
            "bot_id": "bot",
            "workspace_id": "ws",
            "workspace_name": "Work",
            "workspace_icon": None,
        },
    }
    envelope = seal(b64url_decode(key.public_key), STATE, plaintext_json(body))
    return key, envelope, clock


# --- Shared vectors -------------------------------------------------------------------------


def test_vectors_file_is_up_to_date() -> None:
    assert VECTORS_PATH.read_text(encoding="utf-8") == render_vectors()


def test_vector_public_key_matches() -> None:
    assert vector_key().public_key == VECTORS["app_public_key"]


@pytest.mark.parametrize("name", ["ok_full", "ok_null_workspace_details"])
def test_vectors_with_tokens_open(name: str) -> None:
    case = CASES[name]
    result = vector_key().open(case["envelope"], state=STATE, clock=vector_clock())
    assert isinstance(result, TokenGrant)
    expected = json.loads(case["plaintext"])["token"]
    assert result.access_token.reveal() == expected["access_token"]
    assert result.refresh_token.reveal() == expected["refresh_token"]
    assert result.bot_id == expected["bot_id"]
    assert result.workspace_id == expected["workspace_id"]
    assert result.workspace_name == expected["workspace_name"]
    assert result.workspace_icon == expected["workspace_icon"]


@pytest.mark.parametrize(
    ("name", "code"),
    [("error_access_denied", "access_denied"), ("error_notion_unreachable", "notion_unreachable")],
)
def test_vectors_with_errors_open(name: str, code: str) -> None:
    result = vector_key().open(CASES[name]["envelope"], state=STATE, clock=vector_clock())
    assert result == SignInFailed(code)  # type: ignore[arg-type]


def test_expired_vector_is_rejected() -> None:
    with pytest.raises(HandoffError) as caught:
        vector_key().open(CASES["expired"]["envelope"], state=STATE, clock=vector_clock())
    assert caught.value.code == "expired"


# --- One-time use ---------------------------------------------------------------------------


def test_key_opens_only_once() -> None:
    key, envelope, clock = fresh()
    assert isinstance(key.open(envelope, state=STATE, clock=clock), TokenGrant)
    assert key.used
    with pytest.raises(HandoffError) as caught:
        key.open(envelope, state=STATE, clock=clock)
    assert caught.value.code == "key_used"


def test_key_is_destroyed_even_when_opening_fails() -> None:
    key, envelope, clock = fresh()
    with pytest.raises(HandoffError) as caught:
        key.open(envelope, state="another-state", clock=clock)
    assert caught.value.code == "invalid"
    assert key.used
    # The genuine envelope can no longer be read either.
    with pytest.raises(HandoffError) as again:
        key.open(envelope, state=STATE, clock=clock)
    assert again.value.code == "key_used"


def test_destroy_before_use() -> None:
    key, envelope, clock = fresh()
    key.destroy()
    with pytest.raises(HandoffError, match="already completed or cancelled"):
        key.open(envelope, state=STATE, clock=clock)


def test_concurrent_opens_succeed_at_most_once() -> None:
    key, envelope, clock = fresh()
    outcomes: list[str] = []
    lock = threading.Lock()

    def attempt() -> None:
        try:
            key.open(envelope, state=STATE, clock=clock)
            result = "ok"
        except HandoffError as exc:
            result = exc.code
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count("ok") == 1
    assert outcomes.count("key_used") == 7


# --- Tampering and malformed input ----------------------------------------------------------


def flip(envelope: str, index: int) -> str:
    raw = bytearray(b64url_decode(envelope))
    raw[index] ^= 0x01
    return b64url_encode(bytes(raw))


@pytest.mark.parametrize(
    "mangle",
    [
        pytest.param(lambda e: flip(e, -1), id="tag"),
        pytest.param(lambda e: flip(e, 50), id="ciphertext"),
        pytest.param(lambda e: flip(e, 40), id="nonce"),
        pytest.param(lambda e: flip(e, 5), id="ephemeral-key"),
        pytest.param(lambda e: flip(e, 0), id="version-byte"),
        pytest.param(lambda e: e[:60], id="truncated"),
        pytest.param(lambda e: e + "=", id="padding"),
        pytest.param(lambda e: e.replace("-", "+"), id="standard-base64"),
        pytest.param(lambda e: "", id="empty"),
        pytest.param(lambda e: "A" * 20_000, id="huge"),
    ],
)
def test_tampered_envelopes_are_rejected(mangle: Any) -> None:
    key, envelope, clock = fresh()
    mangled = mangle(envelope)
    if mangled == envelope:
        pytest.skip("this envelope has no character to mangle")
    with pytest.raises(HandoffError) as caught:
        key.open(mangled, state=STATE, clock=clock)
    assert caught.value.code == "invalid"


def test_envelope_for_another_key_is_rejected() -> None:
    key, _, clock = fresh()
    other = OneTimeKey()
    stolen = seal(b64url_decode(other.public_key), STATE, b'{"v":1}')
    with pytest.raises(HandoffError) as caught:
        key.open(stolen, state=STATE, clock=clock)
    assert caught.value.code == "invalid"


def test_low_order_ephemeral_key_is_rejected() -> None:
    key, _, clock = fresh()
    envelope = b64url_encode(bytes([0x01]) + bytes(32) + bytes(12) + bytes(32))
    with pytest.raises(HandoffError) as caught:
        key.open(envelope, state=STATE, clock=clock)
    assert caught.value.code == "invalid"


@pytest.mark.parametrize(
    "body",
    [
        {"v": 2, "exp": 9_999_999_999, "result": "error", "error": "access_denied"},
        {"v": 1, "exp": "soon", "result": "error", "error": "access_denied"},
        {"v": 1, "exp": True, "result": "error", "error": "access_denied"},
        {"v": 1, "exp": 9_999_999_999, "result": "error", "error": "made_up"},
        {"v": 1, "exp": 9_999_999_999, "result": "maybe"},
        {"v": 1, "exp": 9_999_999_999, "result": "ok"},
        {"v": 1, "exp": 9_999_999_999, "result": "ok", "token": {"access_token": "a"}},
        {
            "v": 1,
            "exp": 9_999_999_999,
            "result": "ok",
            "token": {
                "access_token": "a",
                "refresh_token": "b",
                "bot_id": "c",
                "workspace_id": "d",
                "workspace_name": 42,
            },
        },
    ],
)
def test_malformed_plaintexts_are_rejected(body: dict[str, Any]) -> None:
    key, envelope, clock = fresh(body)
    with pytest.raises(HandoffError) as caught:
        key.open(envelope, state=STATE, clock=clock)
    assert caught.value.code == "invalid"


def test_non_json_plaintext_is_rejected() -> None:
    key = OneTimeKey()
    envelope = seal(b64url_decode(key.public_key), STATE, b"\xff not json")
    with pytest.raises(HandoffError) as caught:
        key.open(envelope, state=STATE, clock=ServerClock())
    assert caught.value.code == "invalid"


def test_non_ascii_state_is_rejected() -> None:
    key, envelope, clock = fresh()
    with pytest.raises(HandoffError) as caught:
        key.open(envelope, state="stätë", clock=clock)
    assert caught.value.code == "invalid"


# --- Clock --------------------------------------------------------------------------------


def test_expiry_uses_the_server_clock() -> None:
    # The PC clock is an hour fast; the hand-off is still within its 120 seconds.
    server_now = 1_800_000_000
    pc_now = server_now + 3600
    clock = ServerClock.from_start(server_time=server_now, local_time=pc_now)
    key = OneTimeKey()
    body = {"v": 1, "exp": server_now + 120, "result": "error", "error": "access_denied"}
    envelope = seal(b64url_decode(key.public_key), STATE, plaintext_json(body))
    assert clock.offset == -3600
    assert key.open(envelope, state=STATE, clock=clock) == SignInFailed("access_denied")


# --- Secrets ------------------------------------------------------------------------------


def test_tokens_never_show_in_repr() -> None:
    key, envelope, clock = fresh()
    grant = key.open(envelope, state=STATE, clock=clock)
    shown = repr(grant) + str(grant)
    assert "x" * 40 not in shown
    assert "y" * 40 not in shown
    assert REDACTED in shown
    # Opening registers both tokens for log redaction.
    assert redact("ntn_" + "x" * 40) == REDACTED


def test_public_key_is_32_bytes() -> None:
    key = OneTimeKey()
    assert len(b64url_decode(key.public_key)) == 32
    assert key.public_key != OneTimeKey().public_key


@pytest.mark.parametrize("text", ["a+b", "a/b", "ab==", "a", "a b"])
def test_strict_base64url(text: str) -> None:
    with pytest.raises(ValueError, match="base64url"):
        b64url_decode(text)
