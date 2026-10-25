"""Privacy-policy change notices (PLAN.md 13).

Each build bundles ``app/policy.json``: the policy version it was built for and a plain-language
summary of each version's changes. The ``acknowledged_policy_version`` setting records the newest
version the user has seen.

* **Notice:** when the bundled version is newer than the acknowledged one, the app shows the
  changes before it does anything else, including syncing. Acknowledging saves the bundled
  version.
* **Fresh installs** show no notice. The bundled version is saved when the user first connects,
  which is where the policy is linked.
* **Connected before notices existed:** a copy of the app that connected before this setting
  existed did so under version 1, the first policy.
* **No website contact:** everything comes from the bundled file. The app never checks the
  website for policy changes, because the policy says it uses the website only when connecting,
  renewing and disconnecting.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict, TypeGuard

from app.db.settings import Settings
from app.errors import AppError

logger = logging.getLogger(__name__)

POLICY_FILE: Final = Path(__file__).resolve().parent / "policy.json"
ACKNOWLEDGED_KEY: Final = "acknowledged_policy_version"
#: The version a copy of the app agreed to if it connected before notices existed.
FIRST_VERSION: Final = 1


class PolicyChangeInfo(TypedDict):
    version: int
    date: str
    summary: list[str]


class PolicyNotice(TypedDict):
    version: int
    acknowledged_version: int
    url: str
    #: Every change since the acknowledged version, oldest first.
    changes: list[PolicyChangeInfo]


@dataclass(frozen=True, slots=True)
class PolicyChange:
    version: int
    date: str
    summary: tuple[str, ...]

    def to_dict(self) -> PolicyChangeInfo:
        return {"version": self.version, "date": self.date, "summary": list(self.summary)}


@dataclass(frozen=True, slots=True)
class BundledPolicy:
    version: int
    url: str
    changes: tuple[PolicyChange, ...]

    def changes_after(self, acknowledged: int) -> list[PolicyChange]:
        return [c for c in self.changes if acknowledged < c.version <= self.version]


class PolicyFileError(ValueError):
    """The bundled policy file is malformed: a build mistake, caught by tests and the build."""


def load_policy(path: Path | None = None) -> BundledPolicy:
    """Read and check the bundled policy file (``POLICY_FILE`` unless ``path`` is given)."""
    path = path or POLICY_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PolicyFileError(f"{path.name} can't be read: {exc}") from exc
    if not isinstance(raw, dict):
        raise PolicyFileError("the policy file must hold an object")
    version = raw.get("version")
    url = raw.get("url")
    entries = raw.get("changes")
    if not _is_version(version):
        raise PolicyFileError("version must be a whole number of at least 1")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise PolicyFileError("url must be an https:// address")
    if not isinstance(entries, list):
        raise PolicyFileError("changes must be a list")
    changes: list[PolicyChange] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise PolicyFileError("each change must be an object")
        change_version = entry.get("version")
        date = entry.get("date")
        summary = entry.get("summary")
        if not _is_version(change_version):
            raise PolicyFileError("each change needs a version of at least 1")
        if not isinstance(date, str) or len(date) != 10:
            raise PolicyFileError(f"change {change_version} needs a YYYY-MM-DD date")
        if (
            not isinstance(summary, list)
            or not summary
            or not all(isinstance(line, str) and line.strip() for line in summary)
        ):
            raise PolicyFileError(f"change {change_version} needs a summary")
        changes.append(PolicyChange(change_version, date, tuple(summary)))
    versions = [c.version for c in changes]
    if versions != sorted(set(versions)):
        raise PolicyFileError("changes must be in order, one per version")
    if version not in versions or max(versions) != version:
        raise PolicyFileError(f"the newest change must be version {version}")
    return BundledPolicy(version=version, url=url, changes=tuple(changes))


def _is_version(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


class PolicyNotAcknowledgedError(AppError):
    """Something tried to run before the user saw a pending policy notice."""

    state = "policy_notice"


class PolicyService:
    def __init__(
        self,
        *,
        settings: Settings,
        has_connected: Callable[[], bool],
        policy: BundledPolicy | None = None,
    ) -> None:
        self._settings = settings
        self._has_connected = has_connected
        self._policy = policy or load_policy()

    @property
    def bundled_version(self) -> int:
        return self._policy.version

    def acknowledged_version(self) -> int | None:
        stored = self._settings.get(ACKNOWLEDGED_KEY)
        if _is_version(stored):
            return stored
        if stored is not None:
            logger.warning("Ignoring a damaged %s setting", ACKNOWLEDGED_KEY)
        return FIRST_VERSION if self._has_connected() else None

    def notice(self) -> PolicyNotice | None:
        """The notice to show before anything else, or None."""
        acknowledged = self.acknowledged_version()
        if acknowledged is None or acknowledged >= self._policy.version:
            return None
        return {
            "version": self._policy.version,
            "acknowledged_version": acknowledged,
            "url": self._policy.url,
            "changes": [c.to_dict() for c in self._policy.changes_after(acknowledged)],
        }

    def require_acknowledged(self) -> None:
        if self.notice() is not None:
            raise PolicyNotAcknowledgedError(
                "Read the privacy policy changes first.",
                detail="A policy notice is waiting to be acknowledged.",
            )

    def acknowledge(self, version: object) -> None:
        """Save the version the user just read. It must be the one this build shows."""
        if not _is_version(version) or version != self._policy.version:
            raise AppError(
                "That privacy notice is out of date. Close the app and open it again.",
                detail=f"acknowledged {version!r}, bundled {self._policy.version}",
            )
        self._save()
        logger.info("Privacy policy version %s acknowledged", self._policy.version)

    def record_connected(self) -> None:
        """A connection was made: the user saw the policy where Connect links it."""
        self._save()

    def _save(self) -> None:
        stored = self._settings.get(ACKNOWLEDGED_KEY)
        if _is_version(stored) and stored >= self._policy.version:
            return  # never lower it, for example after going back to an older build
        self._settings.set(ACKNOWLEDGED_KEY, self._policy.version)
