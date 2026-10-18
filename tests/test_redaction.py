from __future__ import annotations

import pickle

import pytest

from app.redaction import (
    MIN_REGISTERED_LENGTH,
    REDACTED,
    Secret,
    forget_secret,
    redact,
    register_secret,
)


@pytest.mark.parametrize(
    ("text", "leaked"),
    [
        ("token secret_abcdefghijklmnopqrstuvwxyz0123", "secret_abcdefghijklmnop"),
        ("token ntn_abcdefghijklmnopqrstuvwxyz0123", "ntn_abcdefghijklmnop"),
        ("Authorization: Bearer abc.def-ghi_jkl~mno", "abc.def-ghi_jkl"),
        ("authorization=Basic dXNlcjpwYXNzd29yZA==", "dXNlcjpwYXNzd29yZA"),
        ('{"access_token": "opaque-value-1"}', "opaque-value-1"),
        ("{'refresh_token': 'opaque-value-2'}", "opaque-value-2"),
        ("client_secret=opaque-value-3&x=1", "opaque-value-3"),
        ("REFRESH_TOKEN: opaque-value-4", "opaque-value-4"),
        ("password = hunter2-hunter2", "hunter2-hunter2"),
        ("https://x.test/cb?code=abc123def456&state=s1", "abc123def456"),
        ("https://x.test/cb?state=signed.state.value", "signed.state.value"),
        ('"private_key": "MC4CAQAwBQYDK2VuBCIEI"', "MC4CAQAwBQYDK2VuBCIEI"),  # gitleaks:allow
    ],
)
def test_patterns_mask_secret_shapes(text: str, leaked: str) -> None:
    result = redact(text)
    assert leaked not in result
    assert REDACTED in result


@pytest.mark.parametrize(
    "text",
    [
        "Synced 42 entries in 1.2 s",
        '{"token_type": "bearer", "workspace_name": "Work"}',
        "error code: 401 unauthorized",
        "GET /v1/data_sources/1234/query 200",
        "secret_short",
    ],
)
def test_ordinary_text_is_left_alone(text: str) -> None:
    assert redact(text) == text


def test_registered_values_are_masked_anywhere() -> None:
    value = "a weird secret with spaces"
    register_secret(value)
    assert redact(f"prefix{value}suffix") == f"prefix{REDACTED}suffix"
    forget_secret(value)
    assert redact(value) == value


def test_short_values_are_not_registered() -> None:
    register_secret("a" * (MIN_REGISTERED_LENGTH - 1))
    assert redact("aaaaaaa banana") == "aaaaaaa banana"


def test_longest_registered_value_wins() -> None:
    register_secret("abcdefgh")
    register_secret("abcdefgh-and-more")
    assert redact("abcdefgh-and-more") == REDACTED


def test_secret_hides_its_value() -> None:
    secret = Secret("super-secret-value")
    assert secret.reveal() == "super-secret-value"
    for shown in (str(secret), repr(secret), f"{secret}", f"{secret:>30}", "%s" % secret):  # noqa: UP031
        assert "super-secret-value" not in shown
    assert redact("leaked super-secret-value") == f"leaked {REDACTED}"
    assert secret == Secret("super-secret-value")
    assert len({secret, Secret("super-secret-value")}) == 1
    with pytest.raises(TypeError):
        pickle.dumps(secret)
