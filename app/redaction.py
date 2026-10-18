"""Masking of tokens and secrets before text reaches a log, the UI or an error report.

Two layers work together:

* **Patterns** catch the shapes secrets take in text: Notion tokens (``secret_…``, ``ntn_…``),
  ``Authorization`` headers, ``key=value`` / JSON pairs whose key names a secret, and OAuth
  parameters in URLs.
* **Registered values** catch exact secrets the app holds at run time, whatever their shape.
  Code that receives a token calls :func:`register_secret` before doing anything else with it.
"""

from __future__ import annotations

import re
import threading
from typing import Final

REDACTED: Final = "[REDACTED]"

# Values shorter than this are not registered: masking every "a" or "1" in the logs would
# destroy them, and no real token is this short.
MIN_REGISTERED_LENGTH: Final = 8

# Key names whose values are masked (not secrets themselves).
_SECRET_KEYS = (
    r"access_token|refresh_token|id_token|client_secret|client_id_secret|api_key|apikey"  # noqa: S105
    r"|private_key|signing_key|password|passwd|secret|token|authorization|cookie|set-cookie"
)

_PATTERNS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    # Notion internal integration, OAuth and personal access tokens.
    (re.compile(r"\b(?:secret|ntn)_[A-Za-z0-9]{16,}\b"), REDACTED),
    # HTTP auth schemes, wherever they appear.
    (re.compile(r"(?i)\b(Bearer|Basic|Token)\s+[A-Za-z0-9._~+/=-]{8,}"), rf"\1 {REDACTED}"),
    # OAuth parameters in URLs and form bodies.
    (
        re.compile(
            r"(?i)([?&](?:code|state|token|access_token|refresh_token|client_secret)=)[^&\s\"'#]+"
        ),
        rf"\1{REDACTED}",
    ),
    # key: value, key=value, "key": "value", 'key': 'value' where the key names a secret.
    (
        re.compile(
            rf"(?i)(?<![A-Za-z0-9])([\"']?(?:{_SECRET_KEYS})[\"']?\s*[:=]\s*)"
            r"(?:(?:Bearer|Basic|Token)\s+)?"
            r"(?:\"[^\"]*\"|'[^']*'|[^\s,;}&\]\)]+)"
        ),
        rf"\1{REDACTED}",
    ),
)

_registered: set[str] = set()
_registered_lock = threading.Lock()


def register_secret(value: str | None) -> None:
    """Mask every future occurrence of ``value`` in redacted text."""
    if value and len(value) >= MIN_REGISTERED_LENGTH:
        with _registered_lock:
            _registered.add(value)


def forget_secret(value: str | None) -> None:
    """Stop masking ``value``, for example after the token has been deleted."""
    if value:
        with _registered_lock:
            _registered.discard(value)


def clear_registered_secrets() -> None:
    with _registered_lock:
        _registered.clear()


def redact(text: str) -> str:
    """Return ``text`` with every known secret replaced by ``[REDACTED]``."""
    with _registered_lock:
        # Longest first, so a secret containing another one is masked whole.
        registered = sorted(_registered, key=len, reverse=True)
    for value in registered:
        text = text.replace(value, REDACTED)
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class Secret:
    """A string that never shows its value in ``str``, ``repr`` or f-strings.

    Wrapping a token in ``Secret`` keeps it out of tracebacks, debug output and logs; code that
    really needs the value calls :meth:`reveal`.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value
        register_secret(value)

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"Secret({REDACTED})"

    def __str__(self) -> str:
        return REDACTED

    def __format__(self, format_spec: str) -> str:
        return REDACTED

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Secret) and other._value == self._value

    def __hash__(self) -> int:
        return hash(self._value)

    def __reduce__(self) -> str | tuple[object, ...]:
        raise TypeError("Secret values cannot be pickled")
