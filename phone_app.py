"""Phone app — Material 3 with call history + duration tracking."""

from __future__ import annotations

import json
import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

# (QPushButton already in imports above)


from plugins.chat_phone.styles import (
    AVATAR_COLORS, SURFACE, ON_SURFACE, ON_SURFACE_VARIANT,
    OUTLINE_VARIANT, chip_style,
)

_call_log_dir: Path = Path("data/plugins/com.shinsekai.chat_phone")


def set_call_log_dir(d: Path) -> None:
    global _call_log_dir
    _call_log_dir = d


def _call_log_path() -> Path:
    p = _call_log_dir / "call_log.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


class PhoneApp(QWidget):
    on_back = Signal()
    on_call = Signal(str)

    def __init__(self, contacts: list[str], parent=None):
        super().__init__(parent)
        self._contacts = contacts
        self._tab = "recents"
        self._dial_text = ""
        self._dial_label: QLabel | None = None
        self._call_log: list[dict] = []
        self._chip_btns: dict[str, QPushButton] = {}
        self._load_log()
        self._setup_ui()
        self._show_content()

    def refresh_contacts(self, contacts):
        self._contacts = list(contacts)
        if self._tab != "dial":
            self._show_content()

    # ── call log API ──

    def log_call(self, name: str, duration: int, call_type: str = "outgoing"):
        """Record a completed call."""
        entry = {
            "name": name, "duration": duration,
            "timestamp": time.time(), "type": call_type,
        }
        self._call_log.insert(0, entry)
        self._save_log()
        from pathlib import Path
        p = _call_log_path()
        Path("data/plugins/com.shinsekai.chat_phone/debug_log.txt").write_text(
            f"LOGGED: {entry} to={p} exists={p.is_file()}", encoding="utf-8")
        if self._tab == "recents":
            self._show_content()

    def _load_log(self):
        try:
            p = _call_log_path()
            if p.is_file():
                self._call_log = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            self._call_log = []

    def _save_log(self):
        try:
            p = _call_log_path()
            p.write_text(json.dumps(self._call_log, ensure_ascii=False, indent=2),
                         encoding="utf-8")
        except Exception:
            pass

    # ── UI ──

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(_top_bar("通话", self.on_back.emit))

        chips = QWidget()
        chips.setStyleSheet(f"background: {SURFACE}; padding: 4px;")
        cl = QHBoxLayout(chips)
        cl.setContentsMargins(12, 4, 12, 4)
        cl.setSpacing(8)
        for tid, label in [("recents", "最近"), ("contacts", "联系人"), ("dial", "拨号")]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(tid == self._tab)
            btn.setStyleSheet(chip_style(tid == self._tab))
            btn.clicked.connect(self._make_tab(tid))
            self._chip_btns[tid] = btn
            cl.addWidget(btn)
        cl.addStretch()
        layout.addWidget(chips)

        self._stack = QVBoxLayout()
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.setSpacing(0)
        layout.addLayout(self._stack, 1)

    def _make_tab(self, tid: str):
        def switch():
            self._tab = tid
            for t, btn in self._chip_btns.items():
                btn.setStyleSheet(chip_style(t == tid))
            self._show_content()
        return switch

    def _show_content(self):
        if self._tab == "dial":
            self._show_dial()
        elif self._tab == "recents":
            self._show_recents()
        else:
            self._show_contacts()

    # ── recents ──

    def _show_recents(self):
        _clear(self._stack)
        if not self._call_log:
            hint = QLabel("暂无通话记录")
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

        for entry in self._call_log:
            name = entry.get("name", "?")
            dur = entry.get("duration", 0)
            ts = entry.get("timestamp", 0)
            ttype = entry.get("type", "outgoing")
            icon = "↗" if ttype == "outgoing" else "↙"
            ts_str = _fmt_ts(ts)

            row = QWidget()
            row.setFixedHeight(52)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(16, 6, 12, 6)
            rl.setSpacing(10)
            av = _avatar(name, 38)
            rl.addWidget(av)
            tv = QVBoxLayout()
            tv.setSpacing(2)
            nl = QLabel(f"{icon} {name}")
            nl.setStyleSheet(f"color: {ON_SURFACE}; font-size: 14px;")
            dl = QLabel(_fmt_dur(dur) if dur else "未接通")
            dl.setStyleSheet(f"color: {ON_SURFACE_VARIANT}; font-size: 11px;")
            tv.addWidget(nl)
            tv.addWidget(dl)
            rl.addLayout(tv, 1)

            tl = QLabel(ts_str)
            tl.setStyleSheet(f"color: {ON_SURFACE_VARIANT}; font-size: 11px;")
            rl.addWidget(tl)

            cb = QPushButton("\U0001F4DE")
            cb.setFixedSize(34, 34)
            cb.setStyleSheet(
                "QPushButton { background: #34C759; color: white; border-radius: 17px;"
                " font-size: 14px; border: none; }"
            )
            cb.clicked.connect(lambda n=name: self.on_call.emit(n))
            rl.addWidget(cb)

            cl.addWidget(row)

        cl.addStretch()
        scroll.setWidget(c)
        self._stack.addWidget(scroll, 1)

    # ── contacts ──

    def _show_contacts(self):
        _clear(self._stack)
        if not self._contacts:
            hint = QLabel("暂无联系人")
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
        for name in sorted(self._contacts):
            row = QWidget()
            row.setFixedHeight(52)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(16, 6, 12, 6)
            rl.setSpacing(12)
            rl.addWidget(_avatar(name, 38))
            nl = QLabel(name)
            nl.setStyleSheet(f"color: {ON_SURFACE}; font-size: 14px;")
            rl.addWidget(nl, 1)
            cb = QPushButton("\U0001F4DE")
            cb.setFixedSize(38, 38)
            cb.setStyleSheet(
                "QPushButton { background: #34C759; color: white; border-radius: 19px;"
                " font-size: 16px; border: none; }"
            )
            cb.clicked.connect(lambda n=name: self.on_call.emit(n))
            rl.addWidget(cb)
            cl.addWidget(row)
        cl.addStretch()
        scroll.setWidget(c)
        self._stack.addWidget(scroll, 1)

    # ── dial ──

    def _show_dial(self):
        _clear(self._stack)
        self._dial_text = ""
        dw = QWidget()
        dw.setStyleSheet(f"background: {SURFACE};")
        dl = QVBoxLayout(dw)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(0)

        self._dial_label = QLabel("")
        self._dial_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._dial_label.setFixedHeight(56)
        self._dial_label.setStyleSheet(
            f"color: {ON_SURFACE}; font-size: 30px; font-weight: 300;")
        dl.addWidget(self._dial_label)

        grid = QGridLayout()
        grid.setContentsMargins(24, 12, 24, 12)
        grid.setSpacing(6)
        keys = [
            ("1",""),("2","ABC"),("3","DEF"),
            ("4","GHI"),("5","JKL"),("6","MNO"),
            ("7","PQRS"),("8","TUV"),("9","WXYZ"),
            ("*",""),("0","+"),("#",""),
        ]
        for i, (num, _sub) in enumerate(keys):
            btn = QPushButton(num)
            btn.setFixedSize(60, 60)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {OUTLINE_VARIANT}; color: {ON_SURFACE};
                    border-radius: 30px; font-size: 22px; font-weight: 300; border: none;
                }}
                QPushButton:pressed {{ background: #E0D5D5; }}
            """)
            btn.clicked.connect(self._make_dial(num))
            grid.addWidget(btn, i // 3, i % 3, Qt.AlignmentFlag.AlignCenter)

        call_btn = QPushButton("\U0001F4DE")
        call_btn.setFixedSize(60, 60)
        call_btn.setStyleSheet(
            "QPushButton { background: #34C759; color: white; border-radius: 30px;"
            " font-size: 26px; border: none; }"
        )
        call_btn.clicked.connect(self._on_dial_call)
        del_btn = QPushButton("⌫")
        del_btn.setFixedSize(60, 60)
        del_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {ON_SURFACE_VARIANT};"
            f" border-radius: 30px; font-size: 18px; border: none; }}"
        )
        del_btn.clicked.connect(self._on_del)
        brow = QHBoxLayout()
        brow.addStretch()
        brow.addWidget(del_btn)
        brow.addStretch()
        brow.addWidget(call_btn)
        brow.addStretch()

        dl.addLayout(grid)
        dl.addStretch()
        dl.addLayout(brow)
        dl.addSpacing(16)
        self._stack.addWidget(dw, 1)

    def _make_dial(self, d: str):
        def fn():
            self._dial_text += d
            if self._dial_label:
                self._dial_label.setText(self._dial_text)
        return fn

    def _on_del(self):
        self._dial_text = self._dial_text[:-1]
        if self._dial_label:
            self._dial_label.setText(self._dial_text)

    def _on_dial_call(self):
        if self._contacts and self._contacts[0]:
            self.on_call.emit(self._contacts[0])


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
    from plugins.chat_phone.avatar_manager import get_avatar_for_character
    av = QLabel()
    av.setFixedSize(size, size)
    av.setAlignment(Qt.AlignmentFlag.AlignCenter)
    pix = get_avatar_for_character(name)
    if pix is not None and not pix.isNull():
        from PySide6.QtGui import QPixmap, QPainter, QBrush, QColor
        rounded = QPixmap(size, size)
        rounded.fill(Qt.GlobalColor.transparent)
        p = QPainter(rounded)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(pix.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                     Qt.TransformationMode.SmoothTransformation)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, size, size, size//4, size//4)
        p.end()
        av.setPixmap(rounded)
    else:
        av.setText(name[0] if name else "?")
        c = AVATAR_COLORS[hash(name) % len(AVATAR_COLORS)]
        av.setStyleSheet(f"background: {c}; border-radius: {size//2}px; color: white; font-size: {size//2}px; font-weight: bold;")
    return av


def _clear(layout):
    while layout.count():
        w = layout.takeAt(0).widget()
        if w: w.deleteLater()


def _fmt_dur(sec: int) -> str:
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _fmt_ts(ts: float) -> str:
    if ts <= 0:
        return ""
    t = time.localtime(ts)
    now = time.time()
    if now - ts < 86400 and t.tm_mday == time.localtime(now).tm_mday:
        return time.strftime("%H:%M", t)
    return time.strftime("%m/%d", t)
