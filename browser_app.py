"""Browser — Material 3, search via LLM tool (works in CN)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTextEdit, QVBoxLayout, QWidget,
)
from plugins.chat_phone.styles import SURFACE, ON_SURFACE, ON_SURFACE_VARIANT, OUTLINE_VARIANT


class BrowserApp(QWidget):
    on_back = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._submit_cb: object = None  # set by phone widget
        self._setup_ui()

    def set_submit_callback(self, cb: object):
        self._submit_cb = cb

    def show_search_result(self, html: str):
        self._content.setHtml(html)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # top bar
        tb = QWidget()
        tb.setFixedHeight(48)
        tb.setStyleSheet(f"background: {SURFACE};")
        tl = QHBoxLayout(tb)
        tl.setContentsMargins(4, 0, 12, 0)
        b = QPushButton("←")
        b.setStyleSheet(
            "QPushButton { background: transparent; color: #FFB3BA; border: none;"
            " font-size: 18px; padding: 6px 10px; font-weight: 600; }"
        )
        b.clicked.connect(self.on_back.emit)
        t = QLabel("浏览器")
        t.setStyleSheet(f"color: {ON_SURFACE}; font-size: 17px; font-weight: 500;")
        tl.addWidget(b)
        tl.addWidget(t, 1)
        layout.addWidget(tb)

        # search bar
        sbar = QWidget()
        sbar.setStyleSheet(f"background: {SURFACE}; padding: 8px;")
        sl = QHBoxLayout(sbar)
        sl.setContentsMargins(12, 4, 12, 4)
        sl.setSpacing(8)
        self._inp = QLineEdit()
        self._inp.setPlaceholderText("输入问题，通过 AI 联网搜索...")
        self._inp.setStyleSheet(
            f"QLineEdit {{ background: {OUTLINE_VARIANT}; color: {ON_SURFACE};"
            f" border: none; border-radius: 20px; padding: 10px 16px; font-size: 13px; }}"
            f"QLineEdit:focus {{ border: 1px solid #FFB3BA; }}"
        )
        self._inp.returnPressed.connect(self._search)
        go = QPushButton("搜索")
        go.setStyleSheet(
            "QPushButton { background: #FFB3BA; color: white; border-radius: 16px;"
            " padding: 8px 16px; font-size: 12px; font-weight: 600; border: none; }"
        )
        go.clicked.connect(self._search)
        sl.addWidget(self._inp, 1)
        sl.addWidget(go)
        layout.addWidget(sbar)

        # content
        self._content = QTextEdit()
        self._content.setReadOnly(True)
        self._content.setStyleSheet(
            f"QTextEdit {{ background: white; color: #3C2A2A;"
            f" border: none; font-size: 13px; padding: 12px; }}"
        )
        self._content.setHtml(
            "<p style='color:#8A7A7A; text-align:center; padding-top:40px;'>"
            "输入问题，通过 AI 搜索回答</p>"
        )
        layout.addWidget(self._content, 1)

    def _search(self):
        q = self._inp.text().strip()
        if not q:
            return
        self._content.setHtml(
            f"<p style='color:#8A7A7A; text-align:center; padding-top:40px;'>"
            f"正在搜索: {q}...</p>"
        )
        # Send query through LLM (uses submit_user_message → LLM with web search if available)
        if self._submit_cb is not None:
            self._submit_cb(f"[联网搜索] {q}")  # type: ignore[operator]
