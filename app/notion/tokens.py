"""The current Notion access, and how it is renewed (PLAN.md 12.5).

Rules:

* **Write before use.** Notion rotates refresh tokens, so a renewed pair is saved to Credential
  Manager before anything uses it. If saving fails, the pair is kept in memory and the next
  request retries the save before calling Notion; nothing runs on an unsaved pair.
* **One renewal at a time.** A single lock serializes renewals. A caller that hit a 401 with a
  token that has already been replaced simply gets the newer token, so ten parallel 401s cause
  exactly one renewal.
* **Pasted tokens can't be renewed.** A 401 on a pasted token means "paste a new token".
* Renewal happens only after a 401, never on a timer.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import replace

from app.notion.credentials import CredentialStore, StoredCredential, utc_now
from app.notion.errors import NotConnectedError, PasteNewTokenError
from app.notion.service_client import TokenServiceClient
from app.redaction import Secret

logger = logging.getLogger(__name__)


class TokenManager:
    def __init__(self, store: CredentialStore, service: TokenServiceClient) -> None:
        self._store = store
        self._service = service
        self._lock = threading.Lock()
        self._current: StoredCredential | None = None
        self._unsaved: StoredCredential | None = None
        self._loaded = False

    # --- reading --------------------------------------------------------------------------

    def _load_locked(self) -> StoredCredential | None:
        if not self._loaded:
            self._current = self._store.load()
            self._loaded = True
        return self._current

    def credential(self) -> StoredCredential | None:
        """The stored connection, or None if the app isn't connected."""
        with self._lock:
            self._flush_unsaved_locked()
            return self._load_locked()

    def access_token(self) -> Secret:
        """The token to call Notion with. Retries a pending save first (write before use)."""
        with self._lock:
            self._flush_unsaved_locked()
            current = self._load_locked()
            if current is None:
                raise NotConnectedError
            return current.access_token

    # --- changing -------------------------------------------------------------------------

    def replace_credential(self, credential: StoredCredential) -> None:
        """Save a new connection (after connecting or pasting a token), then start using it."""
        with self._lock:
            self._store.save(credential)
            self._current = credential
            self._unsaved = None
            self._loaded = True

    def forget(self) -> StoredCredential | None:
        """Delete the stored connection. Returns what was stored, for revoking."""
        with self._lock:
            previous = self._unsaved or self._load_locked()
            self._store.delete()
            self._current = None
            self._unsaved = None
            self._loaded = True
            return previous

    def renew_after_unauthorized(self, rejected: Secret) -> Secret:
        """Called when Notion answered 401 to ``rejected``. Returns a token to retry with."""
        with self._lock:
            self._flush_unsaved_locked()
            current = self._load_locked()
            if current is None:
                raise NotConnectedError
            if current.access_token != rejected:
                # Another caller already renewed while this one waited for the lock.
                return current.access_token
            if not current.can_refresh or current.refresh_token is None:
                raise PasteNewTokenError(detail=f"Notion returned 401 for a {current.kind} token.")
            logger.info("Notion returned 401; renewing access through the token service")
            grant = self._service.refresh(current.refresh_token)
            renewed = replace(
                current,
                access_token=grant.access_token,
                refresh_token=grant.refresh_token,
                obtained_at=utc_now(),
            )
            # Write before use. If this raises, the pair waits in memory for the next attempt.
            self._unsaved = renewed
            self._flush_unsaved_locked()
            return renewed.access_token

    def _flush_unsaved_locked(self) -> None:
        if self._unsaved is None:
            return
        self._store.save(self._unsaved)
        self._current = self._unsaved
        self._unsaved = None
        self._loaded = True
