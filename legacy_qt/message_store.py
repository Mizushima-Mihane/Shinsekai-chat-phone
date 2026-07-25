"""In-memory per-character message store for the chat phone."""

from __future__ import annotations

import threading
import time
from typing import Literal

MessageType = Literal["text", "call_missed", "call_outgoing", "call_incoming"]


class MessageStore:
    """Thread-safe store of chat-phone messages, keyed by character name.

    Each message is a plain dict:
        {"text": str, "is_user": bool, "timestamp": float,
         "type": MessageType, "unread": bool}
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._messages: dict[str, list[dict]] = {}

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def add_message(
        self,
        character: str,
        text: str,
        *,
        is_user: bool = False,
        msg_type: MessageType = "text",
    ) -> None:
        """Append a message to *character*'s thread."""
        entry = {
            "text": text,
            "is_user": is_user,
            "timestamp": time.time(),
            "type": msg_type,
            "unread": not is_user,  # incoming messages start unread
        }
        with self._lock:
            self._messages.setdefault(character, []).append(entry)

    def get_messages(self, character: str) -> list[dict]:
        """Return a shallow copy of the message list for *character*."""
        with self._lock:
            return list(self._messages.get(character, []))

    def mark_all_read(self, character: str) -> int:
        """Mark every message for *character* as read.  Returns count changed."""
        changed = 0
        with self._lock:
            for m in self._messages.get(character, []):
                if m.get("unread"):
                    m["unread"] = False
                    changed += 1
        return changed

    def total_unread(self) -> int:
        """Total unread messages across all characters."""
        with self._lock:
            return sum(
                1
                for msgs in self._messages.values()
                for m in msgs
                if m.get("unread")
            )

    def unread_per_character(self) -> dict[str, int]:
        """Return {character_name: unread_count} for characters with >0 unread."""
        with self._lock:
            return {
                name: sum(1 for m in msgs if m.get("unread"))
                for name, msgs in self._messages.items()
                if any(m.get("unread") for m in msgs)
            }

    def last_message(self, character: str) -> dict | None:
        """Return the most recent message for *character* or None."""
        with self._lock:
            msgs = self._messages.get(character, [])
            return msgs[-1] if msgs else None

    def last_message_preview(self, character: str, max_len: int = 30) -> str:
        """Short preview text for the contact list."""
        msg = self.last_message(character)
        if msg is None:
            return ""
        text = msg["text"].replace("\n", " ")
        if len(text) > max_len:
            text = text[: max_len - 1] + "…"
        return text
