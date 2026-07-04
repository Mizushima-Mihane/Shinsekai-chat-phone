"""Contacts app — Material 3 with macaron colours."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from plugins.chat_phone.styles import (
    AVATAR_COLORS, SURFACE, ON_SURFACE, ON_SURFACE_VARIANT, OUTLINE_VARIANT,
)


class ContactsApp(QWidget):
    on_back = Signal()
    on_call = Signal(str)
    on_message = Signal(str)

    def __init__(self, contacts: list[str], parent=None):
        super().__init__(parent)
        self._contacts = contacts
        self._setup_ui()
        self._show()

    def refresh(self, contacts):
        self._contacts = list(contacts)
        self._show()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        tb = _top_bar("通讯录", self.on_back.emit)
        layout.addWidget(tb)

        self._stack = QVBoxLayout()
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.setSpacing(0)
        layout.addLayout(self._stack, 1)

    def _show(self):
        _clear(self._stack)
        if not self._contacts:
            hint = QLabel("还没有联系人\n在聊天中交换联系方式吧~")
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hint.setStyleSheet(f"color: {ON_SURFACE_VARIANT}; font-size: 13px;")
            self._stack.addWidget(hint, 1)
            return

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        c = QWidget()
        c.setStyleSheet(f"background: {SURFACE};")
        cl = QVBoxLayout(c)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        from config.config_manager import ConfigManager
        try:
            cm = ConfigManager()
            ac = {ch.name: ch for ch in cm.config.characters}
        except Exception:
            ac = {}

        for name in sorted(self._contacts):
            ch = ac.get(name)
            setting = (ch.character_setting or "")[:60] if ch else ""

            row = QWidget()
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row.mousePressEvent = self._make_tap(name)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(16, 10, 8, 10)
            rl.setSpacing(12)

            av = _avatar(name, 40)
            rl.addWidget(av)

            tv = QVBoxLayout()
            tv.setSpacing(2)
            nlb = QLabel(name)
            nlb.setStyleSheet(f"color: {ON_SURFACE}; font-size: 14px; font-weight: 500;")
            tv.addWidget(nlb)
            if setting:
                slb = QLabel(setting)
                slb.setStyleSheet(f"color: {ON_SURFACE_VARIANT}; font-size: 11px;")
                slb.setMaximumWidth(140)
                tv.addWidget(slb)
            rl.addLayout(tv, 1)

            mb = QPushButton("\U0001F4AC")
            mb.setFixedSize(34, 34)
            mb.setStyleSheet("background: transparent; border: none; font-size: 16px;")
            mb.clicked.connect(lambda n=name: self.on_message.emit(n))
            cb = QPushButton("\U0001F4DE")
            cb.setFixedSize(34, 34)
            cb.setStyleSheet("background: transparent; border: none; font-size: 16px;")
            cb.clicked.connect(lambda n=name: self.on_call.emit(n))
            rl.addWidget(mb)
            rl.addWidget(cb)

            cl.addWidget(row)
        cl.addStretch()
        scroll.setWidget(c)
        self._stack.addWidget(scroll, 1)

    def _make_tap(self, name: str):
        def handler(event):
            self.on_message.emit(name)
        return handler


def _top_bar(title: str, on_back) -> QWidget:
    w = QWidget()
    w.setFixedHeight(48)
    w.setStyleSheet(f"background: {SURFACE};")
    l = QHBoxLayout(w)
    l.setContentsMargins(4, 0, 12, 0)
    b = QPushButton("←")
    b.setStyleSheet(
        "QPushButton { background: transparent; color: #FFB3BA; border: none;"
        " font-size: 18px; padding: 6px 10px; font-weight: 600; }"
    )
    b.clicked.connect(on_back)
    t = QLabel(title)
    t.setStyleSheet(f"color: {ON_SURFACE}; font-size: 17px; font-weight: 500;")
    l.addWidget(b)
    l.addWidget(t, 1)
    return w


def _avatar(name: str, size: int) -> QLabel:
    av = QLabel(name[0] if name else "?")
    av.setFixedSize(size, size)
    av.setAlignment(Qt.AlignmentFlag.AlignCenter)
    c = AVATAR_COLORS[hash(name) % len(AVATAR_COLORS)]
    r = size // 2
    av.setStyleSheet(f"background: {c}; border-radius: {r}px; color: white; font-size: {size//2}px; font-weight: bold;")
    return av


def _clear(layout):
    while layout.count():
        w = layout.takeAt(0).widget()
        if w: w.deleteLater()
