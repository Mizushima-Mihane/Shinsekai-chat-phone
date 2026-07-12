"""Main phone widget — Material 3 macaron, draggable, proper interactions."""

from __future__ import annotations

import enum
import json
import logging
import random
import re
import threading
import time
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve, QEvent, QPoint, QPropertyAnimation,
    QSequentialAnimationGroup, Qt, QTimer, Signal,
)
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from plugins.shinsekai_chat_phone.browser_app import BrowserApp
from plugins.shinsekai_chat_phone.call_view import CallView
from plugins.shinsekai_chat_phone.contact_store import ContactStore
from plugins.shinsekai_chat_phone.home_screen import HomeScreen
from plugins.shinsekai_chat_phone.video_call_view import VideoCallView
from plugins.shinsekai_chat_phone.messages_app import MessagesApp
from plugins.shinsekai_chat_phone.message_store import MessageStore
from plugins.shinsekai_chat_phone.music_app import MusicApp
from plugins.shinsekai_chat_phone.settings_app import SettingsApp
from plugins.shinsekai_chat_phone.phone_app import PhoneApp
from plugins.shinsekai_chat_phone.styles import PHONE_QSS, _darken
from plugins.shinsekai_chat_phone.voice_memo_app import VoiceMemosApp
from plugins.shinsekai_chat_phone.group_store import GroupStore
from plugins.shinsekai_chat_phone.group_chat_app import GroupChatApp
from plugins.shinsekai_chat_phone import sound_fx as _sfx

_logger = logging.getLogger("chat_phone.widget")

ICON_W, ICON_H = 44, 44
PHONE_W, PHONE_H = 280, 500
PHONE_MARGIN = 10
RING_TIMEOUT_MS = 25000  # unanswered incoming call auto-misses after ~25s of ringing

# Dialog markers / narration that must never become a call / SMS / group participant.
_RESERVED_NAMES = {"旁白", "NARR", "CALL", "COT", "CHOICE", "STAT", "PHONE", "bgm", "CG"}


