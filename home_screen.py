"""Material 3 home screen with macaron icon grid + custom PNG icons."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout,
    QLabel, QPushButton, QVBoxLayout, QWidget,
)
from plugins.shinsekai_chat_phone.styles import (
    ACCENT_BROWSER, ACCENT_MEMOS, ACCENT_MESSAGES, ACCENT_PHONE,
    get_surface, ON_SURFACE, ON_SURFACE_VARIANT, OUTLINE_VARIANT,
)
import time as _time

_ASSETS = Path(__file__).parent / "assets"
_dnd_ref: object = None  # Store reference for external toggle

def _set_dnd_visible(visible: bool):
    global _dnd_ref
    if _dnd_ref is not None:
        _dnd_ref.setVisible(visible)

# Accent colours — macaron palette, unique per app
ACCENT_MUSIC    = "#C7CEEA"  # lavender
ACCENT_SETTINGS = "#E0D5D5"  # warm gray
ACCENT_LOCATION = "#FFDAC1"  # peach
ACCENT_VIDEO    = "#FFB3BA"  # pastel pink
ACCENT_GROUP    = "#FCE1A4"  # light yellow
ACCENT_MOMENTS  = "#D4B8D9"  # light purple


class HomeScreen(QWidget):
    app_launched = Signal(str)
    minimize_requested = Signal()  # user tapped the home bar to collapse the phone

    APPS = [
        # (app_id, label, emoji_or_text, color, font_size, icon_path, icon_scale)
        ("phone",    "通话",   "☏", ACCENT_PHONE,    28, "phone.png",       36),
        ("messages", "短信",   None, ACCENT_MESSAGES,  0, "messages_new.png",36),
        ("group",    "群聊",   None, ACCENT_GROUP,     0, "group_chat.png",  48),
        ("moments",  "朋友圈", None, ACCENT_MOMENTS,   0, "moments.png",     36),
        ("music",    "音乐",   None, ACCENT_MUSIC,     0, "music.png",       36),
        ("browser",  "浏览器", None, ACCENT_BROWSER,   0, "browser.png",     36),
        ("location", "定位",   None, ACCENT_LOCATION,  0, "location.png",    36),
        ("settings", "设置",   None, ACCENT_SETTINGS,  0, "settings.png",    36),
        ("memos",    "录音",   "●", ACCENT_MEMOS,     32, None,              0),
        ("video",    "视频",   None, ACCENT_VIDEO,     0, "video.png",       36),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._messages_icon: _MacaronIcon | None = None
        self._last_badge_count: int = -1
        self._group_icon: _MacaronIcon | None = None
        self._last_group_badge: int = -1
        self._moments_icon: _MacaronIcon | None = None
        self._last_moments_badge: int = -1
        self.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)

        self._time_label = QLabel(_fmt_time())
        self._time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._time_label.setStyleSheet(
            f"color: {ON_SURFACE}; font-size: 11px; font-weight: 600; padding: 8px 0 4px 0;")
        layout.addWidget(self._time_label)
        layout.addSpacing(4)

        # Status bar: signal + battery right-aligned
        srow = QWidget(); srow.setMinimumWidth(280)
        sl = QHBoxLayout(srow); sl.setContentsMargins(20, 0, 40, 0); sl.setSpacing(4)
        from plugins.shinsekai_chat_phone.settings_app import is_dnd
        self._dnd_icon = QLabel("\U0001F319")
        self._dnd_icon.setStyleSheet("font-size: 10px; background: transparent;")
        self._dnd_icon.setVisible(is_dnd())
        global _dnd_ref; _dnd_ref = self._dnd_icon
        sl.addWidget(self._dnd_icon)
        sl.addSpacing(4)
        sl.addStretch()
        sig_icon = QLabel()
        sig_pix = QPixmap(str(_ASSETS / "signal.png"))
        if not sig_pix.isNull():
            sig_icon.setPixmap(sig_pix.scaled(14, 14, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        sig_icon.setStyleSheet("background: transparent;")
        sig_label = QLabel("5G")
        sig_label.setStyleSheet(f"color: {ON_SURFACE}; font-size: 10px; background: transparent;")
        bat = QLabel("85% ▯")
        bat.setStyleSheet(f"color: {ON_SURFACE}; font-size: 10px; background: transparent;")
        sl.addWidget(sig_icon); sl.addWidget(sig_label); sl.addSpacing(6); sl.addWidget(bat)
        from plugins.shinsekai_chat_phone.styles import _darken, get_bg
        darker = _darken(get_bg(), 0.08)
        srow.setStyleSheet(f"background: {darker};")
        layout.addWidget(srow)
        layout.addSpacing(20)

        grid = QGridLayout()
        grid.setContentsMargins(18, 0, 18, 0)
        grid.setHorizontalSpacing(8); grid.setVerticalSpacing(8)

        for i, item in enumerate(self.APPS):
            app_id, label, emoji, color = item[0], item[1], item[2], item[3]
            fs = item[4] if len(item) > 4 else 26
            icon_path = item[5] if len(item) > 5 else None
            icon_scale = item[6] if len(item) > 6 else 36
            row, col = divmod(i, 3)
            pix = QPixmap(str(_ASSETS / icon_path)) if icon_path else None
            if pix and pix.isNull():
                pix = None
            btn = _MacaronIcon(app_id, emoji, label, color, fs, pix, icon_scale=icon_scale)
            btn.clicked.connect(self._make_launch(app_id))
            if app_id == "messages":
                self._messages_icon = btn
            elif app_id == "group":
                self._group_icon = btn
            elif app_id == "moments":
                self._moments_icon = btn
            grid.addWidget(btn, row, col)
        layout.addLayout(grid)
        layout.addStretch()

        # Home bar — tap to collapse the phone (swipe-up analog); enlarged hit area.
        home_bar = QWidget()
        home_bar.setFixedHeight(24)
        home_bar.setCursor(Qt.CursorShape.PointingHandCursor)
        home_bar.setToolTip("收起手机")
        hb = QVBoxLayout(home_bar); hb.setContentsMargins(0, 6, 0, 8)
        hb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pill = QWidget(); pill.setFixedSize(100, 5)
        pill.setStyleSheet(f"background: {OUTLINE_VARIANT}; border-radius: 3px;")
        hb.addWidget(pill, 0, Qt.AlignmentFlag.AlignCenter)
        home_bar.mousePressEvent = lambda e: self.minimize_requested.emit()
        layout.addWidget(home_bar)

        self._timer = QTimer(self)
        self._timer.timeout.connect(lambda: self._time_label.setText(_fmt_time()))
        self._timer.start(30_000)

    def set_messages_badge(self, count: int) -> None:
        """Update unread badge on the Messages app icon (no-op if unchanged)."""
        if count == self._last_badge_count:
            return
        self._last_badge_count = count
        if self._messages_icon is not None:
            self._messages_icon.set_badge(count)

    def set_group_badge(self, count: int) -> None:
        """Update unread badge on the 群聊 app icon (no-op if unchanged)."""
        if count == self._last_group_badge:
            return
        self._last_group_badge = count
        if self._group_icon is not None:
            self._group_icon.set_badge(count)

    def set_moments_badge(self, count: int) -> None:
        """Update unread badge on the 朋友圈 app icon (no-op if unchanged)."""
        if count == self._last_moments_badge:
            return
        self._last_moments_badge = count
        if self._moments_icon is not None:
            self._moments_icon.set_badge(count)

    def _make_launch(self, app_id): return lambda: self.app_launched.emit(app_id)


class _MacaronIcon(QPushButton):
    def __init__(self, app_id, emoji, label, color, font_size=26, pixmap=None, parent=None,
                 icon_scale=36):
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
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if pixmap and not pixmap.isNull():
            s = icon_scale or 36
            lbl.setPixmap(pixmap.scaled(s, s, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            lbl.setStyleSheet("background: transparent;")
        else:
            lbl.setText(emoji or "")
            lbl.setStyleSheet(f"font-size: {font_size}px; background: transparent;")
        il.addWidget(lbl)
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignCenter)

        nl = QLabel(label)
        nl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nl.setStyleSheet(f"color: {ON_SURFACE}; font-size: 10px; font-weight: 400; background: transparent;")
        layout.addWidget(nl, 0, Qt.AlignmentFlag.AlignCenter)

        # Badge overlay on top-right of icon
        import random as _random
        bid = f"app_badge_{_random.randint(0, 9999)}"
        self._badge = QLabel("", self)
        self._badge.setObjectName(bid)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setStyleSheet(
            f"#{bid} {{ background: #FF3B30; color: white;"
            " border: 2px solid white; border-radius: 11px;"
            " font-size: 10px; font-weight: bold;"
            " min-width: 22px; min-height: 22px; }}"
        )
        self._badge.hide()
        self._icon_widget = icon  # store ref for positioning badge

    def set_badge(self, count: int) -> None:
        """Show/hide badge with count on the icon's top-right corner."""
        if count > 0:
            t = str(count) if count <= 99 else "99+"
            self._badge.setText(t)
            self._badge.adjustSize()
            # Position at top-right of the icon widget (overlapping the corner)
            ix = self._icon_widget.x() + self._icon_widget.width() - self._badge.width() // 2 - 4
            iy = self._icon_widget.y() - self._badge.height() // 2 + 4
            self._badge.move(ix, iy)
            self._badge.show()
            self._badge.raise_()
        else:
            self._badge.hide()


def _fmt_time(): return _time.strftime("%H:%M")
