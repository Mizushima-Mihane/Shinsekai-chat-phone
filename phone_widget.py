"""Main phone widget — Material 3 macaron, draggable, proper interactions."""

from __future__ import annotations

import enum
import json
import logging
import re
import time
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve, QEvent, QPoint, QPropertyAnimation,
    QSequentialAnimationGroup, Qt, QTimer, Signal,
)
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from plugins.chat_phone.browser_app import BrowserApp
from plugins.chat_phone.call_view import CallView
from plugins.chat_phone.contact_store import ContactStore
from plugins.chat_phone.home_screen import HomeScreen
from plugins.chat_phone.messages_app import MessagesApp
from plugins.chat_phone.message_store import MessageStore
from plugins.chat_phone.phone_app import PhoneApp
from plugins.chat_phone.styles import PHONE_QSS
from plugins.chat_phone.voice_memo_app import VoiceMemosApp

_logger = logging.getLogger("chat_phone.widget")

ICON_W, ICON_H = 44, 44
PHONE_W, PHONE_H = 280, 500
PHONE_MARGIN = 10


def _data_dir() -> Path:
    """Phone data follows chat history — find the latest active session."""
    base = Path("data/plugins/com.shinsekai.chat_phone")
    # Try to find the current chat history hash
    ch_dir = Path("data/chat_history")
    if ch_dir.is_dir():
        dirs = sorted(ch_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        for d in dirs:
            if d.is_dir() and (d / "active.json").exists():
                session = d.name
                return base / session
    # Fallback
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

    def __init__(self, submit_cb: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._submit_cb = submit_cb
        self._state = _State.COLLAPSED
        self._previous_state = _State.COLLAPSED
        self._current_app = ""
        self._call_char = ""
        self._call_start: float = 0
        self._call_type = ""
        self._hangup_attempts: int = 0
        # SMS tracking: only route replies that follow an SMS send
        self._sms_pending: set[str] = set()  # characters awaiting SMS reply

        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        # ── drag state ──
        self._dragging = False
        self._drag_start: QPoint | None = None
        self._drag_press_time: float = 0

        # ── keep-on-top ──
        self._raise_timer = QTimer(self)
        self._raise_timer.timeout.connect(self._keep_on_top)
        self._raise_timer.setInterval(100)

        # ── data ──
        self._data_dir = _data_dir()
        import plugins.chat_phone.phone_app as _pa
        _pa.set_call_log_dir(self._data_dir)
        self._contact_store = ContactStore(self._data_dir / "contacts.json")
        self._message_store = MessageStore()

        self.setStyleSheet(PHONE_QSS)

        # ── floating toggle button (always visible) ──
        from PySide6.QtWidgets import QPushButton
        self._toggle_btn = QPushButton("\U0001F4F1", self)  # 📱
        self._toggle_btn.setFixedSize(ICON_W, ICON_H)
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; font-size: 28px; }"
            "QPushButton:hover { font-size: 32px; }"
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
        self._frame.setStyleSheet(
            "#PhoneFrame {"
            "  background-color: #FFFAFA;"
            "  border: 2px solid #E8DCDC;"
            "  border-radius: 28px;"
            "}"
        )
        self._frame.hide()
        # Clip frame to rounded corners via bitmap mask
        from PySide6.QtGui import QBitmap, QPainter, QBrush, QColor
        from PySide6.QtCore import Qt as QtCore
        mask_bm = QBitmap(PHONE_W, PHONE_H)
        mask_bm.fill(QtCore.GlobalColor.color0)
        mp = QPainter(mask_bm)
        mp.setBrush(QBrush(QtCore.GlobalColor.color1))
        mp.setPen(QtCore.PenStyle.NoPen)
        mp.setRenderHint(QPainter.RenderHint.Antialiasing)
        from PySide6.QtCore import QRectF
        mp.drawRoundedRect(QRectF(0, 0, PHONE_W, PHONE_H), 28, 28)
        mp.end()
        self._frame.setMask(mask_bm)

        frame_layout = QVBoxLayout(self._frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)

        # ── home + apps ──
        self._home = HomeScreen(self._frame)
        self._home.app_launched.connect(self._launch_app)

        self._messages_app = MessagesApp(self._message_store, self._frame)
        self._messages_app.set_submit_callback(self._submit_cb)
        self._messages_app.set_sms_sent_callback(self._on_sms_sent)
        self._messages_app.set_save_callback(self._save_messages)
        self._messages_app.on_back.connect(self._go_home)
        self._messages_app.on_call.connect(self._start_call)

        self._phone_app = PhoneApp([], self._frame)
        self._phone_app.on_back.connect(self._go_home)
        self._phone_app.on_call.connect(self._start_call)


        self._memos_app = VoiceMemosApp(self._data_dir, self._frame)
        self._memos_app.on_back.connect(self._go_home)


        self._browser_app = BrowserApp(self._frame)
        self._browser_app.set_submit_callback(self._submit_cb)
        self._browser_app.on_back.connect(self._go_home)

        self._call_view = CallView(self._frame)
        self._call_view.on_accept.connect(self._call_accept)
        self._call_view.on_decline.connect(self._call_decline)
        self._call_view.on_hangup.connect(self._call_hangup)

        # stack
        for w in [self._home, self._messages_app, self._phone_app,
                   self._memos_app, self._browser_app, self._call_view]:
            frame_layout.addWidget(w)

        self.new_proactive_message.connect(self._on_proactive_message)

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
        unread = self._message_store.unread_per_character()
        previews = {n: self._message_store.last_message_preview(n) for n in names}
        self._messages_app.refresh(names, unread, previews)
        self._phone_app.refresh_contacts(names)

    def add_contact(self, name: str) -> bool:
        added = self._contact_store.add_contact(name)
        if added:
            self.load_contacts()
        return added

    def notify_new_message(self, character: str, text: str):
        self._message_store.add_message(character, text, is_user=False)
        self._messages_app.add_received_message(character, text)
        self._save_messages()
        self._update_badge()
        self._refresh_all()
        self._shake()

    def notify_incoming_call(self, character: str):
        # (self._data_dir / "debug_call_flow.txt").write_text(f"INCOMING: {character}", encoding="utf-8")
        if self._state == _State.IN_CALL:
            return
        self._previous_state = self._state
        self._call_view.show_incoming(character)
        self._apply_state(_State.INCOMING_CALL)
        self._shake()  # shake to notify

    # ==================================================================
    # LLM capture — primary: message_added hook (JSON); fallback: HTML
    # ==================================================================

    def _on_sms_sent(self, character: str):
        """Mark that we're waiting for an SMS reply from this character."""
        self._sms_pending.add(character)
        self._sms_target = character
        self._save_messages()

    def route_llm_reply(self, char_name: str, speech: str):
        """SMS reply from PHONE-tagged LLM output — always stored."""
        char_name = (char_name or "").strip()
        speech = (speech or "").strip()
        if not char_name or not speech:
            return
        if not self._contact_store.is_contact(char_name):
            self._contact_store.add_contact(char_name)
        self._contact_store.touch_interaction(char_name)
        (self._data_dir / "debug_route_in.txt").write_text(f"ROUTE: {char_name}={speech[:50]}", encoding="utf-8")
        self._messages_app.add_received_message(char_name, speech, delay=True)
        self._save_messages()
        self._update_badge()
        self._refresh_all()

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
        if not text:
            return

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
            # Toggle button floats at top-right of frame
            self._toggle_btn.move(PHONE_W - ICON_W - 8, 8)
            self._toggle_btn.raise_()
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
        expanded = st != _State.COLLAPSED
        self._frame.setVisible(expanded)
        self._call_view.setVisible(
            st in (_State.CALLING, _State.INCOMING_CALL, _State.IN_CALL))
        if expanded:
            self._raise_timer.start()
        else:
            self._raise_timer.stop()
        if expanded:
            self._reposition()

    def _on_floating_icon_click(self):
        if self._state == _State.COLLAPSED:
            self.load_contacts()
            self._show_home()
            self._apply_state(_State.HOME)
        else:
            # Collapse back — always works
            self._apply_state(_State.COLLAPSED)

    # ── home / apps ──

    def _show_home(self):
        self._current_app = ""
        for w in [self._home, self._messages_app, self._phone_app,
                   self._memos_app, self._browser_app]:
            w.hide()
        self._home.show()

    def _launch_app(self, app_id: str):
        self._current_app = app_id
        apps = {
            "messages": self._messages_app,
            "phone": self._phone_app,
            "memos": self._memos_app,
            "browser": self._browser_app,
        }
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

    def _start_call(self, character: str):
        if not character or not character.strip():
            return
        self._previous_state = self._state
        self._call_char = character
        self._call_start = time.time()
        self._call_type = "outgoing"
        self._sms_pending.clear()
        self._hangup_attempts = 0
        self._call_view.show_calling(character)
        self._apply_state(_State.CALLING)
        if self._submit_cb is not None:
            prompt = f"[通话] 玩家正在和{character}通电话。只有{character}能听到。请只输出{character}的对话。"
            self._submit_cb(prompt)  # type: ignore[operator]
        QTimer.singleShot(2000, self._auto_connect)

    def _auto_connect(self):
        """Auto-connect outgoing call after brief delay."""
        # (self._data_dir / "debug_call_flow.txt").write_text("AUTO_CONNECT", encoding="utf-8")
        if self._state != _State.CALLING:
            # (self._data_dir / "debug_call_flow.txt").write_text(f"AUTO_SKIP state={self._state}", encoding="utf-8")
            return
        char = self._call_view.character() or getattr(self, '_call_char', '')
        self._call_view.show_in_call(char)
        self._apply_state(_State.IN_CALL)
        if char:
            self._contact_store.touch_interaction(char)

    def _call_accept(self):
        # (self._data_dir / "debug_call_flow.txt").write_text("ACCEPT", encoding="utf-8")
        char = self._call_view.character()
        self._call_char = char
        self._call_start = time.time()
        self._call_type = "incoming"
        self._hangup_attempts = 0
        self._call_view.show_in_call(char)
        self._apply_state(_State.IN_CALL)
        self._contact_store.touch_interaction(char)
        if self._submit_cb is not None:
            self._submit_cb(f"[通话] 玩家正在和{char}通电话。只有{char}能听到。请只输出{char}的对话。")

    def _call_decline(self):
        # (self._data_dir / "debug_call_flow.txt").write_text("DECLINE", encoding="utf-8")
        char = self._call_view.character()
        if self._state == _State.INCOMING_CALL:
            self._message_store.add_message(
                char, "未接来电", is_user=False, msg_type="call_missed")
            self._update_badge()
            self._refresh_all()
        self._apply_state(self._previous_state)

    def _call_hangup(self):
        (self._data_dir / "debug_h.txt").write_text(f"HANGUP view={self._call_view.character()!r} stored={self._call_char!r}", encoding="utf-8")
        char = self._call_view.character() or self._call_char
        # Check if character is controlling/yandere type
        try:
            from config.config_manager import ConfigManager
            cm = ConfigManager()
            for ch in cm.config.characters:
                if ch.name == char:
                    setting = (ch.character_setting or "").lower()
                    keywords = ["病娇", "控制", "占有", "独占", "支配", "yandere", "束缚", "监禁"]
                    if any(kw in setting for kw in keywords):
                        self._hangup_attempts += 1
                        self._call_view.add_subtitle(char, f"第{self._hangup_attempts}次尝试挂断...")
                        if self._submit_cb:
                            self._submit_cb(f"（{char}发现你想挂电话。请以{char}的身份回应，可以阻止、嘲讽、或者终于放你走）")
                        return
            self._hangup_attempts = 0
        except Exception:
            pass
        duration = int(time.time() - self._call_start) if self._call_start else 0
        call_type = getattr(self, '_call_type', 'outgoing')
        (self._data_dir / "debug_hangup.txt").write_text(
            f"LOG: char={char} dur={max(duration,1)} type={call_type}", encoding="utf-8")
        # Send hangup reaction prompt
        if call_type == "incoming" and self._submit_cb and char:
            self._submit_cb(f"[通话结束] 只输出{char}。{char}被挂断电话后的反应。")
        elif self._submit_cb and char:
            self._submit_cb(f"[通话结束] 只输出{char}。{char}被挂断电话后的反应。")
        if char:
            self._phone_app.log_call(char, max(duration, 1), call_type)
        self._call_start = 0
        self._call_char = ''
        self._apply_state(self._previous_state)

    def _on_proactive_message(self, character, text):
        self.notify_new_message(character, text)

    # ── helpers ──

    def _update_badge(self):
        total = self._message_store.total_unread()
        if total > 0:
            t = str(total) if total <= 99 else "99+"
            self._badge.setText(t)
            self._badge.adjustSize()
            self._badge.show()
            self._badge.raise_()
        else:
            self._badge.hide()

    def _refresh_all(self):
        names = self._contact_store.get_contacts()
        unread = self._message_store.unread_per_character()
        previews = {n: self._message_store.last_message_preview(n) for n in names}
        self._messages_app.refresh(names, unread, previews)
        self._phone_app.refresh_contacts(names)

    def _shake(self):
        orig = self.pos()
        g = QSequentialAnimationGroup(self)
        g.addAnimation(_a(self, orig, orig + QPoint(-5, 0), 70, QEasingCurve.Type.OutSine))
        g.addAnimation(_a(self, orig + QPoint(-5, 0), orig + QPoint(5, 0), 70, QEasingCurve.Type.InOutSine))
        g.addAnimation(_a(self, orig + QPoint(5, 0), orig + QPoint(-4, 0), 70, QEasingCurve.Type.InOutSine))
        g.addAnimation(_a(self, orig + QPoint(-4, 0), orig, 70, QEasingCurve.Type.InSine))
        g.start()


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
