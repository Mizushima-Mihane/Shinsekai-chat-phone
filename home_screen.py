"""Material 3 home screen with macaron icon grid."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout,
    QLabel, QPushButton, QVBoxLayout, QWidget,
)
from plugins.chat_phone.styles import (
    ACCENT_BROWSER, ACCENT_MEMOS, ACCENT_MESSAGES, ACCENT_PHONE,
    SURFACE, ON_SURFACE, ON_SURFACE_VARIANT, OUTLINE_VARIANT,
)
import time as _time


class HomeScreen(QWidget):
    app_launched = Signal(str)

    APPS = [
        ("phone",    "通话",   "☎", ACCENT_PHONE,    24),
        ("messages", "短信",   "✉", ACCENT_MESSAGES, 34),
        ("memos",    "录音",   "●", ACCENT_MEMOS,    32),
        ("browser",  "浏览器", "⌘", ACCENT_BROWSER,  24),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {SURFACE};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)

        self._time_label = QLabel(_fmt_time())
        self._time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._time_label.setStyleSheet(
            f"color: {ON_SURFACE}; font-size: 11px; font-weight: 600; padding: 8px 0 4px 0;")
        layout.addWidget(self._time_label)
        layout.addSpacing(20)

        # Status bar
        srow = QWidget()
        srow.setMinimumWidth(280)
        sl = QHBoxLayout(srow)
        sl.setContentsMargins(20, 0, 20, 0); sl.setSpacing(4)
        sl.addStretch()
        sig = QLabel("5G")
        sig.setStyleSheet(f"color: {ON_SURFACE}; font-size: 10px; background: transparent;")
        bars = QLabel("| | | |")
        bars.setStyleSheet(f"color: {ON_SURFACE}; font-size: 10px; background: transparent; letter-spacing: -1px;")
        bat = QLabel("85% ▯")
        bat.setStyleSheet(f"color: {ON_SURFACE}; font-size: 10px; background: transparent;")
        sl.addWidget(sig)
        sl.addWidget(bars)
        sl.addSpacing(4)
        sl.addWidget(bat)
        layout.addWidget(srow)
        layout.addSpacing(20)

        grid = QGridLayout()
        grid.setContentsMargins(18, 0, 18, 0)
        grid.setHorizontalSpacing(8); grid.setVerticalSpacing(8)

        for i, (app_id, label, emoji, color, *fs) in enumerate(self.APPS):
            font_size = fs[0] if fs else 26
            row, col = divmod(i, 3)
            btn = _MacaronIcon(app_id, emoji, label, color, font_size)
            btn.clicked.connect(self._make_launch(app_id))
            grid.addWidget(btn, row, col)
        layout.addLayout(grid)
        layout.addStretch()

        pill = QWidget()
        pill.setFixedHeight(5)
        pill.setStyleSheet(f"background: {OUTLINE_VARIANT}; border-radius: 3px; margin: 0 120px 8px 120px;")
        layout.addWidget(pill)

        self._timer = QTimer(self)
        self._timer.timeout.connect(lambda: self._time_label.setText(_fmt_time()))
        self._timer.start(30_000)

    def _make_launch(self, app_id): return lambda: self.app_launched.emit(app_id)


class _MacaronIcon(QPushButton):
    def __init__(self, app_id, emoji, label, color, font_size=26, parent=None):
        super().__init__(parent)
        self.setFixedSize(80, 88)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 0, 6, 0); layout.setSpacing(6)

        icon = QWidget()
        icon.setFixedSize(60, 60)
        icon.setStyleSheet(f"QWidget {{ background: {color}; border-radius: 18px; }}")
        shadow = QGraphicsDropShadowEffect(icon)
        shadow.setBlurRadius(12); shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 25))
        icon.setGraphicsEffect(shadow)

        il = QVBoxLayout(icon); il.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(emoji)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(f"font-size: {font_size}px; background: transparent;")
        il.addWidget(lbl)
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignCenter)

        nl = QLabel(label)
        nl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nl.setStyleSheet(f"color: {ON_SURFACE}; font-size: 10px; font-weight: 400; background: transparent;")
        layout.addWidget(nl, 0, Qt.AlignmentFlag.AlignCenter)


def _fmt_time(): return _time.strftime("%H:%M")
