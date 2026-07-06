"""Music app — album art, media controls, listen-together."""

from __future__ import annotations

import json, os, subprocess, time as _time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)
from plugins.shinsekai_chat_phone.styles import ON_SURFACE, ON_SURFACE_VARIANT

_CONFIG = Path("data/plugins/com.shinsekai.chat_phone/music_config.json")
_ASSETS = Path(__file__).parent / "assets"


def get_player_path() -> str:
    try:
        if _CONFIG.is_file():
            return json.loads(_CONFIG.read_text(encoding="utf-8")).get("exe_path", "")
    except Exception: pass
    return ""

def set_player_path(path: str) -> None:
    _CONFIG.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG.write_text(json.dumps({"exe_path": path}, ensure_ascii=False, indent=2), encoding="utf-8")


class MusicApp(QWidget):
    on_back = Signal()
    _bgm_saved: float = 0.5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._listen_active = False
        self._submit_cb: object = None
        self._contact_store: object = None
        self.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)

        # Top bar
        tb = QWidget(); tb.setFixedHeight(48); tb.setStyleSheet("background: transparent;")
        tl = QHBoxLayout(tb); tl.setContentsMargins(4, 0, 12, 0)
        back = QPushButton("←")
        back.setStyleSheet("QPushButton { background: transparent; color: #FFB3BA; border: none; font-size: 18px; padding: 6px 10px; font-weight: 600; }")
        back.clicked.connect(self.on_back.emit)
        t = QLabel("音乐"); t.setStyleSheet(f"color: {ON_SURFACE}; font-size: 17px; font-weight: 500;")
        tl.addWidget(back); tl.addWidget(t, 1)
        layout.addWidget(tb)
        layout.addSpacing(12)

        # ── Album Art ──
        self._album = QLabel()
        self._album.setFixedSize(200, 200)
        self._album.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = QPixmap(str(_ASSETS / "album_art.png"))
        if not pix.isNull():
            self._album.setPixmap(pix.scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self._album.setStyleSheet("background: transparent; border-radius: 16px;")
        layout.addWidget(self._album, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(12)

        # ── Song Name ──
        self._song_label = QLabel("未在播放")
        self._song_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._song_label.setStyleSheet(f"color: {ON_SURFACE}; font-size: 14px; font-weight: 500; padding: 0 20px;")
        self._song_label.setWordWrap(True)
        layout.addWidget(self._song_label)
        layout.addSpacing(16)

        # ── Controls: prev | play | next ──
        ctrl = QWidget(); ctrl.setStyleSheet("background: transparent;")
        cl = QHBoxLayout(ctrl); cl.setContentsMargins(0, 0, 0, 0); cl.setSpacing(20)
        cl.addStretch()

        prev_btn = self._icon_btn("prev.png", "上一首")
        prev_btn.clicked.connect(self._media_prev)
        cl.addWidget(prev_btn)

        self._play_btn = self._icon_btn("play_pause.png", "播放/暂停")
        self._play_btn.clicked.connect(self._media_play_pause)
        cl.addWidget(self._play_btn)

        next_btn = self._icon_btn("next.png", "下一首")
        next_btn.clicked.connect(self._media_next)
        cl.addWidget(next_btn)

        cl.addStretch()
        layout.addWidget(ctrl)
        layout.addStretch()

        # ── Listen Together ──
        lt_row = QWidget(); lt_row.setStyleSheet("background: transparent;")
        ltr = QHBoxLayout(lt_row); ltr.setContentsMargins(16, 4, 16, 8); ltr.setSpacing(8)
        self._lt_btn = QPushButton()
        self._lt_btn.setFixedSize(56, 56)
        pix2 = QPixmap(str(_ASSETS / "listen_together.png"))
        if not pix2.isNull():
            self._lt_btn.setIcon(pix2.scaled(44, 44, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            self._lt_btn.setText("🎧")
        self._lt_btn.setStyleSheet("QPushButton { background: transparent; border: none; font-size: 32px; }")
        self._lt_btn.clicked.connect(self._toggle_listen)
        self._lt_label = QLabel("一起听")
        self._lt_label.setStyleSheet(f"color: {ON_SURFACE_VARIANT}; font-size: 12px;")
        ltr.addWidget(self._lt_btn)
        ltr.addWidget(self._lt_label)
        ltr.addStretch()
        layout.addWidget(lt_row)
        layout.addSpacing(4)

        # Only refresh when visible, stop when hidden
        self._song_timer = QTimer(self)
        self._song_timer.timeout.connect(self._refresh_song)

    def set_submit_callback(self, cb): self._submit_cb = cb
    def set_contact_store(self, cs): self._contact_store = cs

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_song()
        self._song_timer.start(5000)

    def hideEvent(self, event):
        super().hideEvent(event)
        self._song_timer.stop()

    # ── Media controls ──

    def _icon_btn(self, filename: str, tooltip: str) -> QPushButton:
        btn = QPushButton()
        btn.setFixedSize(56, 56); btn.setToolTip(tooltip)
        pix = QPixmap(str(_ASSETS / filename))
        if not pix.isNull():
            btn.setIcon(pix.scaled(44, 44, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        btn.setStyleSheet("QPushButton { background: transparent; border: none; }")
        return btn

    def _send_key(self, vk: int):
        try:
            import ctypes
            ctypes.windll.user32.keybd_event(vk, 0, 0x0001, 0)
            ctypes.windll.user32.keybd_event(vk, 0, 0x0001 | 0x0002, 0)
        except Exception: pass

    def _media_play_pause(self):
        self._lower_bgm()
        self._send_key(0xB3)  # VK_MEDIA_PLAY_PAUSE

    def _media_prev(self): self._send_key(0xB1)
    def _media_next(self): self._send_key(0xB0)

    # ── BGM ──

    @classmethod
    def _lower_bgm(cls):
        try:
            import pygame.mixer
            cls._bgm_saved = pygame.mixer.music.get_volume()
            pygame.mixer.music.set_volume(0.01)
        except Exception: pass

    @classmethod
    def _restore_bgm(cls):
        try:
            import pygame.mixer
            pygame.mixer.music.set_volume(cls._bgm_saved)
        except Exception: pass

    # ── Listen Together ──

    def _toggle_listen(self):
        self._listen_active = not self._listen_active
        if self._listen_active:
            self._lower_bgm()
        else:
            self._restore_bgm()
        # Animate
        anim = QPropertyAnimation(self._lt_btn, b"pos")
        anim.setDuration(300); anim.setEasingCurve(QEasingCurve.Type.OutBounce)
        pos = self._lt_btn.pos()
        if self._listen_active:
            anim.setStartValue(pos); anim.setEndValue(pos.__class__(0, -8))
            self._lt_label.setText("一起听 ●")
            chars = self._contact_store.get_contacts() if self._contact_store else []
            char = chars[0] if chars else "TA"
            song = self._get_current_song()
            if song != "未知歌曲":
                prompt = f"[一起听] 玩家正在和{char}一起听《{song}》。请以{char}的身份对这首歌做出简短评价，一句话。"
            else:
                prompt = f"[一起听] 玩家打开了一起听功能。请以{char}的身份说一句邀请听歌的话。"
            if self._submit_cb: self._submit_cb(prompt)
        else:
            anim.setStartValue(pos.__class__(0, -8)); anim.setEndValue(pos)
            self._lt_label.setText("一起听")
        anim.start()

    # ── Song detection ──

    def _refresh_song(self):
        song = self._get_current_song()
        if song != "未知歌曲":
            self._song_label.setText(song)

    def _get_current_song(self) -> str:
        title = self._read_window_title()
        if title:
            for s in [" - NetEase Cloud Music", " - 网易云音乐", " 网易云音乐",
                       " - QQMusic", " - QQ音乐", " - Spotify"]:
                if s in title: title = title.replace(s, "").strip()
            return title
        return self._try_local_api() or "未知歌曲"

    def _read_window_title(self) -> str | None:
        """Read NetEase Cloud Music window title."""
        try:
            import ctypes; from ctypes import wintypes
            u = ctypes.windll.user32
            # Try FindWindow first (much faster than EnumWindows)
            hwnd = u.FindWindowW(None, None)
            # Search for cloudmusic window specifically
            titles = []
            def cb(h, _):
                if not u.IsWindowVisible(h): return True
                cls = ctypes.create_unicode_buffer(64)
                u.GetClassNameW(h, cls, 64)
                # NetEase uses "OrpheusBrowserHost" as class name
                if "orpheus" in cls.value.lower():
                    n = u.GetWindowTextLengthW(h)
                    if 5 < n < 200:
                        b = ctypes.create_unicode_buffer(n + 1)
                        u.GetWindowTextW(h, b, n + 1)
                        if b.value.strip(): titles.append(b.value)
                return True
            W = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            u.EnumWindows(W(cb), 0)
            return titles[0] if titles else None
        except Exception: return None

    def _try_local_api(self) -> str | None:
        try:
            import urllib.request, json
            for port in [8978, 4000, 10754]:
                try:
                    r = urllib.request.urlopen(f"http://127.0.0.1:{port}/player", timeout=1)
                    d = json.loads(r.read()); return d.get("title") or d.get("name")
                except Exception: pass
        except Exception: pass
        return None
