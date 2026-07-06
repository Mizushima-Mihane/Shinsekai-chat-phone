"""Call UI — simple centered layout as overlay."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)
from plugins.shinsekai_chat_phone.styles import (
    AVATAR_COLORS, get_surface, ON_SURFACE, ON_SURFACE_VARIANT,
)


class CallView(QWidget):
    on_accept = Signal()
    on_decline = Signal()
    on_hangup = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {get_surface()};")
        self._character = ""
        self._elapsed = 0
        self._timer: QTimer | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 40, 0, 30); layout.setSpacing(0)

        layout.addStretch(1)

        self._avatar = QLabel("")
        self._avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._avatar.setFixedSize(120, 120)
        layout.addWidget(self._avatar, 0, Qt.AlignmentFlag.AlignCenter)

        layout.addSpacing(16)

        self._name = QLabel("")
        self._name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name.setStyleSheet(f"color: {ON_SURFACE}; font-size: 24px; font-weight: 500;")
        layout.addWidget(self._name)

        layout.addSpacing(4)

        self._status = QLabel("")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet(f"color: {ON_SURFACE_VARIANT}; font-size: 16px;")
        layout.addWidget(self._status)

        layout.addSpacing(40)

        self._btn_row = QHBoxLayout()
        self._btn_row.setSpacing(40)
        self._btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addLayout(self._btn_row)
        layout.addStretch(1)

        self._build_buttons()
        for col in (self._decline_col, self._accept_col, self._hangup_col, self._cancel_col):
            self._btn_row.addWidget(col); col.hide()

    def _build_buttons(self):
        def _col(btn, lbl_text, lbl_color):
            w = QWidget(); w.setStyleSheet("background: transparent;")
            l = QVBoxLayout(w); l.setContentsMargins(0,0,0,0); l.setSpacing(4)
            l.addWidget(btn, 0, Qt.AlignmentFlag.AlignCenter)
            lb = QLabel(lbl_text); lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lb.setStyleSheet(f"color: {lbl_color}; font-size: 12px; font-weight: 600;")
            l.addWidget(lb, 0, Qt.AlignmentFlag.AlignCenter)
            return w

        self._accept_btn = QPushButton()
        self._accept_btn.setFixedSize(64, 64)
        _accept_pix = QPixmap(str(Path(__file__).parent / "assets" / "call_answer.png"))
        if not _accept_pix.isNull():
            self._accept_btn.setIcon(_accept_pix.scaled(36, 36, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            self._accept_btn.setText("📞")
        self._accept_btn.setStyleSheet("QPushButton { background: #7AE582; color: white; border-radius: 32px; border: none; }")
        self._accept_btn.clicked.connect(self.on_accept.emit)
        self._accept_col = _col(self._accept_btn, "接听", "#7AE582")

        self._decline_btn = QPushButton("✕"); self._decline_btn.setFixedSize(64, 64)
        self._decline_btn.setStyleSheet("QPushButton { background: #FF3B30; color: white; border-radius: 32px; font-size: 28px; border: none; }")
        self._decline_btn.clicked.connect(self.on_decline.emit)
        self._decline_col = _col(self._decline_btn, "拒接", "#FF3B30")

        self._hangup_btn = QPushButton("📞"); self._hangup_btn.setFixedSize(64, 64)
        self._hangup_btn.setStyleSheet("QPushButton { background: #FF3B30; color: white; border-radius: 32px; font-size: 30px; border: none; }")
        self._hangup_btn.clicked.connect(self.on_hangup.emit)
        self._hangup_col = _col(self._hangup_btn, "挂断", "#FF3B30")

        self._cancel_btn = QPushButton("✕"); self._cancel_btn.setFixedSize(64, 64)
        self._cancel_btn.setStyleSheet("QPushButton { background: #8E8E93; color: white; border-radius: 32px; font-size: 28px; border: none; }")
        self._cancel_btn.clicked.connect(self.on_decline.emit)
        self._cancel_col = _col(self._cancel_btn, "取消", "#8E8E93")

    def show_incoming(self, character: str):
        self._character = character; self._set_avatar(character)
        self._name.setText(character); self._status.setText("来电...")
        self._hide_all(); self._decline_col.show(); self._accept_col.show()
        self._stop_timer(); self.show(); self.raise_()

    def show_calling(self, character: str):
        self._character = character; self._set_avatar(character)
        self._name.setText(character); self._status.setText("正在呼叫...")
        self._hide_all(); self._cancel_col.show()
        self._stop_timer(); self.show(); self.raise_()

    def show_in_call(self, character: str):
        self._character = character; self._set_avatar(character)
        self._name.setText(character)
        self._hide_all(); self._hangup_col.show()
        self._start_timer(); self.show(); self.raise_()

    def character(self) -> str: return self._character

    def _set_avatar(self, name):
        from plugins.shinsekai_chat_phone.avatar_manager import get_avatar_for_character
        from PySide6.QtGui import QPixmap, QPainter, QBrush
        pix = get_avatar_for_character(name)
        if pix and not pix.isNull():
            r = QPixmap(120, 120); r.fill(Qt.GlobalColor.transparent)
            p = QPainter(r); p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setBrush(QBrush(pix.scaled(120,120,Qt.AspectRatioMode.KeepAspectRatioByExpanding,Qt.TransformationMode.SmoothTransformation)))
            p.setPen(Qt.PenStyle.NoPen); p.drawRoundedRect(0,0,120,120,30,30); p.end()
            self._avatar.setPixmap(r)
        else:
            self._avatar.setText(name[0] if name else "?"); c = AVATAR_COLORS[hash(name)%len(AVATAR_COLORS)]
            self._avatar.setStyleSheet(f"background:{c};border-radius:60px;color:white;font-size:48px;font-weight:bold;")

    def _start_timer(self):
        self._elapsed=0; self._update_timer()
        self._timer=QTimer(self); self._timer.timeout.connect(self._on_tick); self._timer.start(1000)

    def _stop_timer(self):
        if self._timer: self._timer.stop(); self._timer=None

    def _on_tick(self): self._elapsed+=1; self._update_timer()

    def _update_timer(self):
        m,s=divmod(self._elapsed,60); self._status.setText(f"{m:02d}:{s:02d}")

    def _hide_all(self):
        for c in (self._decline_col, self._accept_col, self._hangup_col, self._cancel_col): c.hide()
