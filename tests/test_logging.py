"""Logs must never contain tokens or secrets (CLAUDE.md hard rules, PLAN.md 12.5)."""

from __future__ import annotations

import json
import logging
import re
import threading
import warnings
from pathlib import Path

import pytest

from app import log
from app.errors import report_exception
from app.log import LOG_FILE_NAME, configure_logging
from app.redaction import REDACTED, Secret, register_secret

# Fake values in the shapes real ones take. None of them is a real credential.
NOTION_INTERNAL_TOKEN = "secret_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0U1v"
NOTION_NEW_TOKEN = "ntn_" + "123456789012345678901234567890abcdefABCDEF1234"
OAUTH_ACCESS_TOKEN = "eyJhbGciOiJIUzI1NiJ9.ZmFrZS1hY2Nlc3MtdG9rZW4.c2lnbmF0dXJl"
REFRESH_TOKEN = "rt-" + "9f8e7d6c5b4a39281706f5e4d3c2b1a0"
CLIENT_SECRET = "cs-" + "Zx9Yw8Vu7Ts6Rq5Po4Nm3Lk2Ji1Hg0Fe"
OAUTH_CODE = "code-" + "0a1b2c3d4e5f60718293a4b5c6d7e8f9"
OPAQUE_SECRET = "odd shaped value !@#$ 42 that only registration can catch"

ALL_SECRETS = (
    NOTION_INTERNAL_TOKEN,
    NOTION_NEW_TOKEN,
    OAUTH_ACCESS_TOKEN,
    REFRESH_TOKEN,
    CLIENT_SECRET,
    OAUTH_CODE,
    OPAQUE_SECRET,
)


def read_all_logs(logs_dir: Path) -> str:
    handlers = [h for h in logging.getLogger().handlers if getattr(h, "_habit_tracker", False)]
    for handler in handlers:
        handler.flush()
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(logs_dir.glob("*.log*")))


def assert_no_secrets(text: str) -> None:
    for secret in ALL_SECRETS:
        assert secret not in text, f"secret leaked into the log: {secret[:8]}…"
        # Partial leaks count too: no 12-character window of any secret may appear.
        for start in range(0, len(secret) - 12, 4):
            assert secret[start : start + 12] not in text, f"part of {secret[:8]}… leaked"


def test_tokens_never_reach_the_log_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    logs_dir = tmp_path / "logs"
    configure_logging(logs_dir, debug=True, console=True)
    register_secret(OPAQUE_SECRET)
    logger = logging.getLogger("app.notion.client")

    # Every way a token could plausibly end up in a log call.
    logger.debug("Token is %s", NOTION_INTERNAL_TOKEN)
    logger.info(f"Using token {NOTION_NEW_TOKEN}")  # noqa: G004 - the f-string case on purpose
    logger.info("Request headers: %s", {"Authorization": f"Bearer {OAUTH_ACCESS_TOKEN}"})
    logger.info("Authorization: Bearer %s", OAUTH_ACCESS_TOKEN)
    logger.info(
        "Token response: %s",
        json.dumps({"access_token": OAUTH_ACCESS_TOKEN, "refresh_token": REFRESH_TOKEN}),
    )
    logger.info("Token response repr: %r", {"refresh_token": REFRESH_TOKEN, "token_type": "bearer"})
    logger.info("POST body: grant_type=refresh_token&refresh_token=%s", REFRESH_TOKEN)
    logger.info("client_secret=%s client_id=abc", CLIENT_SECRET)
    logger.info("Callback URL: https://example.test/callback?code=%s&state=xyz", OAUTH_CODE)
    logger.info("Opaque value: %s", OPAQUE_SECRET)
    logger.info("Wrapped value: %s / %r", Secret(CLIENT_SECRET), Secret(REFRESH_TOKEN))
    logger.warning("extra fields", extra={"token": NOTION_INTERNAL_TOKEN})
    logging.getLogger("pywebview").info("js_api call with %s", NOTION_NEW_TOKEN)
    logging.getLogger("some.library").error("Library echoed %s", NOTION_INTERNAL_TOKEN)

    try:
        raise RuntimeError(
            f"Notion rejected token {NOTION_INTERNAL_TOKEN} with refresh {REFRESH_TOKEN}"
        )
    except RuntimeError:
        logger.exception("Request failed")

    try:
        raise ValueError(f"access_token={OAUTH_ACCESS_TOKEN}")
    except ValueError as exc:
        report = report_exception(exc, context="a test")

    def thread_failure() -> None:
        logger.error("From a thread: %s", NOTION_NEW_TOKEN, stack_info=True)

    worker = threading.Thread(target=thread_failure)
    worker.start()
    worker.join()

    with warnings.catch_warnings():
        warnings.simplefilter("always")
        warnings.warn(f"deprecated use of {CLIENT_SECRET}", UserWarning, stacklevel=1)

    text = read_all_logs(logs_dir)
    assert_no_secrets(text)
    assert_no_secrets(capsys.readouterr().err)
    assert_no_secrets(json.dumps(report.to_dict()))
    assert text.count(REDACTED) >= 15
    # The useful context around each secret survives.
    assert "Request failed" in text
    assert "token_type" in text
    assert "client_id=abc" in text
    assert "state=" in text


def test_log_lines_use_utc_timestamps(tmp_path: Path) -> None:
    configure_logging(tmp_path)
    logging.getLogger("app").info("hello")
    line = read_all_logs(tmp_path).strip().splitlines()[-1]
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z INFO ", line), line


def test_log_file_rotates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(log, "MAX_LOG_BYTES", 2000)
    monkeypatch.setattr(log, "LOG_BACKUP_COUNT", 2)
    configure_logging(tmp_path)
    logger = logging.getLogger("app")
    for i in range(200):
        logger.info("line %d %s", i, "x" * 50)
    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == [LOG_FILE_NAME, f"{LOG_FILE_NAME}.1", f"{LOG_FILE_NAME}.2"]


def test_configuring_twice_does_not_duplicate_output(tmp_path: Path) -> None:
    configure_logging(tmp_path)
    configure_logging(tmp_path)
    logging.getLogger("app").info("only once")
    assert read_all_logs(tmp_path).count("only once") == 1


def test_info_level_by_default_and_debug_in_dev(tmp_path: Path) -> None:
    configure_logging(tmp_path / "a")
    logging.getLogger("app").debug("hidden detail")
    assert "hidden detail" not in read_all_logs(tmp_path / "a")
    configure_logging(tmp_path / "b", debug=True)
    logging.getLogger("app").debug("visible detail")
    assert "visible detail" in read_all_logs(tmp_path / "b")


def test_pywebview_console_handler_is_replaced(tmp_path: Path) -> None:
    pywebview_logger = logging.getLogger("pywebview")
    stray = logging.StreamHandler()
    pywebview_logger.addHandler(stray)
    configure_logging(tmp_path)
    assert stray not in pywebview_logger.handlers
    assert pywebview_logger.propagate
