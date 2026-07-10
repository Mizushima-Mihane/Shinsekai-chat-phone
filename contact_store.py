"""Contact management: add/remove contacts, persisted as JSON."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_CONTACTS_PATH = Path("data/plugins/com.shinsekai.chat_phone/contacts.json")


def _default_contacts_path() -> Path:
    return _DEFAULT_CONTACTS_PATH


class ContactStore:
    """Thread-safe contact list persisted to a local JSON file.

    Only characters that have "exchanged contacts" in the story appear here —
    not the full character roster.  Contacts survive app restarts but are
    lightweight enough to be edited by hand if needed.
    """

    def __init__(self, file_path: Path | None = None) -> None:
        self._file = Path(file_path) if file_path is not None else _default_contacts_path()
        self._lock = threading.Lock()
        self._contacts: dict[str, dict] = {}
        self._load()

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def get_contacts(self) -> list[str]:
        """Return sorted list of character names that are currently contacts."""
        with self._lock:
            return sorted(k for k in self._contacts.keys() if k and k.strip())

    def is_contact(self, name: str) -> bool:
        with self._lock:
            return name in self._contacts

    def is_known(self, name: str) -> bool:
        """True if the contact formally exchanged (legacy contacts & non-contacts → True)."""
        with self._lock:
            entry = self._contacts.get(name)
            return True if entry is None else bool(entry.get("known", True))

    def add_contact(self, name: str, known: bool = True) -> bool:
        """Add a character as a contact. Returns True if newly added or upgraded.

        ``known=False`` records an *unknown contact* — a character who got the
        player's number without formally exchanging (shown as「未知联系人」). Calling
        again with ``known=True`` (e.g. exchange_contacts) upgrades it to known.
        """
        if not name or not name.strip():
            return False
        with self._lock:
            if name in self._contacts:
                if known and not self._contacts[name].get("known", True):
                    self._contacts[name]["known"] = True  # upgrade unknown → known
                else:
                    return False
            else:
                self._contacts[name] = {"added_at": _now(), "known": bool(known)}
        self._save()
        logger.info("Contact added/updated: %s (known=%s)", name, known)
        return True

    def remove_contact(self, name: str) -> bool:
        """Remove a character from contacts.  Returns True if it existed."""
        with self._lock:
            existed = self._contacts.pop(name, None) is not None
        if existed:
            self._save()
            logger.info("Contact removed: %s", name)
        return existed

    def touch_interaction(self, name: str) -> None:
        """Update the last-interaction timestamp for *name*."""
        with self._lock:
            if name in self._contacts:
                self._contacts[name]["last_interaction"] = _now()
        self._save()

    def last_interaction(self, name: str) -> float:
        with self._lock:
            entry = self._contacts.get(name)
            if entry is None:
                return 0.0
            return float(entry.get("last_interaction", entry.get("added_at", 0)))

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _load(self) -> None:
        try:
            if self._file.is_file():
                raw = json.loads(self._file.read_text(encoding="utf-8"))
                self._contacts = raw.get("contacts", {})
        except Exception:
            logger.debug("Failed to load contacts, starting fresh.", exc_info=True)
            self._contacts = {}

    def _save(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            payload = {"contacts": self._contacts}
            self._file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            logger.exception("Failed to save contacts to %s", self._file)


def _now() -> float:
    import time
    return time.time()
