"""Messages app — Line-style chat bubbles, left/right aligned."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from plugins.shinsekai_chat_phone.message_store import MessageStore
from plugins.shinsekai_chat_phone.styles import (
    AVATAR_COLORS, ON_SURFACE, ON_SURFACE_VARIANT, OUTLINE_VARIANT, get_surface,
)


class MessagesApp(QWidget):
    on_back = Signal()
    on_call = Signal(str)
    _signal_received = Signal(str, str)

    def __init__(self, store: MessageStore, parent=None):
        super().__init__(parent)
        self._store = store
        self._character = ""
        self._submit_cb: object = None
        self._sms_sent_cb: object = None
        self._save_cb: object = None
        self._read_cb: object = None
        self._contacts: list[str] = []
        self._unread: dict[str, int] = {}
        self._previews: dict[str, str] = {}
        self._view = "list"
        self._msg_layout: QVBoxLayout | None = None
        self._scroll: QScrollArea | None = None
        self._own_messages: dict[str, list[dict]] = {}
        self._msg_idx: int = 0
        self._signal_received.connect(self._on_received_signal)
        self._setup_ui()
        self._show_list()

    def set_submit_callback(self, cb): self._submit_cb = cb
    def set_sms_sent_callback(self, cb): self._sms_sent_cb = cb
    def set_save_callback(self, cb): self._save_cb = cb
    def set_read_callback(self, cb): self._read_cb = cb

    def _on_call_btn(self):
        btn = self.sender()
        if btn:
            name = btn.property("char_name")
            if name and isinstance(name, str) and name.strip():
                try:
                    from plugins.shinsekai_chat_phone.plugin import get_phone_widget
                    w = get_phone_widget()
                    if w:
                        w._start_call(name, mode="voice")
                except Exception:
                    pass

    def refresh(self, contacts, unread, previews):
        self._contacts, self._unread, self._previews = list(contacts), dict(unread), dict(previews)
        if self._view == "list":
            self._show_list()

    def active_character(self) -> str: return self._character

    def add_received_message(self, name: str, text: str, delay: bool = False):
        self._signal_received.emit(name, text)

    def _on_received_signal(self, name: str, text: str):
        self._msg_idx += 1
        entry = {"text": text, "is_user": False, "idx": self._msg_idx}
        self._own_messages.setdefault(name, []).append(entry)
        self._store.add_message(name, text, is_user=False)
        preview = text[:30] + ("..." if len(text) > 30 else "")
        self._previews[name] = preview
        if self._save_cb is not None:
            self._save_cb()
        # Only show bubble if we're currently viewing this character's chat
        if self._msg_layout is not None and name == self._character:
            self._add_bubble(text, False)
            self._scroll_down()

    # ── UI setup ──
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)
        self._top_bar = _top_bar()
        self._top_bar["back"].clicked.connect(self._on_back)
        layout.addWidget(self._top_bar["widget"])
        self._stack = QVBoxLayout()
        self._stack.setContentsMargins(0, 0, 0, 0); self._stack.setSpacing(0)
        layout.addLayout(self._stack, 1)

    # ── Conversation list ──
    def _show_list(self):
        self._view = "list"
        self._top_bar["title"].setText("短信")
        self._top_bar["back"].hide(); self._top_bar["action"].setText("")
        self._clear()
        if not self._contacts:
            hint = QLabel("还没有短信\n在聊天中交换联系方式吧~")
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hint.setStyleSheet(f"color: {ON_SURFACE_VARIANT}; font-size: 13px;")
            self._stack.addWidget(hint, 1)
            return
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        c = QWidget(); c.setStyleSheet(f"background: {get_surface()};")
        cl = QVBoxLayout(c); cl.setContentsMargins(0, 0, 0, 0); cl.setSpacing(0)
        for name in self._contacts:
            row = QWidget(); row.setFixedHeight(64)
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row.mousePressEvent = self._make_tap(name)
            rl = QHBoxLayout(row); rl.setContentsMargins(16, 10, 16, 10); rl.setSpacing(12)
            rl.addWidget(self._avatar(name, 44))
            tv = QVBoxLayout(); tv.setSpacing(2)
            nlb = QLabel(name); nlb.setStyleSheet(f"color: {ON_SURFACE}; font-size: 14px; font-weight: 500;")
            plb = QLabel(self._previews.get(name, ""))
            plb.setStyleSheet(f"color: {ON_SURFACE_VARIANT}; font-size: 12px;"); plb.setMaximumWidth(150)
            tv.addWidget(nlb); tv.addWidget(plb); rl.addLayout(tv, 1)
            if self._unread.get(name, 0) > 0:
                badge = QLabel(str(self._unread[name])); badge.setFixedSize(20, 20)
                badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                badge.setStyleSheet("background: #FFB3BA; color: white; border-radius: 10px; font-size: 10px; font-weight: bold;")
                rl.addWidget(badge)
            cl.addWidget(row)
        cl.addStretch(); scroll.setWidget(c); self._stack.addWidget(scroll, 1)

    def _make_tap(self, name: str):
        def handler(event):
            self._store.mark_all_read(name)
            if self._read_cb is not None:
                self._read_cb()
            self._show_chat(name)
        return handler

    # ── Chat view ──
    def _show_chat(self, name: str):
        self._view = "chat"; self._character = name
        self._top_bar["title"].setText(name)
        self._top_bar["back"].show()
        self._top_bar["action"].setText("☏")
        self._top_bar["action"].clicked.disconnect()
        self._top_bar["action"].setProperty("char_name", name)
        self._top_bar["action"].clicked.connect(self._on_call_btn)
        self._clear()
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"QScrollArea {{ background: {get_surface()}; border: none; border-radius: 20px; }}")
        mc = QWidget(); mc.setStyleSheet(f"background: {get_surface()};")
        self._msg_layout = QVBoxLayout(mc)
        self._msg_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._msg_layout.setContentsMargins(4, 6, 4, 6); self._msg_layout.setSpacing(6)
        msgs = sorted(self._own_messages.get(name, []), key=lambda m: m.get("idx", 0))
        for msg in msgs:
            self._add_bubble(msg["text"], msg["is_user"])
        self._msg_layout.addStretch(); scroll.setWidget(mc)
        self._scroll = scroll; QTimer.singleShot(500, self._scroll_down)

        ibar = QWidget()
        ibar.setStyleSheet(f"background: {get_surface()}; border-top: 1px solid {OUTLINE_VARIANT};")
        ibar.setFixedHeight(46)
        il = QHBoxLayout(ibar); il.setContentsMargins(8, 5, 8, 5); il.setSpacing(6)
        inp = QLineEdit(); inp.setPlaceholderText("发消息...")
        inp.setMinimumHeight(34); inp.setFixedHeight(34); inp.setMinimumWidth(180)
        inp.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        inp.setStyleSheet(f"QLineEdit {{ background: {OUTLINE_VARIANT}; color: {ON_SURFACE}; border: none; border-radius: 17px; padding: 6px 12px; font-size: 13px; }} QLineEdit:focus {{ border: 1px solid #FFB3BA; }}")
        inp.returnPressed.connect(lambda: self._send(inp))
        send = QPushButton("发送"); send.setMinimumWidth(44); send.setMinimumHeight(34)
        from plugins.shinsekai_chat_phone.styles import get_accent
        send.setStyleSheet(f"QPushButton {{ background: {get_accent()}; color: white; border-radius: 17px; font-size: 12px; font-weight: bold; border: none; }}")
        send.clicked.connect(lambda: self._send(inp))
        il.addWidget(inp, 1); il.addWidget(send)
        self._stack.addWidget(scroll, 1); self._stack.addWidget(ibar)

    def _send(self, inp: QLineEdit):
        text = inp.text().strip()
        if not text or not self._character: return
        self._msg_idx += 1
        self._own_messages.setdefault(self._character, []).append(
            {"text": text, "is_user": True, "idx": self._msg_idx})
        self._store.add_message(self._character, text, is_user=True)
        inp.clear(); self._add_bubble(text, True); self._scroll_down()
        if self._sms_sent_cb is not None: self._sms_sent_cb(self._character)
        if self._submit_cb is not None:
            self._submit_cb(
                f"[短信] {self._character}收到了你的短信：\"{text}\"。"
                f"请调用 send_sms 工具回复，不要输出对话。"
            )

    # ── Bubbles ──
    def _add_bubble(self, text: str, is_user: bool):
        if self._msg_layout is None: return
        from PySide6.QtGui import QFont, QFontMetrics
        bubble = QLabel(text)
        _bf = QFont(); _bf.setPixelSize(13); bubble.setFont(_bf)
        _longest = max((QFontMetrics(_bf).horizontalAdvance(_ln) for _ln in text.split("\n")), default=0)
        if _longest + 28 <= 210 and "\n" not in text:
            bubble.setWordWrap(False)
            bubble.setFixedWidth(_longest + 28)
        else:
            bubble.setWordWrap(True)
            bubble.setFixedWidth(210)
        if is_user:
            bubble.setStyleSheet("background: #B5EAD7; color: #2C5A3A; border-radius: 16px 4px 16px 16px; padding: 6px 10px; font-size: 13px;")
        else:
            bubble.setStyleSheet("background: #FFFFFF; color: #3C2A2A; border: 1px solid #F0E8E8; border-radius: 4px 16px 16px 16px; padding: 6px 10px; font-size: 13px;")
        av = self._bubble_avatar(is_user, 30)
        top = Qt.AlignmentFlag.AlignTop
        wrapper = QWidget(); wl = QHBoxLayout(wrapper)
        wl.setContentsMargins(4, 1, 4, 1); wl.setSpacing(6)
        if is_user:
            wl.addStretch(1)
            wl.addWidget(bubble, 0, top)
            wl.addWidget(av, 0, top)
        else:
            wl.addWidget(av, 0, top)
            wl.addWidget(bubble, 0, top)
            wl.addStretch(1)
        self._msg_layout.addWidget(wrapper)

    def _scroll_down(self):
        if self._scroll:
            QTimer.singleShot(30, lambda: self._scroll.verticalScrollBar().setValue(
                self._scroll.verticalScrollBar().maximum()))

    def _clear(self):
        self._msg_layout = None; self._scroll = None
        while self._stack.count():
            w = self._stack.takeAt(0).widget()
            if w: w.deleteLater()

    def _on_back(self):
        if self._view == "chat": self._show_list()
        else: self.on_back.emit()

    def _rounded_pixmap_label(self, pix, size):
        """Render a pixmap into a rounded-square QLabel (corner radius size//4)."""
        from PySide6.QtGui import QPixmap, QPainter, QBrush
        av = QLabel(); av.setFixedSize(size, size); av.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rounded = QPixmap(size, size); rounded.fill(Qt.GlobalColor.transparent)
        p = QPainter(rounded); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(pix.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)))
        p.setPen(Qt.PenStyle.NoPen); p.drawRoundedRect(0, 0, size, size, size // 4, size // 4); p.end()
        av.setPixmap(rounded)
        return av

    def _avatar(self, name, size):
        from plugins.shinsekai_chat_phone.avatar_manager import get_avatar_for_character
        pix = get_avatar_for_character(name)
        if pix and not pix.isNull():
            return self._rounded_pixmap_label(pix, size)
        av = QLabel(); av.setFixedSize(size, size); av.setAlignment(Qt.AlignmentFlag.AlignCenter)
        av.setText(name[0] if name else "?")
        c = AVATAR_COLORS[hash(name) % len(AVATAR_COLORS)]
        av.setStyleSheet(f"background: {c}; border-radius: {size // 4}px; color: white; font-size: {size // 2}px; font-weight: bold;")
        return av

    def _bubble_avatar(self, is_user: bool, size: int = 30):
        """Rounded-square avatar beside a bubble: character sprite, or the
        player's uploaded avatar (key '__player__') falling back to a 我 chip."""
        if not is_user:
            return self._avatar(self._character, size)
        from plugins.shinsekai_chat_phone.avatar_manager import get_avatar_for_character
        pix = get_avatar_for_character("__player__")
        if pix and not pix.isNull():
            return self._rounded_pixmap_label(pix, size)
        from plugins.shinsekai_chat_phone.styles import get_accent
        av = QLabel("我"); av.setFixedSize(size, size); av.setAlignment(Qt.AlignmentFlag.AlignCenter)
        av.setStyleSheet(f"background: {get_accent()}; border-radius: {size // 4}px; color: white; font-size: {int(size * 0.42)}px; font-weight: bold;")
        return av


def _top_bar() -> dict:
    w = QWidget(); w.setFixedHeight(48); w.setStyleSheet(f"background: {get_surface()};")
    l = QHBoxLayout(w); l.setContentsMargins(4, 0, 12, 0)
    back = QPushButton("←")
    back.setStyleSheet("QPushButton { background: transparent; color: #FFB3BA; border: none; font-size: 18px; padding: 6px 10px; font-weight: 600; }")
    title = QLabel(""); title.setStyleSheet(f"color: {ON_SURFACE}; font-size: 17px; font-weight: 500;")
    action = QPushButton("")
    action.setStyleSheet("QPushButton { background: transparent; color: #FFB3BA; border: none; font-size: 18px; padding: 6px 10px; }")
    l.addWidget(back); l.addWidget(title, 1); l.addWidget(action)
    return {"widget": w, "back": back, "title": title, "action": action}