def _data_dir() -> Path:
    """Phone data follows the CURRENT chat session.

    首选本次启动的 ``--history`` 参数（当前会话的准确 hash）。这样即使新开局的
    ``active.json`` 还没落盘（只有 ``active.json.tmp``、或尚未写入），也不会按 mtime
    误选到别的存档目录——那正是「新开局把手机数据写进/重置了旧存档」的根因。
    仅当拿不到 ``--history`` 时，才回退到「最新的、含 active.json(.tmp) 的目录」。
    """
    base = Path("data/plugins/com.shinsekai.chat_phone")
    # 1) 首选：本次启动的 --history（当前会话）
    import sys
    for _a in sys.argv:
        if _a.startswith("--history="):
            _hp = _a.split("=", 1)[1].strip().strip('"').strip("'")
            if _hp:
                _p = Path(_hp)
                _sess = _p if _p.suffix.lower() != ".json" else _p.parent
                if _sess.name:
                    return base / _sess.name
            break
    # 2) 回退：最新的、含 active.json 或 active.json.tmp 的 chat_history 目录
    ch_dir = Path("data/chat_history")
    if ch_dir.is_dir():
        dirs = sorted(ch_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        for d in dirs:
            if d.is_dir() and ((d / "active.json").exists() or (d / "active.json.tmp").exists()):
                return base / d.name
    # 3) 兜底
    d = base / "_default"
    d.mkdir(parents=True, exist_ok=True)
    return d


class _State(enum.Enum):
    COLLAPSED = 0
    HOME = 1
    APP = 2
    CALLING = 3
    INCOMING_CALL = 4
    IN_CALL = 5


class PhoneWidget(QWidget):
    contact_list_changed = Signal()
    new_proactive_message = Signal(str, str)
    _sms_deliver_signal = Signal(str, str)
    _incoming_call_signal = Signal(str, str)  # (character, call_type) — thread-safe LLM-driven incoming call
    _group_deliver_signal = Signal(str, str, str)  # (group, sender, text) — thread-safe group delivery
    _group_refresh_signal = Signal()  # LLM created a group — refresh list on GUI thread
    _group_event_signal = Signal(str, str, str)  # (action, group, arg) — membership/rename/removal → GUI

    def __init__(self, submit_cb: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._submit_cb = submit_cb
        self._state = _State.COLLAPSED
        self._previous_state = _State.COLLAPSED
        self._current_app = ""
        self._call_char = ""
        self._call_start: float = 0
        self._call_type = ""
        self._call_mode: str = "voice"  # "voice" or "video"
        self._call_mode_preset: str = "voice"  # preset from home screen app
        self._hangup_attempts: int = 0
        # SMS tracking: only route replies that follow an SMS send
        self._sms_pending: set[str] = set()  # characters awaiting SMS reply
        # Call dialogue buffer — for hangup-block detection
        self._call_dialogue: list[str] = []
        self._sms_stagger: int = 0  # counter for staggered SMS delivery
        self._group_delay: float = 0.0  # accumulated delay for the current group reply batch
        self._group_delay_time: float = 0.0  # last group-reply schedule time (fallback batch reset)
        self._sms_lock = threading.Lock()
        # Debounce state
        self._last_badge_count: int = -1
        self._refresh_queued: bool = False

        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        # ── drag state ──
        self._dragging = False
        self._drag_start: QPoint | None = None
        self._drag_press_time: float = 0

        # ── keep-on-top ──
        self._raise_timer = QTimer(self)
        self._raise_timer.timeout.connect(self._keep_on_top)
        self._raise_timer.setInterval(500)

        # ── data ──
        self._data_dir = _data_dir()
        import plugins.shinsekai_chat_phone.phone_app as _pa
        _pa.set_call_log_dir(self._data_dir)
        # Session-scoped settings (dnd / hacked_characters / yandere_tampering)
        # follow the chat session — inject dir before any settings read below.
        import plugins.shinsekai_chat_phone.settings_app as _sa
        _sa.set_session_dir(self._data_dir)
        self._contact_store = ContactStore(self._data_dir / "contacts.json")
        self._message_store = MessageStore()
        self._group_store = GroupStore(self._data_dir / "groups.json")

        self.setStyleSheet(PHONE_QSS)

        # ── floating toggle button (always visible) ──
        from PySide6.QtWidgets import QPushButton
        self._toggle_btn = QPushButton("\U0001F4F1", self)  # 📱
        self._toggle_btn.setFixedSize(ICON_W, ICON_H)
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._toggle_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; outline: none; font-size: 28px; }"
            "QPushButton:hover { font-size: 32px; }"
            "QPushButton:focus { background: transparent; border: none; outline: none; }"
        )
        self._toggle_btn.clicked.connect(self._on_floating_icon_click)

        # ── badge ──
        import random
        bid = f"badge_{random.randint(0,9999)}"
        self._badge = QLabel("", self)
        self._badge.setObjectName(bid)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setStyleSheet(
            f"#{bid} {{ background: #FF3B30; color: white;"
            " border: 2px solid white; border-radius: 11px;"
            " font-size: 10px; font-weight: bold;"
            " min-width: 22px; min-height: 22px; }"
        )
        self._badge.hide()

        # ── phone frame ──
        self._frame = QWidget(self)
        self._frame.setObjectName("PhoneFrame")
        self._frame.setFixedSize(PHONE_W, PHONE_H)
        from plugins.shinsekai_chat_phone.settings_app import get_theme
        theme = get_theme()
        self._theme = _darken(theme, 0.06)
        self._frame.setStyleSheet(
            f"#PhoneFrame {{ background-color: {self._theme}; border: 1px solid #D8CDCD; border-radius: 28px; }}"
        )
        from PySide6.QtWidgets import QGraphicsDropShadowEffect
        from PySide6.QtGui import QColor
        shadow = QGraphicsDropShadowEffect(self._frame)
        shadow.setBlurRadius(24); shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 60))
        self._frame.setGraphicsEffect(shadow)
        # Round all content via mask
        from PySide6.QtGui import QRegion, QPainterPath
        path = QPainterPath()
        path.addRoundedRect(0, 0, PHONE_W, PHONE_H, 28, 28)
        self._frame.setMask(QRegion(path.toFillPolygon().toPolygon()))
        self._frame.hide()

        frame_layout = QVBoxLayout(self._frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)

        # ── home + apps ──
        self._home = HomeScreen(self._frame)
        self._home.app_launched.connect(self._launch_app)
        self._home.minimize_requested.connect(lambda: self._apply_state(_State.COLLAPSED))

        self._messages_app = MessagesApp(self._message_store, self._frame)
        self._messages_app.set_submit_callback(self._submit_cb)
        self._messages_app.set_sms_sent_callback(self._on_sms_sent)
        self._messages_app.set_save_callback(self._save_messages)
        self._messages_app.set_read_callback(self._update_badge)
        self._messages_app.on_back.connect(self._go_home)
        self._messages_app.on_call.connect(self._start_call)

        self._phone_app = PhoneApp([], self._frame)
        self._phone_app.on_back.connect(self._go_home)
        self._phone_app.on_call.connect(self._start_call)


        self._memos_app = VoiceMemosApp(self._data_dir, self._frame)
        self._memos_app.on_back.connect(self._go_home)


        self._browser_app = BrowserApp(self._data_dir, self._frame)
        self._browser_app.on_back.connect(self._go_home)

        self._music_app = MusicApp(self._frame)
        self._music_app.on_back.connect(self._go_home)
        self._music_app.set_submit_callback(self._submit_cb)
        self._music_app.set_contact_store(self._contact_store)

        self._settings_app = SettingsApp(self._frame)
        self._settings_app.on_back.connect(self._go_home)

        # Placeholder apps — each with a back button so it isn't a dead end.
        self._location_app = _placeholder_app("定位功能开发中...", self._go_home, self._frame)
        self._video_placeholder = _placeholder_app("视频功能开发中...", self._go_home, self._frame)
        self._group_app = GroupChatApp(self._group_store, self._frame)
        self._group_app.on_back.connect(self._go_home)
        self._group_app.set_submit_callback(self._submit_cb)
        self._group_app.set_sent_callback(self._on_group_sent)
        self._group_app.set_manage_callback(self._on_player_manage)
        self._group_app.set_read_callback(self._update_group_badge)
        self._moments_placeholder = _placeholder_app("朋友圈功能开发中...", self._go_home, self._frame)

        # Rounded corner mask for call views (matches phone frame 28px radius)
        call_mask_path = QPainterPath()
        call_mask_path.addRoundedRect(0, 0, PHONE_W, PHONE_H, 28, 28)
        call_mask = QRegion(call_mask_path.toFillPolygon().toPolygon())

        # Call views — direct children of PhoneWidget (NOT inside _frame)
        # so they stay visible when _frame is hidden during calls.
        self._call_view = CallView(self)
        self._call_view.setGeometry(0, 0, PHONE_W, PHONE_H)
        self._call_view.setMask(call_mask)
        self._call_view.hide()
        self._call_view.on_accept.connect(self._call_accept)
        self._call_view.on_decline.connect(self._call_decline)
        self._call_view.on_hangup.connect(self._call_hangup)

        self._video_call_view = VideoCallView(self)
        self._video_call_view.setGeometry(0, 0, PHONE_W, PHONE_H)
        self._video_call_view.setMask(call_mask)
        self._video_call_view.hide()
        self._video_call_view.on_accept.connect(self._call_accept)
        self._video_call_view.on_decline.connect(self._call_decline)
        self._video_call_view.on_hangup.connect(self._call_hangup)

        # stack — app widgets inside phone frame
        for w in [self._home, self._messages_app, self._phone_app,
                   self._memos_app, self._browser_app, self._music_app,
                   self._settings_app, self._location_app, self._video_placeholder,
                   self._group_app, self._moments_placeholder]:
            frame_layout.addWidget(w)

        self._sms_deliver_signal.connect(self._deliver_sms)
        self.new_proactive_message.connect(self._on_proactive_message)
        self._incoming_call_signal.connect(self._on_llm_incoming_call)
        self._group_deliver_signal.connect(self._deliver_group)
        self._group_refresh_signal.connect(self._on_group_refresh)
        self._group_event_signal.connect(self._on_group_event)

        # ── load saved messages ──
        self._load_messages()

        self._show_home()
        self._apply_state(_State.COLLAPSED)
        self._update_badge()

    def _msg_file(self) -> Path:
        return self._data_dir / "messages.json"

    def _load_messages(self):
        try:
            p = self._msg_file()
            if p.is_file():
                data = json.loads(p.read_text(encoding="utf-8"))
                max_idx = 0
                for name, msgs in data.items():
                    for m in msgs:
                        idx = m.get("idx", 0)
                        if not idx:
                            max_idx += 1; idx = max_idx
                        else:
                            max_idx = max(max_idx, idx)
                        self._messages_app._own_messages.setdefault(name, []).append({
                            "text": m.get("text", ""),
                            "is_user": m.get("is_user", False),
                            "idx": idx,
                        })
                self._messages_app._msg_idx = max_idx
        except Exception:
            pass

    def _save_messages(self):
        try:
            data = {}
            for name, msgs in self._messages_app._own_messages.items():
                data[name] = [{"text": m["text"], "is_user": m["is_user"], "idx": m.get("idx", 0)}
                              for m in msgs[-100:]]
            self._msg_file().write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ==================================================================
    # public API
    # ==================================================================

    def contact_store(self) -> ContactStore:
        return self._contact_store
    def message_store(self) -> MessageStore:
        return self._message_store

    def load_contacts(self):
        names = self._contact_store.get_contacts()
        known = [n for n in names if self._contact_store.is_known(n)]
        unknown = {n for n in names if not self._contact_store.is_known(n)}
        unread = self._message_store.unread_per_character()
        previews = {n: self._message_store.last_message_preview(n) for n in names}
        self._messages_app.refresh(names, unread, previews, unknown)
        self._phone_app.refresh_contacts(known)   # strangers aren't dialable
        self._group_app.set_contacts(known)       # nor addable to groups

    def add_contact(self, name: str) -> bool:
        if not name or not name.strip():
            return False
        added = self._contact_store.add_contact(name)
        if added:
            self.load_contacts()
        return added

    def _is_in_chat_with(self, character: str) -> bool:
        """Check if we're currently viewing the Messages app chat with *character*."""
        return (
            self._state != _State.COLLAPSED
            and self._current_app == "messages"
            and self._messages_app._view == "chat"
            and self._messages_app._character == character
        )

    def _is_viewing_group(self, group: str) -> bool:
        """Check if we're currently viewing this group's chat in the Group app."""
        return (
            self._state != _State.COLLAPSED
            and self._current_app == "group"
            and self._group_app._view == "chat"
            and self._group_app._group == group
        )

    def _update_group_badge(self):
        """Refresh the 群聊 home-icon badge + floating badge from group unread."""
        if getattr(self, "_home", None) is not None:
            self._home.set_group_badge(self._group_store.total_unread())
        self._update_badge()

    def notify_new_message(self, character: str, text: str):
        self._message_store.add_message(character, text, is_user=False)
        self._messages_app.add_received_message(character, text)
        self._save_messages()
        # Queue this proactive SMS so the main story learns about it on the
        # next turn (proactive SMS otherwise never reaches the main chat).
        self._record_pending_proactive(character, text)
        # If already chatting with this character, mark read & skip shake
        if self._is_in_chat_with(character):
            self._message_store.mark_all_read(character)
        self._update_badge()
        self._refresh_all()
        from plugins.shinsekai_chat_phone.settings_app import is_dnd
        if not self._is_in_chat_with(character) and not is_dnd():
            self._shake()

    def _record_pending_proactive(self, character: str, text: str):
        """Append a proactive SMS to the pending-sync queue (session-scoped)."""
        try:
            p = self._data_dir / "pending_proactive.json"
            data = []
            if p.is_file():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    data = []
            data.append({"name": character, "text": text})
            p.write_text(json.dumps(data[-20:], ensure_ascii=False, indent=2),
                         encoding="utf-8")
        except Exception:
            pass

    def notify_incoming_call(self, character: str, call_type: str = "voice"):
        if (character or "").strip() in _RESERVED_NAMES:
            return  # narration / dialog markers are never callers
        if self._state == _State.IN_CALL:
            return
        # DND: log as missed, don't ring
        from plugins.shinsekai_chat_phone.settings_app import is_dnd
        if is_dnd():
            label = "未接视频来电(DND)" if call_type == "video" else "未接来电(DND)"
            self._message_store.add_message(character, label, is_user=False, msg_type="call_missed")
            self._phone_app.log_call(character, 0, "missed_dnd")
            self._update_badge()
            return
        self._previous_state = self._state
        self._call_mode = call_type
        view = self._active_call_view()
        view.show_incoming(character)
        self._apply_state(_State.INCOMING_CALL)
        _sfx.play(_sfx.RINGTONE, loop=True, key="ring")
        self._ring_vibrate()
        # Auto-miss: stop ringing and log a missed call if left unanswered.
        self._incoming_seq = getattr(self, "_incoming_seq", 0) + 1
        _seq = self._incoming_seq
        QTimer.singleShot(RING_TIMEOUT_MS, lambda: self._incoming_timeout(_seq))

    def _on_incoming_call(self, character: str, call_type: str = "voice"):
        """Slot for proactive monitor's incoming_call signal."""
        self.notify_incoming_call(character, call_type)

    def _on_llm_incoming_call(self, character: str, call_type: str = "voice"):
        """Slot for LLM-driven CALL signal — runs on the GUI thread.

        Ensures the caller is a contact (they must have the player's number to
        call), then rings the phone. Invoked via ``_incoming_call_signal`` so it
        is safe to emit from the message hook regardless of its thread.
        """
        character = (character or "").strip()
        if not character:
            return
        if not self._contact_store.is_contact(character):
            self.add_contact(character)
        self.notify_incoming_call(character, call_type)

    # ==================================================================
    # LLM capture — primary: message_added hook (JSON); fallback: HTML
    # ==================================================================

    def _on_sms_sent(self, character: str):
        """Mark that we're waiting for an SMS reply from this character."""
        self._sms_pending.add(character)
        self._sms_target = character
        self._sms_stagger = 0  # reset stagger for new conversation
        self._save_messages()

    def route_llm_reply(self, char_name: str, speech: str, stagger_index: int = 0, known: bool = True):
        """Store SMS reply — works even during calls (thread-safe).

        ``known=False`` records the sender as an「未知联系人」(obtained the player's
        number without formally exchanging contacts).
        """
        char_name = (char_name or "").strip()
        speech = (speech or "").strip()
        if not char_name or not speech or char_name in _RESERVED_NAMES:
            return
        if not self._contact_store.is_contact(char_name):
            self._contact_store.add_contact(char_name, known=known)
        self._contact_store.touch_interaction(char_name)
        # Auto-increment stagger for tool-based calls (default stagger_index=0)
        if stagger_index == 0:
            with self._sms_lock:
                stagger_index = self._sms_stagger
                self._sms_stagger += 1
        # Simulate typing: first msg 1-3s, each subsequent +2-4s
        base_ms = random.randint(1000, 3000)
        stagger_ms = stagger_index * random.randint(2000, 4000)
        delay_sec = (base_ms + stagger_ms) / 1000.0
        # Use threading.Timer + Signal for cross-thread safety
        t = threading.Timer(delay_sec, lambda cn=char_name, sp=speech: (
            self._sms_deliver_signal.emit(cn, sp)))
        t.daemon = True
        t.start()

    def _deliver_sms(self, char_name: str, speech: str):
        self._messages_app.add_received_message(char_name, speech, delay=True)
        self._save_messages()
        if self._is_in_chat_with(char_name):
            self._message_store.mark_all_read(char_name)
        self._update_badge()
        self._refresh_all()

    # ── group chat (LLM-driven, thread-safe via signals) ──

    def route_group_reply(self, group: str, sender: str, text: str, stagger_index: int = 0):
        """Deliver one character's group message with a human-like staggered delay.

        Successive replies in one batch are delivered strictly in call order
        (accumulating delay), so characters answering each other stay coherent.
        The batch resets when the player sends (``_on_group_sent``) or after a
        >8s gap (fallback for story-driven messages with no player turn).
        """
        group = (group or "").strip()
        sender = (sender or "").strip()
        text = (text or "").strip()
        if not group or not sender or not text or sender in _RESERVED_NAMES:
            return
        if stagger_index == 0:
            with self._sms_lock:
                now = time.time()
                if now - self._group_delay_time > 8.0:
                    self._group_delay = 0.0
                if self._group_delay <= 0.0:
                    self._group_delay = random.uniform(0.6, 1.6)   # first reply of batch
                else:
                    self._group_delay += random.uniform(1.2, 2.6)  # strictly after previous
                delay_sec = self._group_delay
                self._group_delay_time = now
        else:
            delay_sec = (random.randint(600, 1800) + stagger_index * random.randint(1200, 2600)) / 1000.0
        t = threading.Timer(delay_sec, lambda g=group, s=sender, tx=text: (
            self._group_deliver_signal.emit(g, s, tx)))
        t.daemon = True
        t.start()

    def _deliver_group(self, group: str, sender: str, text: str):
        # Only current members can post to a group — a removed/never-added
        # character's message is dropped (membership is authoritative).
        if not self._group_store.has_group(group) or sender not in self._group_store.get_members(group):
            return
        self._group_app.add_received_message(group, sender, text)
        if self._is_viewing_group(group):
            self._group_store.mark_read(group)
        else:
            self._group_store.mark_unread(group)
            self._update_group_badge()
            from plugins.shinsekai_chat_phone.settings_app import is_dnd
            if not is_dnd():
                self._shake()

    def create_group_from_llm(self, name: str, members: list[str]) -> str:
        """Create a group at the story/LLM's request; returns the final group name."""
        name = (name or "").strip()
        if not name:
            return ""
        clean: list[str] = []
        for m in members:
            m = (m or "").strip()
            if not m:
                continue
            clean.append(m)
            if not self._contact_store.is_contact(m):
                self._contact_store.add_contact(m)
        gid = self._group_store.create_group(name, clean)
        if gid:
            self._group_refresh_signal.emit()
        return gid

    def _on_group_refresh(self):
        """GUI-thread slot: refresh contact lists + group list after an LLM-created group."""
        self.load_contacts()
        self._group_app.refresh_list()

    def _on_group_sent(self):
        """Player sent a group message — start a fresh reply batch (reset stagger)."""
        with self._sms_lock:
            self._group_delay = 0.0
            self._group_delay_time = 0.0

    # ── group membership / rename (player UI + LLM tools; thread-safe) ──

    def _notify_group_event(self, text: str):
        """Queue a neutral event notification to the LLM (drives next-turn reactions)."""
        if self._submit_cb is not None and text:
            self._submit_cb(text)  # type: ignore[operator]

    def group_add_member(self, group: str, member: str, actor: str = "") -> bool:
        group = (group or "").strip(); member = (member or "").strip(); actor = (actor or "").strip()
        if not group or not member or member in _RESERVED_NAMES or not self._group_store.has_group(group):
            return False
        if member in self._group_store.get_members(group):
            return False
        if not self._contact_store.is_contact(member):
            self._contact_store.add_contact(member)
        self._group_store.add_member(group, member)
        self._group_store.add_system_message(
            group, f"{actor}把「{member}」拉进了群聊" if actor else f"「{member}」加入了群聊")
        mstr = "、".join(self._group_store.get_members(group))
        self._notify_group_event(
            f"[群聊] {actor or '有人'}把「{member}」拉进了群「{group}」（当前成员：{mstr}）。"
            f"请根据角色性格与当前剧情，自主演绎相关角色的反应。")
        self._group_event_signal.emit("changed", group, "")
        return True

    def group_remove_member(self, group: str, member: str, actor: str = "") -> bool:
        group = (group or "").strip(); member = (member or "").strip(); actor = (actor or "").strip()
        if not group or not member or not self._group_store.has_group(group):
            return False
        if member not in self._group_store.get_members(group):
            return False
        self._group_store.remove_member(group, member)
        self._group_store.add_system_message(
            group, f"{actor}把「{member}」移出了群聊" if actor else f"「{member}」被移出了群聊")
        self._notify_group_event(
            f"[群聊] {actor or '有人'}把「{member}」移出了群「{group}」。"
            f"请自主演绎接下来会发生什么（是否反应、如何反应完全由你定）。")
        self._group_event_signal.emit("changed", group, "")
        return True

    def group_char_leave(self, group: str, member: str) -> bool:
        group = (group or "").strip(); member = (member or "").strip()
        if not group or not member or not self._group_store.has_group(group):
            return False
        if member not in self._group_store.get_members(group):
            return False
        self._group_store.remove_member(group, member)
        self._group_store.add_system_message(group, f"「{member}」退出了群聊")
        self._notify_group_event(
            f"[群聊] 「{member}」退出了群「{group}」。请自主演绎群里其他成员的反应。")
        self._group_event_signal.emit("changed", group, "")
        return True

    def group_rename(self, group: str, new_name: str, actor: str = "") -> str:
        group = (group or "").strip(); new_name = (new_name or "").strip(); actor = (actor or "").strip()
        if not group or not new_name or not self._group_store.has_group(group):
            return ""
        final = self._group_store.rename_group(group, new_name)
        if not final or final == group:
            return final
        self._group_store.add_system_message(
            final, f"{actor}把群名改为「{final}」" if actor else f"群名已改为「{final}」")
        self._notify_group_event(
            f"[群聊] {actor or '有人'}把群「{group}」改成了「{final}」。请自主演绎群里成员的反应。")
        self._group_event_signal.emit("rename", group, final)
        return final

    def group_player_leave(self, group: str) -> bool:
        group = (group or "").strip()
        if not group or not self._group_store.has_group(group):
            return False
        self._notify_group_event(
            f"[群聊] 你退出了群「{group}」。你已看不到群内消息，请自主演绎成员们后续的反应。")
        self._group_store.delete_group(group)
        self._group_event_signal.emit("gone", group, "")
        return True

    def group_dissolve(self, group: str) -> bool:
        group = (group or "").strip()
        if not group or not self._group_store.has_group(group):
            return False
        self._notify_group_event(
            f"[群聊] 你解散了群「{group}」。请自主演绎成员们的反应。")
        self._group_store.delete_group(group)
        self._group_event_signal.emit("gone", group, "")
        return True

    def _on_player_manage(self, action: str, group: str, arg: str):
        """Player-initiated group management from the manage view (actor = 你)."""
        if action == "add":
            self.group_add_member(group, arg, actor="你")
        elif action == "remove":
            self.group_remove_member(group, arg, actor="你")
        elif action == "rename":
            self.group_rename(group, arg, actor="你")
        elif action == "leave":
            self.group_player_leave(group)
        elif action == "dissolve":
            self.group_dissolve(group)

    def _on_group_event(self, action: str, group: str, arg: str):
        """GUI-thread slot: reflect a membership/rename/removal event in the group UI."""
        if action == "rename":
            self._group_app.on_group_renamed(group, arg)
        elif action == "gone":
            self._group_app.on_group_gone(group)
        else:  # "changed"
            self._group_app.on_group_changed(group)
        self._group_app.refresh_list()

    def handle_display_words_changed(self, html_text: str):
        """Fallback: capture SMS replies from HTML display updates."""
        if not html_text or not self._sms_pending:
            return
        parsed = _parse_dialog_html(html_text)
        if parsed:
            char_name, speech = parsed
            if char_name and speech and char_name in self._sms_pending:
                self.route_llm_reply(char_name, speech)

    def handle_message_submitted(self, text: str):
        """Check for parenthetical instructions like (让XX给我打电话)."""
        if not text:
            return
        import re as _re

        # Match: (让/叫 XX 给/打 电话/视频)
        m = _re.search(r'[(（]\s*[让叫]\s*(\S+?)\s*(?:给[我咱])?\s*(?:打|拨)\s*(?:个)?\s*(电话|视频|视频电话)?[)）]', text)
        if m:
            name = m.group(1).strip()
            call_type = "video" if (m.group(2) and "视频" in m.group(2)) else "voice"
            if name and self._contact_store.is_contact(name):
                self.notify_incoming_call(name, call_type)

    # ==================================================================
    # paint / mouse — drag support
    # ==================================================================

    def paintEvent(self, event):
        pass  # button handles its own rendering

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.globalPosition().toPoint()
            self._drag_press_time = time.time()
            self._dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_start is None or not self._dragging:
            # Check if we should start dragging (threshold distance)
            if self._drag_start is not None:
                delta = (event.globalPosition().toPoint() - self._drag_start).manhattanLength()
                if delta > 10:
                    self._dragging = True
            if not self._dragging:
                return
        diff = event.globalPosition().toPoint() - self._drag_start
        new_pos = self.pos() + diff
        p = self.parent()
        if p:
            new_pos.setX(max(0, min(p.width() - self.width(), new_pos.x())))
            new_pos.setY(max(0, min(p.height() - self.height(), new_pos.y())))
        self.move(new_pos)
        self._drag_start = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._dragging = False
        self._drag_start = None
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        if self._state == _State.COLLAPSED:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._state == _State.COLLAPSED:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().leaveEvent(event)

    # ==================================================================
    # position
    # ==================================================================

    def showEvent(self, event):
        super().showEvent(event)
        if self.parent() is not None:
            self.parent().installEventFilter(self)
        self._reposition()

    def eventFilter(self, watched: QWidget, event: QEvent) -> bool:
        if watched is self.parent() and event.type() == QEvent.Type.Resize:
            self._reposition()
        return False

    def _reposition(self):
        p = self.parent()
        if p is None:
            return
        pw, ph = p.width(), p.height()
        if pw <= 0 or ph <= 0:
            return
        if self._state == _State.COLLAPSED:
            if self.x() == 0 and self.y() == 0:
                x = pw - ICON_W - PHONE_MARGIN
                y = max(0, (ph - ICON_H) // 2) - 6
                self.setGeometry(x, y, ICON_W, ICON_H + 10)
            self._toggle_btn.move(0, 6)
            self._toggle_btn.show()
            self._badge.move(ICON_W - 16, 0)
            self._frame.hide()
            self._badge.raise_()
        else:
            if self.width() < PHONE_W:
                x = PHONE_MARGIN
                y = max(0, (ph - PHONE_H) // 2)
                self.setGeometry(x, y, PHONE_W, PHONE_H)
            self._frame.setGeometry(0, 0, PHONE_W, PHONE_H)
            self._frame.show()
            # Expanded: hide the floating 📱. Every app (and the placeholders) has
            # its own back button now, and the home-screen home bar collapses the
            # phone. The 📱 only shows while collapsed, as the launcher to open it.
            self._toggle_btn.hide()
            self._badge.hide()
            self.raise_()
            QTimer.singleShot(100, self._re_raise)

    def _keep_on_top(self):
        if self._state != _State.COLLAPSED and self.isVisible():
            self.raise_()

    def _re_raise(self):
        if self._state != _State.COLLAPSED:
            self.raise_()

    # ==================================================================
    # state
    # ==================================================================

    def _apply_state(self, st: _State):
        self._state = st
        # stop looping call cues when leaving their state
        if st != _State.INCOMING_CALL:
            _sfx.stop("ring")
        if st != _State.CALLING:
            _sfx.stop("dial")
        expanded = st != _State.COLLAPSED
        self._frame.setVisible(expanded)
        if st in (_State.CALLING, _State.INCOMING_CALL, _State.IN_CALL):
            self._frame.hide()
            view = self._active_call_view()
            view.setGeometry(0, 0, PHONE_W, PHONE_H)
            view.show()
            view.raise_()
            # Hide the other view
            if self._call_mode == "video":
                self._call_view.hide()
            else:
                self._video_call_view.hide()
        else:
            self._hide_call_views()
        if expanded:
            self._raise_timer.start()
        else:
            self._raise_timer.stop()
            self._raise_timer.setInterval(500)  # reset to default
        self._reposition()

    def _on_floating_icon_click(self):
        if self._state == _State.COLLAPSED:
            self.load_contacts()
            self._show_home()
            self._apply_state(_State.HOME)
        elif self._state in (_State.CALLING, _State.INCOMING_CALL, _State.IN_CALL):
            # Force shutdown: end call immediately
            self._hangup_attempts = 0
            self._call_hangup()
        else:
            # Collapse back — always works
            self._apply_state(_State.COLLAPSED)

    # ── home / apps ──

    def _show_home(self):
        self._current_app = ""
        for w in [self._home, self._messages_app, self._phone_app,
                   self._memos_app, self._browser_app, self._music_app,
                   self._settings_app, self._location_app, self._video_placeholder,
                   self._group_app, self._moments_placeholder]:
            w.hide()
        self._home.show()

    def _launch_app(self, app_id: str):
        self._current_app = app_id
        apps = {
            "messages": self._messages_app,
            "phone": self._phone_app,
            "memos": self._memos_app,
            "browser": self._browser_app,
            "music": self._music_app,
            "settings": self._settings_app,
            "location": self._location_app,
            "video": self._video_placeholder,
            "group": self._group_app,
            "moments": self._moments_placeholder,
        }
        # "video" app → placeholder for now; "phone" → reset to voice mode
        if app_id == "phone":
            self._call_mode_preset = "voice"
            self._phone_app.set_video_mode(False)
        elif app_id == "group":
            self._group_app.refresh_list()
        for w in apps.values():
            w.hide()
        self._home.hide()
        if app_id in apps:
            apps[app_id].show()
        self._apply_state(_State.APP)

    def _go_home(self):
        self.load_contacts()
        self._show_home()
        self._apply_state(_State.HOME)


    # ── calls ──

    def _start_call(self, character: str, mode: str = "voice"):
        if not character or not character.strip():
            return
        # Honour preset from home screen app (video icon sets _call_mode_preset)
        if mode == "voice":
            mode = getattr(self, '_call_mode_preset', 'voice')
        self._call_mode_preset = "voice"  # reset for next call
        self._previous_state = self._state
        self._call_char = character
        self._call_start = time.time()
        self._call_type = "outgoing"
        self._call_mode = mode
        self._sms_pending.clear()
        self._hangup_attempts = 0
        self._yandere_breakdown_locked = False
        self._call_dialogue.clear()
        view = self._active_call_view()
        view.show_calling(character)
        self._apply_state(_State.CALLING)
        _sfx.play(_sfx.DIAL)  # dialing cue (one-shot)
        _sfx.play(_sfx.BUSY, loop=True, key="dial")  # ring-back while awaiting answer
        if self._submit_cb is not None:
            if mode == "video":
                prompt = f"[视频通话] 玩家主动拨打了{character}的视频电话。{character}是接听方。请只输出{character}的对话。"
            else:
                prompt = f"[通话] 玩家主动拨打了{character}的电话。{character}是接听方。请只输出{character}的对话。"
            self._submit_cb(prompt)  # type: ignore[operator]
        # Random ring time 4-10s before character picks up
        ring_ms = random.randint(4000, 10000)
        QTimer.singleShot(ring_ms, self._auto_connect)

    def _auto_connect(self):
        """Auto-connect outgoing call after brief delay."""
        if self._state != _State.CALLING:
            return
        view = self._active_call_view()
        char = view.character() or getattr(self, '_call_char', '')
        view.show_in_call(char)
        self._apply_state(_State.IN_CALL)
        if char:
            self._contact_store.touch_interaction(char)

    def _call_accept(self):
        # Only read from the active call view — not the stale other one
        view = self._active_call_view()
        char = view.character()
        self._call_char = char
        self._call_start = time.time()
        self._call_type = "incoming"
        self._hangup_attempts = 0
        self._yandere_breakdown_locked = False
        self._call_dialogue.clear()
        view = self._active_call_view()
        view.show_in_call(char)
        self._apply_state(_State.IN_CALL)
        self._contact_store.touch_interaction(char)
        if self._submit_cb is not None:
            _kind = "视频通话" if self._call_mode == "video" else "通话"
            self._submit_cb(
                f"[{_kind}] {char}主动打给玩家，玩家接听了。这通电话是{char}自己发起的——"
                f"请{char}结合当前剧情、近况和你们之间的关系，主动开口，带着自己的目的或心情"
                f"引出话题、推进剧情（是{char}此刻有话想对玩家说、主动联系，"
                f"不是玩家找{char}、也不是玩家让他打的），"
                f"不要反问玩家「有什么事」「找我干嘛」。请只输出{char}的对话。")

    def _call_decline(self):
        view = self._active_call_view()
        char = view.character()
        if self._state == _State.INCOMING_CALL:
            self._message_store.add_message(
                char, "未接来电", is_user=False, msg_type="call_missed")
            # also record it in the phone's call log (recents) — rendered red as 未接来电
            if char:
                self._phone_app.log_call(
                    char, 0, "missed_video" if self._call_mode == "video" else "missed")
            self._update_badge()
            self._refresh_all()
        self._restore_after_call()

    def _restore_after_call(self):
        """Go back to the state before the call, but never collapse."""
        self._clear_yandere_overlays()
        if self._previous_state == _State.COLLAPSED:
            self._show_home()
            self._apply_state(_State.HOME)
        else:
            self._apply_state(self._previous_state)

    def _active_call_view(self):
        """Return the CallView or VideoCallView based on current mode."""
        return self._video_call_view if self._call_mode == "video" else self._call_view

    def _hide_call_views(self):
        """Hide both call views — called when exiting call state."""
        self._call_view.hide()
        self._video_call_view.hide()

    def push_call_dialogue(self, character: str, speech: str) -> None:
        """Feed LLM dialogue into the buffer during an active call."""
        if self._state in (_State.CALLING, _State.INCOMING_CALL, _State.IN_CALL):
            self._call_dialogue.append(speech)
            if len(self._call_dialogue) > 10:
                self._call_dialogue = self._call_dialogue[-10:]

    def push_call_sprite(self, character: str, sprite_index: str) -> None:
        """Update the sprite in the video call view during an active video call."""
        if self._state in (_State.CALLING, _State.INCOMING_CALL, _State.IN_CALL) and self._call_mode == "video":
            self._video_call_view.update_sprite(sprite_index)

    def _reset_hangup_btn(self):
        self._call_view._hangup_btn.setStyleSheet("QPushButton { background: #FF3B30; color: white; border-radius: 32px; font-size: 30px; border: none; }")

    def _call_hangup(self):
        view = self._active_call_view()
        char = view.character() or self._call_char
        from plugins.shinsekai_chat_phone.settings_app import is_character_yandere, is_yandere_tampering_active, record_yandere_tampering

        # ── Detect phone tampering in dialogue and persist it ──
        if char and is_character_yandere(char) and self._call_dialogue:
            recent = " ".join(self._call_dialogue[-8:])
            tamper_kw = [
                "动了手脚", "安装了", "植入", "木马", "病毒", "后门",
                "破解了", "黑入了", "监控", "窃听", "远程控制",
                "挂不断", "挂不了", "不能挂断", "强制通话",
                "修改了你的手机", "控制了你的手机", "入侵了你的手机",
                "在你手机里", "你的手机被", "你的手机已经",
                "你逃不掉的", "你的一切我都", "你跑不掉的",
            ]
            if any(k in recent for k in tamper_kw):
                record_yandere_tampering(char)

        # ── Hangup block: once triggered, pure counting ──
        if char and is_yandere_tampering_active(char):
            recent = " ".join(self._call_dialogue[-6:]) if self._call_dialogue else ""
            breakdown_kw = [
                "哭", "崩溃", "失控", "不要走", "别走", "你不能",
                "绝不", "死给你看", "杀了你", "你不准", "不准挂",
                "疯狂", "歇斯底里", "情绪激动", "求你了", "别离开",
                "敢挂", "你敢", "永远陪我", "不会放过你", "挂不断",
                "逃不掉", "跑不掉", "只有我", "只看着我", "只看着我一个人",
                "不要再对别人", "不要再", "不许", "不准", "不可以",
                "你是我的", "永远是我的", "哪里都别想", "哪里也不许",
                "别想逃", "不会让你", "放不开", "我只有你了",
            ]
            # Trigger on breakdown keywords, or keep counting if already started
            triggered = any(k in recent for k in breakdown_kw) or self._hangup_attempts > 0
            if triggered:
                self._hangup_attempts += 1
                attempt = self._hangup_attempts
                # Update status
                self._call_view._status.setText(f"【挂断尝试 {attempt} 次】")
                self._call_view._status.setStyleSheet(
                    f"color: #FF3B30; font-size: 14px; font-weight: 700;")
                # ── Attempts 3-6: drifting floating labels ──
                if 3 <= attempt <= 6:
                    self._clear_yandere_overlays()
                    import random as _rand
                    font_size = 18 + (attempt - 3) * 8
                    count = attempt - 1  # 2, 3, 4, 5 labels
                    texts = [
                        "不准挂!", "你敢挂?", "永远陪我", "别想逃!",
                        "杀了你...", "不要走...", "你是我的!", "我不会放手!",
                    ]
                    for i in range(count):
                        txt = texts[i % len(texts)]
                        lbl = QLabel(txt, self)
                        lbl.setStyleSheet(
                            f"color: rgba(255,59,48,220); font-size: {font_size}px;"
                            f" font-weight: 900; background: transparent;")
                        lbl.adjustSize()
                        # Random starting position across the whole phone frame
                        ox = _rand.randint(8, PHONE_W - lbl.width() - 8)
                        oy = _rand.randint(60, PHONE_H - lbl.height() - 80)
                        lbl.move(ox, oy)
                        lbl.show(); lbl.raise_()
                        if not hasattr(self, '_yandere_overlays'):
                            self._yandere_overlays: list[QLabel] = []
                        self._yandere_overlays.append(lbl)
                    # Start drift timer
                    self._start_yandere_drift()
                # ── Attempt 7: special center-screen message ──
                elif attempt == 7:
                    self._clear_yandere_overlays()
                    center_lbl = QLabel("！！永远陪着我！！", self)
                    center_lbl.setStyleSheet(
                        "color: #FF3B30; font-size: 36px; font-weight: 900;"
                        " background: rgba(0,0,0,180); border-radius: 16px;"
                        " padding: 14px 20px;")
                    center_lbl.adjustSize()
                    center_lbl.move(
                        (PHONE_W - center_lbl.width()) // 2,
                        (PHONE_H - center_lbl.height()) // 2)
                    center_lbl.show(); center_lbl.raise_()
                    if not hasattr(self, '_yandere_overlays'):
                        self._yandere_overlays: list[QLabel] = []
                    self._yandere_overlays.append(center_lbl)
                # ── Attempt 8+: allow hangup ──
                if attempt >= 8:
                    self._hangup_attempts = 0
                    self._yandere_breakdown_locked = False
                    self._clear_yandere_overlays()
                    # fall through to normal hangup
                else:
                    self._call_view._hangup_btn.setStyleSheet(
                        "QPushButton { background: #FF3B30; color: white;"
                        " border-radius: 32px; font-size: 30px; border: none; }"
                        " QPushButton:pressed { background: #AA0000; }")
                    QTimer.singleShot(3000, self._reset_hangup_btn)
                    if self._submit_cb:
                        self._submit_cb(
                            f"[通话] 只输出{char}。{char}情绪完全失控，利用手机后门程序"
                            f"阻止你挂断电话（第{attempt}次）。"
                            f"用哭腔、尖叫、威胁、哀求的语气，"
                            f"必须包含：不准挂、你是我的、别想逃 等表达。")
                    return
        self._hangup_attempts = 0
        duration = int(time.time() - self._call_start) if self._call_start else 0
        call_type = getattr(self, '_call_type', 'outgoing')
        if self._call_mode == "video":
            call_type = call_type + "_video"
        if char:
            self._phone_app.log_call(char, max(duration, 1), call_type)
        # Force-stop TTS (like skip button)
        try:
            from ui.chat_ui.signal_bridge import get_chat_ui_signal_bridge
            get_chat_ui_signal_bridge().skip_speech_signal.emit()
        except Exception:
            pass
        # Reaction: narration + character response
        if char and self._submit_cb:
            self._submit_cb(f"[通话结束] 用户挂断了电话。请先以旁白身份写一句用户挂断电话的描述，再输出{char}的反应。")
        self._call_start = 0
        self._call_char = ''
        self._call_mode = "voice"
        self._yandere_breakdown_locked = False
        _sfx.play(_sfx.HANGUP)
        self._restore_after_call()

    def end_call_from_character(self, char_name: str) -> None:
        """Character hung up on the user — end call from their side."""
        if self._state not in (_State.CALLING, _State.INCOMING_CALL, _State.IN_CALL):
            return
        _sfx.play(_sfx.HANGUP)
        duration = int(time.time() - self._call_start) if self._call_start else 0
        call_type = getattr(self, '_call_type', 'incoming')
        if self._call_mode == "video":
            call_type = "incoming_video"
        self._phone_app.log_call(char_name, max(duration, 1), call_type)
        # Stop TTS and timer
        try:
            from ui.chat_ui.signal_bridge import get_chat_ui_signal_bridge
            get_chat_ui_signal_bridge().skip_speech_signal.emit()
        except Exception:
            pass
        self._call_start = 0
        self._call_char = ''
        self._call_mode = "voice"
        self._clear_yandere_overlays()
        # Go straight back to home
        self._apply_state(_State.HOME)
        self._show_home()

    def _on_proactive_message(self, character, text):
        self.notify_new_message(character, text)

    # ── helpers ──

    def _update_badge(self):
        total = self._message_store.total_unread() + self._group_store.total_unread()
        # Skip if unchanged — prevents redundant layout/repaint
        if total == self._last_badge_count:
            return
        self._last_badge_count = total
        if total > 0:
            t = str(total) if total <= 99 else "99+"
            self._badge.setText(t)
            self._badge.adjustSize()
            self._badge.show()
            self._badge.raise_()
        else:
            self._badge.hide()
        # Also update home screen Messages app icon badge
        if hasattr(self, '_home') and self._home is not None:
            self._home.set_messages_badge(total)

    def _refresh_all(self):
        # Debounce: coalesce rapid calls into one deferred refresh
        if self._refresh_queued:
            return
        self._refresh_queued = True
        QTimer.singleShot(150, self._do_refresh)

    def _do_refresh(self):
        self._refresh_queued = False
        names = self._contact_store.get_contacts()
        known = [n for n in names if self._contact_store.is_known(n)]
        unknown = {n for n in names if not self._contact_store.is_known(n)}
        unread = self._message_store.unread_per_character()
        previews = {n: self._message_store.last_message_preview(n) for n in names}
        self._messages_app.refresh(names, unread, previews, unknown)
        self._phone_app.refresh_contacts(known)

    def _ring_vibrate(self):
        """Buzzy incoming-call vibration — rapid pulses (brrt … brrt) while ringing,
        matching the ringtone. Louder/faster than the gentle new-SMS shake."""
        if self._state != _State.INCOMING_CALL:
            return
        orig = self.pos()
        g = QSequentialAnimationGroup(self)
        amp = 7
        prev = orig
        for dx in (-amp, amp, -amp, amp, -amp, amp, -3, 0):  # fast buzz, settle to rest
            target = orig + QPoint(dx, 0)
            g.addAnimation(_a(self, prev, target, 38, QEasingCurve.Type.Linear))
            prev = target
        g.finished.connect(g.deleteLater)
        g.start()
        QTimer.singleShot(1050, self._ring_vibrate)  # buzz ~0.3s, pause ~0.75s, repeat

    def _incoming_timeout(self, seq: int):
        """Ringing went unanswered long enough — treat it as a missed call."""
        if self._state == _State.INCOMING_CALL and getattr(self, "_incoming_seq", 0) == seq:
            self._call_decline()  # logs 未接来电 (message + red call-log entry) + restores

    def _shake(self):
        orig = self.pos()
        g = QSequentialAnimationGroup(self)
        g.addAnimation(_a(self, orig, orig + QPoint(-5, 0), 70, QEasingCurve.Type.OutSine))
        g.addAnimation(_a(self, orig + QPoint(-5, 0), orig + QPoint(5, 0), 70, QEasingCurve.Type.InOutSine))
        g.addAnimation(_a(self, orig + QPoint(5, 0), orig + QPoint(-4, 0), 70, QEasingCurve.Type.InOutSine))
        g.addAnimation(_a(self, orig + QPoint(-4, 0), orig, 70, QEasingCurve.Type.InSine))
        g.start()

    def _start_yandere_drift(self):
        """Start a timer that randomly drifts the overlay labels."""
        if hasattr(self, '_drift_timer') and self._drift_timer is not None:
            self._drift_timer.stop()
        self._drift_timer = QTimer(self)
        self._drift_timer.timeout.connect(self._drift_tick)
        self._drift_timer.start(600)  # drift every 600ms

    def _drift_tick(self):
        import random as _rand
        for lbl in getattr(self, '_yandere_overlays', []):
            try:
                if lbl.isVisible():
                    x = lbl.x() + _rand.randint(-25, 25)
                    y = lbl.y() + _rand.randint(-15, 15)
                    x = max(4, min(PHONE_W - lbl.width() - 4, x))
                    y = max(4, min(PHONE_H - lbl.height() - 4, y))
                    lbl.move(x, y)
            except Exception:
                pass

    def _clear_yandere_overlays(self):
        """Remove all floating yandere block labels and stop drift."""
        if hasattr(self, '_drift_timer') and self._drift_timer is not None:
            self._drift_timer.stop()
            self._drift_timer = None
        for lbl in getattr(self, '_yandere_overlays', []):
            try:
                lbl.hide()
                lbl.deleteLater()
            except Exception:
                pass
        self._yandere_overlays = []


def _placeholder_app(text: str, on_back, parent) -> QWidget:
    """A '...功能开发中' screen with a back button, so it isn't a navigation dead end."""
    from PySide6.QtWidgets import QPushButton, QHBoxLayout
    w = QWidget(parent)
    lay = QVBoxLayout(w); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
    tb = QWidget(); tb.setFixedHeight(48)
    tl = QHBoxLayout(tb); tl.setContentsMargins(4, 0, 12, 0)
    back = QPushButton("←")
    back.setStyleSheet("QPushButton { background: transparent; color: #FFB3BA; border: none;"
                       " font-size: 18px; padding: 6px 10px; font-weight: 600; }")
    back.clicked.connect(on_back)
    tl.addWidget(back); tl.addStretch()
    lay.addWidget(tb)
    lbl = QLabel(text); lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setStyleSheet("color: #8A7A7A; font-size: 14px;")
    lay.addWidget(lbl, 1)
    return w


def _a(w, s, e, ms, curve):
    a = QPropertyAnimation(w, b"pos")
    a.setDuration(ms); a.setStartValue(s); a.setEndValue(e)
    a.setEasingCurve(curve)
    return a

def _parse_dialog_html(html: str) -> tuple[str, str] | None:
    m = re.search(r"<b[^>]*>\s*(.*?)\s*</b>\s*[：:]\s*(.*?)</p>", html, re.DOTALL)
    if m:
        name = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        speech = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if name and speech:
            return name, speech
    return None
