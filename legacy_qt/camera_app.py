"""Camera — Material 3 macaron, screen capture."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)
from plugins.shinsekai_chat_phone.styles import get_surface, ON_SURFACE_VARIANT


class CameraApp(QWidget):
    on_back = Signal()

    def __init__(self, data_dir: Path, parent=None):
        super().__init__(parent)
        self._dir = Path(data_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._pixmap: QPixmap | None = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # top bar
        tb = QWidget()
        tb.setFixedHeight(48)
        tb.setStyleSheet(f"background: {get_surface()};")
        tl = QHBoxLayout(tb)
        tl.setContentsMargins(4, 0, 12, 0)
        b = QPushButton("←")
        b.setStyleSheet(
            "QPushButton { background: transparent; color: #FFB3BA; border: none;"
            " font-size: 18px; padding: 6px 10px; font-weight: 600; }"
        )
        b.clicked.connect(self.on_back.emit)
        t = QLabel("相机")
        t.setStyleSheet(f"color: {ON_SURFACE_VARIANT}; font-size: 17px; font-weight: 500;")
        tl.addWidget(b)
        tl.addWidget(t, 1)
        layout.addWidget(tb)

        # preview
        self._preview = QLabel("📷\n点击拍照")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setStyleSheet(
            f"color: {ON_SURFACE_VARIANT}; font-size: 14px; background: {get_surface()};"
        )
        layout.addWidget(self._preview, 1)

        # shutter
        fw = QWidget()
        fw.setFixedHeight(80)
        fw.setStyleSheet(f"background: {get_surface()};")
        fl = QHBoxLayout(fw)
        fl.setContentsMargins(0, 0, 0, 0)
        cap = QPushButton()
        cap.setFixedSize(64, 64)
        cap.setStyleSheet(
            "QPushButton { background: white; border: 3px solid #E0D5D5;"
            " border-radius: 32px; }"
            "QPushButton:pressed { background: #F5F0F0; }"
        )
        cap.clicked.connect(self._capture)
        fl.addStretch()
        fl.addWidget(cap)
        fl.addStretch()
        layout.addWidget(fw)

    def _capture(self):
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        from plugins.shinsekai_chat_phone import sound_fx as _sfx
        _sfx.play(_sfx.SHUTTER)
        self._pixmap = screen.grabWindow(0)
        scaled = self._pixmap.scaled(260, 350,
                                     Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
        self._preview.setPixmap(scaled)
        ts = time.strftime("%Y%m%d_%H%M%S")
        try:
            self._pixmap.save(str(self._dir / f"screenshot_{ts}.png"))
        except Exception:
            pass
