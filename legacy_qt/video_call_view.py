"""Video call UI — sprite display with PiP avatar overlay."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QPixmap, QPainter, QBrush
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from plugins.shinsekai_chat_phone.styles import (
    AVATAR_COLORS, get_surface, ON_SURFACE, ON_SURFACE_VARIANT,
)


class VideoCallView(QWidget):
    on_accept = Signal()
    on_decline = Signal()
    on_hangup = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._character = ""
        self._elapsed = 0
        self._timer: QTimer | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background: #1C1C1E;")

        # ── Top bar (semi-transparent overlay) ──
        self._top_bar = QWidget(self)
        self._top_bar.setFixedHeight(60)
        self._top_bar.setStyleSheet("background: rgba(0,0,0,100);")
        tl = QHBoxLayout(self._top_bar)
        tl.setContentsMargins(12, 6, 12, 6)
        tl.setSpacing(10)

        self._pip_avatar = QLabel()
        self._pip_avatar.setFixedSize(44, 44)
        self._pip_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tl.addWidget(self._pip_avatar)

        info = QVBoxLayout()
        info.setSpacing(0)
        self._name_label = QLabel("")
        self._name_label.setStyleSheet("color: white; font-size: 15px; font-weight: 500; background: transparent;")
        info.addWidget(self._name_label)
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #AAA; font-size: 12px; background: transparent;")
        info.addWidget(self._status_label)
        tl.addLayout(info, 1)

        # ── Sprite area ──
        self._sprite_label = QLabel()
        self._sprite_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sprite_label.setStyleSheet("background: transparent;")
        self._sprite_label.setScaledContents(False)

        # ── Bottom buttons ──
        bottom = QWidget()
        bottom.setStyleSheet("background: rgba(0,0,0,80);")
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 16)
        bl.setSpacing(40)
        bl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._decline_btn = QPushButton("✕")
        self._decline_btn.setFixedSize(64, 64)
        self._decline_btn.setStyleSheet(
            "QPushButton { background: #FF3B30; color: white; border-radius: 32px;"
            " font-size: 28px; border: none; }"
            "QPushButton:pressed { background: #AA0000; }"
        )
        self._decline_btn.clicked.connect(self.on_decline.emit)

        self._accept_btn = QPushButton()
        self._accept_btn.setFixedSize(64, 64)
        _accept_pix = QPixmap(str(Path(__file__).parent / "assets" / "call_answer.png"))
        if not _accept_pix.isNull():
            self._accept_btn.setIcon(_accept_pix.scaled(36, 36, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            self._accept_btn.setText("📞")
        self._accept_btn.setStyleSheet(
            "QPushButton { background: #7AE582; color: white; border-radius: 32px;"
            " border: none; }"
            "QPushButton:pressed { background: #5CC972; }"
        )
        self._accept_btn.clicked.connect(self.on_accept.emit)

        self._hangup_btn = QPushButton("📞")
        self._hangup_btn.setFixedSize(64, 64)
        self._hangup_btn.setStyleSheet(
            "QPushButton { background: #FF3B30; color: white; border-radius: 32px;"
            " font-size: 30px; border: none; }"
            "QPushButton:pressed { background: #AA0000; }"
        )
        self._hangup_btn.clicked.connect(self.on_hangup.emit)

        bl.addWidget(self._decline_btn)
        bl.addWidget(self._accept_btn)
        bl.addWidget(self._hangup_btn)

        # ── Assemble ──
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._top_bar)
        layout.addWidget(self._sprite_label, 1)
        layout.addWidget(bottom)

    # ── public API ──────────────────────────────────────────────────

    def show_incoming(self, character: str):
        self._character = character
        self._set_pip_avatar(character)
        self._name_label.setText(character)
        self._status_label.setText("视频来电...")
        self._decline_btn.show()
        self._accept_btn.show()
        self._hangup_btn.hide()
        self._stop_timer()
        self.show()
        self.raise_()

    def show_calling(self, character: str):
        self._character = character
        self._set_pip_avatar(character)
        self._name_label.setText(character)
        self._status_label.setText("正在呼叫...")
        self._decline_btn.hide()
        self._accept_btn.hide()
        self._hangup_btn.show()  # acts as cancel
        self._stop_timer()
        self.show()
        self.raise_()

    def show_in_call(self, character: str):
        self._character = character
        self._set_pip_avatar(character)
        self._name_label.setText(character)
        self._decline_btn.hide()
        self._accept_btn.hide()
        self._hangup_btn.show()
        self._load_initial_sprite()
        self._start_timer()
        self.show()
        self.raise_()

    def update_sprite(self, sprite_index: str) -> None:
        """Update the displayed sprite from LLM dialog sprite index."""
        if sprite_index == "-1" or not sprite_index or not self._character:
            return
        path = _resolve_sprite_path(self._character, sprite_index)
        if path:
            self._display_sprite(path)

    def character(self) -> str:
        return self._character

    def hide(self):
        self._stop_timer()
        super().hide()

    # ── internals ───────────────────────────────────────────────────

    def _load_initial_sprite(self):
        """Load sprite index 0 after layout settles, or fall back to avatar."""
        # Delay to let layout assign proper size to sprite_label
        QTimer.singleShot(100, self._do_load_initial_sprite)

    def _do_load_initial_sprite(self):
        path = _resolve_sprite_path(self._character, "0")
        if path:
            self._display_sprite(path)
        else:
            # Fallback: large avatar
            pix = _load_avatar_pixmap(self._character)
            if pix and not pix.isNull():
                w = self._sprite_label.width() or self.width()
                h = self._sprite_label.height() or self.height()
                self._sprite_label.setPixmap(
                    pix.scaled(w, h,
                               Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation))

    def _display_sprite(self, path: str):
        pix = QPixmap(path)
        if pix.isNull():
            return
        w = self._sprite_label.width() or self.width()
        h = self._sprite_label.height() or self.height()
        self._sprite_label.setPixmap(
            pix.scaled(w, h,
                       Qt.AspectRatioMode.KeepAspectRatio,
                       Qt.TransformationMode.SmoothTransformation))
        self._sprite_label.repaint()

    def _set_pip_avatar(self, name: str):
        pix = _load_avatar_pixmap(name)
        if pix and not pix.isNull():
            rounded = QPixmap(44, 44)
            rounded.fill(Qt.GlobalColor.transparent)
            p = QPainter(rounded)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setBrush(QBrush(pix.scaled(44, 44, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                         Qt.TransformationMode.SmoothTransformation)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(0, 0, 44, 44, 22, 22)
            p.end()
            self._pip_avatar.setPixmap(rounded)
        else:
            self._pip_avatar.setText(name[0] if name else "?")
            c = AVATAR_COLORS[hash(name) % len(AVATAR_COLORS)]
            self._pip_avatar.setStyleSheet(
                f"background:{c}; border-radius:22px; color:white; font-size:20px; font-weight:bold;")
            self._pip_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def _start_timer(self):
        self._elapsed = 0
        self._update_timer()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(1000)

    def _stop_timer(self):
        if self._timer:
            self._timer.stop()
            self._timer = None

    def _on_tick(self):
        self._elapsed += 1
        self._update_timer()

    def _update_timer(self):
        m, s = divmod(self._elapsed, 60)
        self._status_label.setText(f"{m:02d}:{s:02d}")


# ── helpers ────────────────────────────────────────────────────────

def _resolve_sprite_path(character: str, sprite_index: str) -> str | None:
    """Resolve a sprite index string to a file path for the character."""
    try:
        idx = int(sprite_index)
        from config.config_manager import ConfigManager
        cm = ConfigManager()
        for ch in cm.config.characters:
            if ch.name == character and ch.sprites:
                if 0 <= idx < len(ch.sprites):
                    sprite = ch.sprites[idx]
                    if isinstance(sprite, dict):
                        path = sprite.get("path", "")
                    else:
                        path = getattr(sprite, "path", "")
                    if path and Path(path).is_file():
                        return path
    except Exception:
        pass
    return None


def _load_avatar_pixmap(name: str) -> QPixmap | None:
    """Load avatar pixmap for a character (same as get_avatar_for_character)."""
    from plugins.shinsekai_chat_phone.avatar_manager import get_avatar_for_character
    return get_avatar_for_character(name)
