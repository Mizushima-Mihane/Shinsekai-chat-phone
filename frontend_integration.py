"""React Chat integration for the Chat Phone plugin.

The host remains unaware of phone-specific events.  This module translates the
plugin's existing ``CALL`` dialog marker into the generic frontend page
presentation API introduced by Shinsekai.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterable
from typing import Any

logger = logging.getLogger(__name__)

PAGE_ID = "chat-phone"
TOP_BAR_CONTRIBUTION_ID = "chat-phone.top-bar"
INCOMING_CALL_PRESENTATION_ID = "chat-phone.incoming-call"

_controller_lock = threading.RLock()
_frontend_ui: Any | None = None


def bind_frontend_ui(controller: Any) -> None:
    """Retain the plugin-scoped host controller created during initialization."""
    global _frontend_ui
    with _controller_lock:
        _frontend_ui = controller


def clear_frontend_ui() -> None:
    global _frontend_ui
    with _controller_lock:
        _frontend_ui = None


def present_incoming_call(character: str, call_type: str = "voice") -> bool:
    """Present the phone page for an incoming call when React Chat is active."""
    caller = str(character or "").strip()
    if not caller:
        return False
    normalized_type = "video" if str(call_type or "").strip().lower() == "video" else "voice"
    with _controller_lock:
        controller = _frontend_ui
    if controller is None:
        return False
    try:
        controller.present_page(
            PAGE_ID,
            presentation_id=INCOMING_CALL_PRESENTATION_ID,
            payload={
                "view": "incoming-call",
                "caller": caller,
                "callType": normalized_type,
            },
        )
        return True
    except RuntimeError:
        # Expected when the plugin is loaded without an active React Chat session.
        logger.debug("React Chat is not active; skip incoming-call presentation")
    except Exception:
        logger.exception("Failed to present incoming Chat Phone page")
    return False


def _parse_dialog_payload(content: object) -> tuple[str, dict[str, Any] | list[Any]] | None:
    if isinstance(content, (dict, list)):
        return "", content
    if not isinstance(content, str):
        return None
    raw = content.strip()
    if not raw:
        return None
    prefix = ""
    if not raw.startswith(("{", "[")):
        starts = [index for index in (raw.find("{"), raw.find("[")) if index >= 0]
        if not starts:
            return None
        start = min(starts)
        prefix = raw[:start]
        raw = raw[start:]
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, (dict, list)):
        return None
    return prefix, parsed


def _dialog_items(payload: dict[str, Any] | list[Any]) -> list[Any]:
    if isinstance(payload, list):
        return payload
    items = payload.get("dialog", [])
    return items if isinstance(items, list) else []


def extract_incoming_call(
    content: object,
    known_characters: Iterable[str],
) -> tuple[str, str] | None:
    """Return ``(caller, call_type)`` for the first valid explicit CALL marker."""
    parsed = _parse_dialog_payload(content)
    if parsed is None:
        return None
    _, payload = parsed
    known = {str(name or "").strip() for name in known_characters}
    known.discard("")
    for item in _dialog_items(payload):
        if not isinstance(item, dict):
            continue
        marker = str(item.get("character_name") or "").strip()
        speech = str(item.get("speech") or "").strip()
        if marker != "CALL" or not speech:
            continue
        caller = speech.split(":", 1)[0].split("：", 1)[0].strip()
        if not caller or caller not in known:
            continue
        call_type = "video" if ("视频" in speech or "video" in speech.lower()) else "voice"
        return caller, call_type
    return None


def strip_incoming_call_markers(content: object) -> str | None:
    """Remove explicit CALL markers while preserving the remaining dialog payload."""
    parsed = _parse_dialog_payload(content)
    if parsed is None:
        return None
    prefix, payload = parsed
    if not isinstance(payload, dict):
        return None
    items = payload.get("dialog")
    if not isinstance(items, list):
        return None
    filtered = [
        item
        for item in items
        if not (
            isinstance(item, dict)
            and str(item.get("character_name") or "").strip() == "CALL"
        )
    ]
    if len(filtered) == len(items):
        return None
    updated = dict(payload)
    updated["dialog"] = filtered
    return prefix + json.dumps(updated, ensure_ascii=False)
