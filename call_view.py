"""Call UI — fills the entire phone frame with centered avatar + controls."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)
from plugins.chat_phone.styles import (
    AVATAR_COLORS, SURFACE, ON_SURFACE, ON_SURFACE_VARIANT,
)


class CallView(QWidget):
    on_accept = Signal()
    on_decline = Signal()
    on_hangup = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {SURFACE};")
        self._character = ""
        self._elapsed = 0
        self._timer: QTimer | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── center area: avatar + name + status ──
        layout.addStretch(1)

        self._avatar = QLabel("")
        self._avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._avatar.setFixedSize(100, 100)
        layout.addWidget(self._avatar, 0, Qt.AlignmentFlag.AlignCenter)

        self._name = QLabel("")
        self._name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name.setStyleSheet(
            f"color: {ON_SURFACE}; font-size: 22px; font-weight: 500; margin-top: 12px;")
        layout.addWidget(self._name)

        self._status = QLabel("")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet(
            f"color: {ON_SURFACE_VARIANT}; font-size: 16px; margin-top: 4px;")
        layout.addWidget(self._status)

        layout.addSpacing(20)

        # ── transcript area ──
        self._transcript = QScrollArea()
        self._transcript.setWidgetResizable(True)
        self._transcript.setStyleSheet(f"QScrollArea {{ background: {SURFACE}; border: none; }}")
        self._transcript.hide()
        self._trans_widget = QWidget()
        self._trans_widget.setStyleSheet(f"background: {SURFACE};")
        self._trans_layout = QVBoxLayout(self._trans_widget)
        self._trans_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._trans_layout.setContentsMargins(16, 4, 16, 4)
        self._trans_layout.setSpacing(6)
        self._trans_layout.addStretch()
        self._transcript.setWidget(self._trans_widget)
        layout.addWidget(self._transcript, 1)

        layout.addStretch(1)

        # ── buttons row at bottom ──
        self._btn_row = QHBoxLayout()
        self._btn_row.setSpacing(30)
        self._btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addLayout(self._btn_row)
        layout.addSpacing(24)

        self._build_buttons()
        # Add all button columns to layout once (never remove)
        self._btn_row.addWidget(self._decline_col)
        self._btn_row.addWidget(self._accept_col)
        self._btn_row.addWidget(self._hangup_col)
        self._btn_row.addWidget(self._cancel_col)
        self._hide_all()

    def _build_buttons(self):
        # accept — green
        self._accept_btn = QPushButton("📞")
        self._accept_btn.setFixedSize(64, 64)
        self._accept_btn.setStyleSheet(
            "QPushButton { background: #34C759; color: white; border-radius: 32px;"
            " font-size: 30px; border: none; }"
            "QPushButton:pressed { background: #2DB84E; }"
        )
        self._accept_btn.clicked.connect(self.on_accept.emit)
        self._accept_lbl = QLabel("接听")
        self._accept_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._accept_lbl.setStyleSheet("color: #34C759; font-size: 12px; font-weight: 600;")
        self._accept_col = _vbox(self._accept_btn, self._accept_lbl)

        # decline — red
        self._decline_btn = QPushButton("✕")
        self._decline_btn.setFixedSize(64, 64)
        self._decline_btn.setStyleSheet(
            "QPushButton { background: #FF3B30; color: white; border-radius: 32px;"
            " font-size: 28px; border: none; }"
            "QPushButton:pressed { background: #E0352B; }"
        )
        self._decline_btn.clicked.connect(self.on_decline.emit)
        self._decline_lbl = QLabel("拒接")
        self._decline_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._decline_lbl.setStyleSheet("color: #FF3B30; font-size: 12px; font-weight: 600;")
        self._decline_col = _vbox(self._decline_btn, self._decline_lbl)

        # hangup — red
        self._hangup_btn = QPushButton("📞")
        self._hangup_btn.setFixedSize(64, 64)
        self._hangup_btn.setStyleSheet(
            "QPushButton { background: #FF3B30; color: white; border-radius: 32px;"
            " font-size: 30px; border: none; }"
            "QPushButton:pressed { background: #E0352B; }"
        )
        self._hangup_btn.clicked.connect(self.on_hangup.emit)
        self._hangup_lbl = QLabel("挂断")
        self._hangup_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hangup_lbl.setStyleSheet("color: #FF3B30; font-size: 12px; font-weight: 600;")
        self._hangup_col = _vbox(self._hangup_btn, self._hangup_lbl)

        # cancel — grey
        self._cancel_btn = QPushButton("✕")
        self._cancel_btn.setFixedSize(64, 64)
        self._cancel_btn.setStyleSheet(
            "QPushButton { background: #8E8E93; color: white; border-radius: 32px;"
            " font-size: 28px; border: none; }"
            "QPushButton:pressed { background: #7A7A80; }"
        )
        self._cancel_btn.clicked.connect(self.on_decline.emit)
        self._cancel_lbl = QLabel("取消")
        self._cancel_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cancel_lbl.setStyleSheet(f"color: {ON_SURFACE_VARIANT}; font-size: 12px;")
        self._cancel_col = _vbox(self._cancel_btn, self._cancel_lbl)

    def show_incoming(self, character: str):
        self._character = character
        self._set_avatar(character)
        self._name.setText(character)
        self._status.setText("来电...")
        self._transcript.hide()
        self._hide_all()
        self._decline_col.show(); self._accept_col.show()
        self._stop_timer()
        self.show(); self.raise_()

    def show_calling(self, character: str):
        self._character = character
        self._set_avatar(character)
        self._name.setText(character)
        self._status.setText("正在呼叫...")
        self._transcript.hide()
        self._hide_all()
        self._cancel_col.show()
        self._stop_timer()
        self.show(); self.raise_()

    def show_in_call(self, character: str):
        self._character = character
        self._set_avatar(character)
        self._name.setText(character)
        self._hide_all()
        self._hangup_col.show()
        self._transcript.hide()
        self._start_timer()
        self.show(); self.raise_()

    def add_subtitle(self, speaker: str, text: str):
        if not text.strip():
            return
        bubble = QLabel(text)
        bubble.setWordWrap(True)
        bubble.setFixedWidth(200)
        is_self = speaker in ("你", "我", "user")
        if is_self:
            bubble.setStyleSheet(
                "background: #B5EAD7; color: #2C5A3A; border-radius: 12px 2px 12px 12px;"
                " padding: 5px 8px; font-size: 11px;")
            wrapper = QWidget()
            wl = QHBoxLayout(wrapper); wl.setContentsMargins(0, 1, 0, 1)
            wl.addStretch(1); wl.addWidget(bubble)
        else:
            bubble.setStyleSheet(
                "background: #F0E8E8; color: #3C2A2A; border-radius: 2px 12px 12px 12px;"
                " padding: 5px 8px; font-size: 11px;")
            wrapper = QWidget()
            wl = QHBoxLayout(wrapper); wl.setContentsMargins(0, 1, 0, 1)
            wl.addWidget(bubble); wl.addStretch(1)
        self._trans_layout.insertWidget(self._trans_layout.count() - 1, wrapper)
        v = self._transcript.verticalScrollBar()
        v.setValue(v.maximum())

    def character(self) -> str:
        return self._character

    def _set_avatar(self, name):
        from plugins.chat_phone.avatar_manager import get_avatar_for_character
        pix = get_avatar_for_character(name)
        if pix is not None and not pix.isNull():
            from PySide6.QtGui import QPixmap, QPainter, QBrush
            rounded = QPixmap(100, 100)
            rounded.fill(Qt.GlobalColor.transparent)
            p = QPainter(rounded)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setBrush(QBrush(pix.scaled(100, 100, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                         Qt.TransformationMode.SmoothTransformation)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(0, 0, 100, 100, 25, 25)
            p.end()
            self._avatar.setPixmap(rounded)
        else:
            initial = name[0] if name else "?"
            c = AVATAR_COLORS[hash(name) % len(AVATAR_COLORS)]
            self._avatar.setText(initial)
            self._avatar.setStyleSheet(
                f"background: {c}; border-radius: 50px;"
                "font-size: 42px; font-weight: bold; color: white;")

    def _start_timer(self):
        self._elapsed = 0; self._update_timer()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(1000)

    def _stop_timer(self):
        if self._timer: self._timer.stop(); self._timer = None

    def _on_tick(self):
        self._elapsed += 1; self._update_timer()

    def _update_timer(self):
        m, s = divmod(self._elapsed, 60)
        self._status.setText(f"{m:02d}:{s:02d}")

    def _clear_transcript(self):
        while self._trans_layout.count() > 1:
            w = self._trans_layout.takeAt(0).widget()
            if w: w.deleteLater()

    def _hide_all(self):
        for c in (self._decline_col, self._accept_col, self._hangup_col, self._cancel_col):
            c.hide()


def _vbox(btn, lbl) -> QWidget:
    w = QWidget()
    w.setStyleSheet("background: transparent;")
    l = QVBoxLayout(w); l.setContentsMargins(0, 0, 0, 0); l.setSpacing(4)
    l.addWidget(btn, 0, Qt.AlignmentFlag.AlignCenter)
    l.addWidget(lbl, 0, Qt.AlignmentFlag.AlignCenter)
    return w
