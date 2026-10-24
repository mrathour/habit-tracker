"""Credential Manager target names (issue #11): a ``HABIT_TRACKER_HOME`` copy never shares, moves
or deletes the real app's entry.

These tests run keyring's real Windows backend, ``WinVaultKeyring``, against an in-memory
stand-in for the Windows credential functions, so the target names are the ones Windows sees.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import keyring
import keyring.errors
import pytest
from keyring.backends import Windows

from app.notion.credentials import SERVICE_NAME, CredentialStore, StoredCredential
from app.paths import AppPaths
from app.redaction import Secret

#: The Windows error type the backend catches (pywin32-ctypes, or pywin32).
WinError: type[Exception] = Windows.pywintypes.error  # type: ignore[attr-defined]


class FakeVault:
    """Generic credentials by target name, as ``CredRead``, ``CredWrite`` and ``CredDelete`` see
    them."""

    def __init__(self) -> None:
        self.entries: dict[str, dict[str, Any]] = {}
        #: Set to make every delete fail, as a locked vault would.
        self.refuse_deletes = False

    def _missing(self, funcname: str) -> Exception:
        return WinError(1168, funcname, "Element not found.")

    def CredRead(self, Type: int, TargetName: str) -> dict[str, Any]:  # noqa: N802, N803
        if TargetName not in self.entries:
            raise self._missing("CredRead")
        return dict(self.entries[TargetName])

    def CredWrite(self, credential: dict[str, Any], flags: int) -> None:  # noqa: N802
        self.entries[credential["TargetName"]] = {
            "TargetName": credential["TargetName"],
            "UserName": credential["UserName"],
            "CredentialBlob": credential["CredentialBlob"].encode("utf-16-le"),
        }

    def CredDelete(self, Type: int, TargetName: str) -> None:  # noqa: N802, N803
        if self.refuse_deletes:
            raise keyring.errors.KeyringError("locked")
        if self.entries.pop(TargetName, None) is None:
            raise self._missing("CredDelete")

    def users(self) -> dict[str, str]:
        """Target name → user name, as ``cmdkey /list`` shows them."""
        return {target: entry["UserName"] for target, entry in self.entries.items()}


@pytest.fixture
def vault(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeVault]:
    fake = FakeVault()
    module = SimpleNamespace(
        CRED_TYPE_GENERIC=1,
        CRED_PERSIST_ENTERPRISE=3,
        CredRead=fake.CredRead,
        CredWrite=fake.CredWrite,
        CredDelete=fake.CredDelete,
    )
    monkeypatch.setattr(Windows, "win32cred", module)
    previous = keyring.get_keyring()
    keyring.set_keyring(Windows.WinVaultKeyring())  # type: ignore[no-untyped-call]
    yield fake
    keyring.set_keyring(previous)


REAL = AppPaths.resolve({"APPDATA": "C:/AppData"})
COPY = AppPaths.resolve({"HABIT_TRACKER_HOME": "C:/Temp/ht-policy-test"})


def credential(token: str) -> StoredCredential:
    return StoredCredential(
        kind="oauth", access_token=Secret(token), refresh_token=Secret(f"{token}-refresh")
    )


def token_of(store: CredentialStore) -> str | None:
    loaded = store.load()
    return loaded.access_token.reveal() if loaded else None


def test_the_real_app_keeps_its_entry_name() -> None:
    store = CredentialStore.for_paths(REAL)
    assert (store.service, store.account, store.legacy_account) == ("HabitTracker", "notion", None)


def test_each_data_folder_gets_its_own_service() -> None:
    copy = CredentialStore.for_paths(COPY)
    other = CredentialStore.for_paths(AppPaths.resolve({"HABIT_TRACKER_HOME": "C:/elsewhere"}))
    assert copy.service == f"HabitTracker-{COPY.instance_id}"
    assert copy.account == "notion"
    assert copy.legacy_account == f"notion-{COPY.instance_id}"
    assert len({SERVICE_NAME, copy.service, other.service}) == 3
    assert COPY.instance_lock_name != REAL.instance_lock_name


def test_a_copy_never_touches_the_real_entry(vault: FakeVault) -> None:
    real = CredentialStore.for_paths(REAL)
    copy = CredentialStore.for_paths(COPY)
    real.save(credential("real-token"))
    before = dict(vault.entries["HabitTracker"])

    copy.save(credential("copy-token"))
    assert vault.users() == {"HabitTracker": "notion", copy.service: "notion"}
    assert vault.entries["HabitTracker"] == before
    assert token_of(copy) == "copy-token"

    copy.delete()
    assert vault.users() == {"HabitTracker": "notion"}
    assert token_of(real) == "real-token"


def test_the_real_app_still_reads_an_entry_an_old_copy_moved(vault: FakeVault) -> None:
    """Before the fix, a copy's save moved the real entry to ``notion@HabitTracker``."""
    real = CredentialStore.for_paths(REAL)
    real.save(credential("real-token"))
    keyring.set_password(SERVICE_NAME, f"notion-{COPY.instance_id}", credential("x").to_json())
    assert vault.users()["notion@HabitTracker"] == "notion"

    assert token_of(real) == "real-token"
    real.save(credential("renewed"))  # renewing keeps working
    assert token_of(real) == "renewed"
    real.delete()  # logout removes every copy of the real entry
    assert "notion" not in vault.users().values()


def test_a_copy_moves_its_old_shared_entry_to_its_own(vault: FakeVault) -> None:
    """The state found on the dev PC: the copy's sign-in on the bare ``HabitTracker`` target."""
    legacy_account = f"notion-{COPY.instance_id}"
    keyring.set_password(SERVICE_NAME, legacy_account, credential("copy-token").to_json())
    assert vault.users() == {"HabitTracker": legacy_account}

    copy = CredentialStore.for_paths(COPY)
    assert token_of(copy) == "copy-token"
    assert vault.users() == {copy.service: "notion"}
    assert token_of(CredentialStore.for_paths(REAL)) is None


def test_a_copy_moves_its_old_entry_without_disturbing_the_real_one(vault: FakeVault) -> None:
    real = CredentialStore.for_paths(REAL)
    legacy_account = f"notion-{COPY.instance_id}"
    real.save(credential("real-token"))
    keyring.set_password(SERVICE_NAME, legacy_account, credential("copy-token").to_json())
    real_entry = dict(vault.entries["notion@HabitTracker"])

    copy = CredentialStore.for_paths(COPY)
    assert token_of(copy) == "copy-token"
    assert vault.users() == {"notion@HabitTracker": "notion", copy.service: "notion"}
    assert vault.entries["notion@HabitTracker"] == real_entry
    assert token_of(real) == "real-token"


def test_a_copys_logout_removes_an_old_entry_it_couldnt_move(vault: FakeVault) -> None:
    legacy_account = f"notion-{COPY.instance_id}"
    keyring.set_password(SERVICE_NAME, legacy_account, credential("copy-token").to_json())
    copy = CredentialStore.for_paths(COPY)
    vault.refuse_deletes = True
    assert token_of(copy) == "copy-token"  # moved, but the old entry stayed
    assert vault.users() == {"HabitTracker": legacy_account, copy.service: "notion"}

    vault.refuse_deletes = False
    copy.delete()
    assert vault.users() == {}
