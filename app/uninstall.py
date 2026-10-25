"""``--uninstall-cleanup``: remove the Notion sign-in and the local data (PLAN.md 13).

The uninstaller runs this only when the user ticks "Also delete my data and Notion sign-in"
(unchecked by default). It disconnects the way Disconnect does (PLAN.md 12.7), then deletes:

1. **The sign-in.** For Notion sign-in (OAuth), the access is first cancelled with Notion through
   the token service, as the privacy policy describes ("when you disconnect"). A failure there
   never stops the rest. Pasted tokens can't be cancelled by the app. Then the Credential
   Manager entry is deleted.
2. **The data folder's own files.** Only what the app creates there (the database and its
   journal files, and the ``logs`` folder), and then the folder itself if nothing else is left.
   A whole folder is never deleted blindly, in case ``HABIT_TRACKER_HOME`` points at a folder
   that also holds other files.

The windowed app has no console, so the outcome is the exit code, a set of flags the
uninstaller turns into messages (``packaging/HabitTracker.iss``).
"""

from __future__ import annotations

import logging
import os
import shutil
import stat
from collections.abc import Callable
from enum import IntFlag
from pathlib import Path
from typing import Final

from app.notion.credentials import CredentialStore
from app.notion.service_client import TokenServiceClient
from app.paths import DATABASE_FILE_NAME, LOG_DIR_NAME, AppPaths

logger = logging.getLogger(__name__)

#: SQLite's companion files, deleted with the database.
DATABASE_SUFFIXES: Final = ("", "-journal", "-wal", "-shm")


class Outcome(IntFlag):
    """Exit code flags. 0 means everything was removed and any Notion access cancelled."""

    DONE = 0
    #: Unexpected failure: nothing can be assumed.
    FAILED = 1
    #: Notion sign-in: the access couldn't be cancelled with Notion (offline, service down).
    NOT_REVOKED = 2
    #: A pasted internal integration token: the app can't cancel it.
    PASTED_INTERNAL = 4
    #: A pasted personal access token: the app can't cancel it.
    PASTED_PAT = 8
    #: The Credential Manager entry couldn't be deleted.
    CREDENTIAL_KEPT = 16
    #: Some local data couldn't be deleted (for example a file open in another program).
    DATA_KEPT = 32


def remove_sign_in(store: CredentialStore, service: TokenServiceClient) -> Outcome:
    outcome = Outcome.DONE
    try:
        credential = store.load()
    except Exception:  # noqa: BLE001 - a damaged entry is still deleted below
        logger.warning("The stored sign-in couldn't be read; deleting it anyway")
        credential = None
    if credential is not None:
        if credential.kind == "oauth":
            try:
                service.revoke(credential.access_token)
            except Exception as exc:  # noqa: BLE001 - never stops the uninstall
                logger.warning("Couldn't cancel Notion access: %s", type(exc).__name__)
                outcome |= Outcome.NOT_REVOKED
        elif credential.kind == "internal":
            outcome |= Outcome.PASTED_INTERNAL
        else:
            outcome |= Outcome.PASTED_PAT
    try:
        store.delete()
    except Exception as exc:  # noqa: BLE001 - reported to the uninstaller
        logger.warning("Couldn't delete the sign-in: %s", type(exc).__name__)
        outcome |= Outcome.CREDENTIAL_KEPT
    return outcome


def _make_writable_and_retry(
    function: Callable[[str], object], path: str, _exc: BaseException
) -> None:
    Path(path).chmod(stat.S_IWRITE)
    function(path)


def remove_local_data(paths: AppPaths) -> Outcome:
    outcome = Outcome.DONE
    root = paths.root
    if not root.is_dir():
        return outcome
    for suffix in DATABASE_SUFFIXES:
        target = root / f"{DATABASE_FILE_NAME}{suffix}"
        try:
            target.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Couldn't delete %s: %s", target.name, exc.strerror)
            outcome |= Outcome.DATA_KEPT
    logs = root / LOG_DIR_NAME
    if logs.exists():
        try:
            shutil.rmtree(logs, onexc=_make_writable_and_retry)
        except OSError as exc:
            logger.warning("Couldn't delete the logs: %s", exc.strerror)
            outcome |= Outcome.DATA_KEPT
    try:
        root.rmdir()  # only when nothing else is left in it
    except OSError:
        if not outcome & Outcome.DATA_KEPT and any(root.iterdir()):
            logger.info("Kept %s: it holds files the app didn't create", root)
    return outcome


def run_cleanup(paths: AppPaths, service: TokenServiceClient) -> int:
    try:
        outcome = remove_sign_in(CredentialStore.for_paths(paths), service)
        outcome |= remove_local_data(paths)
    except Exception:  # the uninstaller explains a failure
        logger.exception("Uninstall cleanup failed")
        return int(Outcome.FAILED)
    finally:
        service.close()
    logger.info("Uninstall cleanup finished: %s", outcome.value)
    return int(outcome)


def cleanup_from_installer() -> int:
    """Entry point for ``--uninstall-cleanup``. Writes no log: the folder is being removed."""
    from app.notion.service_client import DEFAULT_SERVICE_URL, SERVICE_URL_ENV_VAR

    service = TokenServiceClient(os.environ.get(SERVICE_URL_ENV_VAR) or DEFAULT_SERVICE_URL)
    return run_cleanup(AppPaths.resolve(), service)
