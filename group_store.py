"""Group-chat store — groups keyed by name, each with members and messages.

Persisted to a per-session JSON file so groups follow the chat session (same
isolation model as single-SMS / contacts).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path


class GroupStore:
    """Thread-safe store of group chats, keyed by group name.

    Each group is a dict::

        {"name": str, "members": list[str], "messages": list[dict]}

    Each message::

        {"sender": str, "text": str, "is_user": bool, "idx": int}

    ``sender`` is the character name; for the player ``is_user=True``.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._groups: dict[str, dict] = {}
        self._msg_idx = 0
        self._load()

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        try:
            if self._path.is_file():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._groups = data.get("groups", {})
                    self._msg_idx = int(data.get("msg_idx", 0))
        except Exception:
            self._groups = {}
            self._msg_idx = 0

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps({"groups": self._groups, "msg_idx": self._msg_idx},
                           ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # groups
    # ------------------------------------------------------------------

    def create_group(self, name: str, members: list[str]) -> str:
        """Create a group; returns the final (de-duplicated) group name."""
        name = (name or "").strip()
        if not name:
            return ""
        with self._lock:
            base, i = name, 2
            while name in self._groups:
                name = f"{base}{i}"
                i += 1
            self._groups[name] = {
                "name": name,
                "members": [m for m in dict.fromkeys(members) if m],  # dedupe, keep order
                "messages": [],
            }
            self._save()
        return name

    def delete_group(self, name: str) -> bool:
        with self._lock:
            if name in self._groups:
                del self._groups[name]
                self._save()
                return True
        return False

    def get_group_names(self) -> list[str]:
        with self._lock:
            return list(self._groups.keys())

    def get_group(self, name: str) -> dict | None:
        with self._lock:
            g = self._groups.get(name)
            return dict(g) if g else None

    def has_group(self, name: str) -> bool:
        with self._lock:
            return name in self._groups

    def get_members(self, name: str) -> list[str]:
        with self._lock:
            g = self._groups.get(name)
            return list(g["members"]) if g else []

    def add_member(self, name: str, member: str) -> bool:
        member = (member or "").strip()
        with self._lock:
            g = self._groups.get(name)
            if g and member and member not in g["members"]:
                g["members"].append(member)
                self._save()
                return True
        return False

    def remove_member(self, name: str, member: str) -> bool:
        with self._lock:
            g = self._groups.get(name)
            if g and member in g["members"]:
                g["members"].remove(member)
                self._save()
                return True
        return False

    # ------------------------------------------------------------------
    # messages
    # ------------------------------------------------------------------

    def add_message(self, name: str, sender: str, text: str, *, is_user: bool = False) -> None:
        with self._lock:
            g = self._groups.get(name)
            if not g:
                return
            self._msg_idx += 1
            g["messages"].append({
                "sender": sender,
                "text": text,
                "is_user": is_user,
                "idx": self._msg_idx,
            })
            self._save()

    def get_messages(self, name: str) -> list[dict]:
        with self._lock:
            g = self._groups.get(name)
            return list(g["messages"]) if g else []

    def last_preview(self, name: str, max_len: int = 24) -> str:
        """Short 'who: text' preview for the group list."""
        with self._lock:
            g = self._groups.get(name)
            if not g or not g["messages"]:
                return ""
            m = g["messages"][-1]
            who = "我" if m.get("is_user") else m.get("sender", "")
            t = f"{who}: {m.get('text', '')}".replace("\n", " ")
            return t[: max_len - 1] + "…" if len(t) > max_len else t
