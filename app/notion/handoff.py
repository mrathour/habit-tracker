"""The app side of the OAuth hand-off (docs/handoff-protocol.md).

The app creates a :class:`OneTimeKey`, sends its public key to the token service's ``/start``,
and later opens the envelope the browser brings back to the loopback listener. The private key
can be used for exactly one decryption attempt and is destroyed afterwards, whatever the outcome,
so a replayed or late envelope can never be read.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import threading
import time
from dataclasses import dataclass
from typing import Final, Literal

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.redaction import Secret

PROTOCOL_VERSION: Final = 1
ENVELOPE_VERSION_BYTE: Final = 0x01
HKDF_INFO: Final = b"habit-tracker handoff v1"
KEY_BYTES: Final = 32
NONCE_BYTES: Final = 12
TAG_BYTES: Final = 16
#: The longest envelope we accept, well above any real token response.
MAX_ENVELOPE_CHARS: Final = 16_384

ErrorCode = Literal["access_denied", "notion_error", "notion_unreachable", "server_misconfigured"]
ERROR_CODES: Final[frozenset[str]] = frozenset(
    {"access_denied", "notion_error", "notion_unreachable", "server_misconfigured"}
)

_B64URL = re.compile(r"^[A-Za-z0-9_-]*$")


class HandoffError(Exception):
    """The hand-off couldn't be accepted. ``code`` says why, for the UI and tests."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    """Strict base64url without padding: anything else is rejected."""
    if not _B64URL.fullmatch(text) or len(text) % 4 == 1:
        raise ValueError("not base64url")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError) as exc:
        raise ValueError("not base64url") from exc


@dataclass(frozen=True, slots=True)
class TokenGrant:
    """A successful sign-in. Token values are wrapped so they never print or log."""

    access_token: Secret
    refresh_token: Secret
    bot_id: str
    workspace_id: str
    workspace_name: str | None
    workspace_icon: str | None


@dataclass(frozen=True, slots=True)
class SignInFailed:
    """Notion or the service reported that sign-in didn't complete."""

    error: ErrorCode


type HandoffResult = TokenGrant | SignInFailed


@dataclass(frozen=True, slots=True)
class ServerClock:
    """Time on the token service's clock, so a wrong PC clock can't break expiry checks.

    ``offset`` is ``server_time - local time`` measured when ``/start`` answered.
    """

    offset: float = 0.0

    @classmethod
    def from_start(cls, server_time: float, local_time: float | None = None) -> ServerClock:
        return cls(server_time - (time.time() if local_time is None else local_time))

    def now(self) -> float:
        return time.time() + self.offset


class OneTimeKey:
    """An X25519 key pair whose private half can open exactly one envelope."""

    def __init__(self, private_key: X25519PrivateKey | None = None) -> None:  # gitleaks:allow
        self._private: X25519PrivateKey | None = private_key or X25519PrivateKey.generate()
        self._lock = threading.Lock()
        self.public_key = b64url_encode(
            self._private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        )

    @property
    def used(self) -> bool:
        return self._private is None

    def destroy(self) -> None:
        with self._lock:
            self._private = None

    def open(self, envelope: str, *, state: str, clock: ServerClock) -> HandoffResult:
        """Decrypt and check ``envelope``. The key is destroyed whatever happens."""
        with self._lock:
            private, self._private = self._private, None
        if private is None:
            raise HandoffError("key_used", "This sign-in was already completed or cancelled.")
        plaintext = _decrypt(private, envelope, state)
        return _parse(plaintext, clock)


def _decrypt(private: X25519PrivateKey, envelope: str, state: str) -> bytes:
    if len(envelope) > MAX_ENVELOPE_CHARS:
        raise HandoffError("invalid", "The sign-in response was too large.")
    try:
        raw = b64url_decode(envelope)
    except ValueError as exc:
        raise HandoffError("invalid", "The sign-in response was malformed.") from exc
    header = 1 + KEY_BYTES + NONCE_BYTES
    if len(raw) < header + TAG_BYTES or raw[0] != ENVELOPE_VERSION_BYTE:
        raise HandoffError("invalid", "The sign-in response was malformed.")
    ephemeral_public = raw[1 : 1 + KEY_BYTES]
    nonce = raw[1 + KEY_BYTES : header]
    ciphertext = raw[header:]
    app_public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    try:
        shared = private.exchange(X25519PublicKey.from_public_bytes(ephemeral_public))
    except ValueError as exc:  # an all-zero shared secret: a malicious public key
        raise HandoffError("invalid", "The sign-in response couldn't be read.") from exc
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_BYTES,
        salt=ephemeral_public + app_public,
        info=HKDF_INFO,
    ).derive(shared)
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, state.encode("ascii"))
    except (InvalidTag, UnicodeEncodeError) as exc:
        raise HandoffError("invalid", "The sign-in response couldn't be read.") from exc


def _parse(plaintext: bytes, clock: ServerClock) -> HandoffResult:
    try:
        data = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandoffError("invalid", "The sign-in response couldn't be read.") from exc
    if not isinstance(data, dict) or data.get("v") != PROTOCOL_VERSION:
        raise HandoffError("invalid", "The sign-in response has an unsupported version.")
    expires = data.get("exp")
    if not isinstance(expires, int | float) or isinstance(expires, bool):
        raise HandoffError("invalid", "The sign-in response was malformed.")
    if expires <= clock.now():
        raise HandoffError("expired", "The sign-in took too long and expired.")

    result = data.get("result")
    if result == "error":
        error = data.get("error")
        if error not in ERROR_CODES:
            raise HandoffError("invalid", "The sign-in response was malformed.")
        return SignInFailed(error)
    if result != "ok":
        raise HandoffError("invalid", "The sign-in response was malformed.")
    token = data.get("token")
    if not isinstance(token, dict):
        raise HandoffError("invalid", "The sign-in response was malformed.")
    required = ("access_token", "refresh_token", "bot_id", "workspace_id")
    if not all(isinstance(token.get(name), str) and token[name] for name in required):
        raise HandoffError("invalid", "The sign-in response was missing details.")
    optional = {name: token.get(name) for name in ("workspace_name", "workspace_icon")}
    if any(value is not None and not isinstance(value, str) for value in optional.values()):
        raise HandoffError("invalid", "The sign-in response was malformed.")
    return TokenGrant(
        access_token=Secret(token["access_token"]),
        refresh_token=Secret(token["refresh_token"]),
        bot_id=token["bot_id"],
        workspace_id=token["workspace_id"],
        workspace_name=optional["workspace_name"],
        workspace_icon=optional["workspace_icon"],
    )
