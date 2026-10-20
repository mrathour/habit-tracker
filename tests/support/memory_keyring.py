"""An in-memory keyring, so tests never touch Windows Credential Manager.

Every pytest test uses it (tests/conftest.py). The end-to-end harness selects it in its
subprocess with ``PYTHON_KEYRING_BACKEND=tests.support.memory_keyring.MemoryKeyring``.
"""

from __future__ import annotations

from typing import ClassVar

import keyring.backend
import keyring.errors


class MemoryKeyring(keyring.backend.KeyringBackend):
    priority = 1
    store: ClassVar[dict[tuple[str, str], str]] = {}
    #: Set to an exception instance to make the next operations fail, simulating a broken vault.
    fail_with: ClassVar[keyring.errors.KeyringError | None] = None

    def _check(self) -> None:
        if MemoryKeyring.fail_with is not None:
            raise MemoryKeyring.fail_with

    def get_password(self, service: str, username: str) -> str | None:
        self._check()
        return self.store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._check()
        self.store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self._check()
        if (service, username) not in self.store:
            raise keyring.errors.PasswordDeleteError("not found")
        del self.store[(service, username)]

    @classmethod
    def reset(cls) -> None:
        cls.store.clear()
        cls.fail_with = None
