"""Helper for packaging/test-installer.ps1: put a fake pasted token in Credential Manager, or
report whether the app's entry exists. Never run it on a PC whose real sign-in matters.

    uv run python packaging/credential_probe.py store-internal
    uv run python packaging/credential_probe.py exists      # prints "yes" or "no"
"""

import sys

from app.notion.credentials import CredentialStore, StoredCredential, utc_now
from app.redaction import Secret


def main(command: str) -> int:
    store = CredentialStore()  # the installed app's real account, "notion"
    if command == "store-internal":
        store.save(
            StoredCredential(
                kind="internal",
                access_token=Secret("installer-test-not-a-real-token"),
                obtained_at=utc_now(),
            )
        )
        return 0
    if command == "exists":
        sys.stdout.write("yes\n" if store.load() is not None else "no\n")
        return 0
    sys.stderr.write(f"unknown command {command!r}\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
