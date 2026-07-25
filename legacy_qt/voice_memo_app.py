"""Voice Memos — record by merging TTS audio from cache/audio."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)
from plugins.shinsekai_chat_phone.styles import (
    get_surface, ON_SURFACE, ON_SURFACE_VARIANT,
)

AUDIO_CACHE = Path("cache/audio")


class VoiceMemosApp(QWidget):
    """Record: captures TTS-generated audio files and merges them."""

    on_back = Signal()

    def __init__(self, data_dir: Path, parent=None):
        super().__init__(parent)
        self._dir = Path(data_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._recording = False
        self._elapsed = 0
        self._timer: QTimer | None = None
        self._captured: list[Path] = []
        self._watch_timer: QTimer | None = None
        self._known_files: set[str] = set()
        self._memos: list[dict] = []
        self._load()
        self._setup_ui()
        self._show()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(_top_bar("语音备忘录", self.on_back.emit))
        self._stack = QVBoxLayout()
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.setSpacing(0)
        layout.addLayout(self._stack, 1)

    def _show(self):
        _clear(self._stack)

        # Info text
        info = QLabel("录音时会捕获 TTS 合成语音\n"
                      f"从 {AUDIO_CACHE} 读取音频文件\n"
                      "点击停止后自动合并为一条录音")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {ON_SURFACE_VARIANT}; font-size: 12px; padding: 16px;")
        self._stack.addWidget(info)

        # Memo list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        c = QWidget()
        c.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(c)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        for i, m in enumerate(self._memos):
            row = QWidget()
            row.setFixedHeight(48)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(16, 8, 12, 8)
            rl.setSpacing(8)
            nm = QLabel(m.get("title", "录音"))
            nm.setStyleSheet(f"color: {ON_SURFACE}; font-size: 14px;")
            dur = QLabel(_fmt_dur(m.get("duration", 0)))
            dur.setStyleSheet(f"color: {ON_SURFACE_VARIANT}; font-size: 12px;")
            files_label = QLabel(f"{m.get('file_count', 0)} 个文件")
            files_label.setStyleSheet(f"color: {ON_SURFACE_VARIANT}; font-size: 11px;")
            rl.addWidget(nm, 1)
            rl.addWidget(files_label)
            rl.addWidget(dur)
            db = QPushButton("🗑")
            db.setFixedSize(28, 28)
            db.setStyleSheet("background: transparent; border: none; font-size: 14px;")
            db.clicked.connect(self._make_del(i))
            rl.addWidget(db)
            cl.addWidget(row)
        cl.addStretch()
        scroll.setWidget(c)
        self._stack.addWidget(scroll, 1)

        # Record FAB
        fw = QWidget()
        fw.setStyleSheet("background: transparent;")
        fw.setFixedHeight(64)
        fl = QHBoxLayout(fw)
        fl.setContentsMargins(0, 0, 0, 0)
        self._rec_btn = QPushButton("🔴  开始录音")
        self._rec_btn.setStyleSheet(
            "QPushButton { background: #FFDAC1; color: #5C3A1A; border-radius: 20px;"
            " font-size: 13px; font-weight: 600; padding: 10px 20px; border: none; }"
        )
        self._rec_btn.clicked.connect(self._toggle)
        fl.addStretch()
        fl.addWidget(self._rec_btn)
        fl.addStretch()
        self._stack.addWidget(fw)

    def _toggle(self):
        if self._recording:
            self._stop()
        else:
            self._start()

    def _start(self):
        self._recording = True
        self._elapsed = 0
        self._captured = []
        # Snapshot existing audio files
        if AUDIO_CACHE.is_dir():
            self._known_files = set(str(p) for p in AUDIO_CACHE.iterdir()
                                    if p.suffix in ('.wav', '.mp3', '.ogg'))

        self._rec_btn.setText("⏹  停止录音")
        self._rec_btn.setStyleSheet(
            "QPushButton { background: #FFB3BA; color: white; border-radius: 20px;"
            " font-size: 13px; font-weight: 600; padding: 10px 20px; border: none; }"
        )
        # Timer for duration
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        # Watch for new audio files
        self._watch_timer = QTimer(self)
        self._watch_timer.timeout.connect(self._scan_new_files)
        self._watch_timer.start(2000)

    def _stop(self):
        self._recording = False
        if self._timer:
            self._timer.stop()
            self._timer = None
        if self._watch_timer:
            self._watch_timer.stop()
            self._watch_timer = None

        # Final scan
        self._scan_new_files()

        # Merge captured files
        merged_path = None
        if self._captured:
            merged_path = self._merge_audio()

        memo = {
            "title": time.strftime("%m/%d %H:%M"),
            "duration": self._elapsed,
            "timestamp": time.time(),
            "file_count": len(self._captured),
            "files": [str(p) for p in self._captured],
            "merged": str(merged_path) if merged_path else None,
        }
        self._memos.insert(0, memo)
        self._save()

        self._rec_btn.setText("🔴  开始录音")
        self._rec_btn.setStyleSheet(
            "QPushButton { background: #FFDAC1; color: #5C3A1A; border-radius: 20px;"
            " font-size: 13px; font-weight: 600; padding: 10px 20px; border: none; }"
        )
        self._show()

    def _scan_new_files(self):
        if not AUDIO_CACHE.is_dir():
            return
        for p in AUDIO_CACHE.iterdir():
            if p.suffix not in ('.wav', '.mp3', '.ogg'):
                continue
            sp = str(p)
            if sp not in self._known_files:
                self._known_files.add(sp)
                self._captured.append(p)

    def _merge_audio(self) -> Path | None:
        """Merge captured audio files into one .wav using wave/stdlib if possible."""
        if not self._captured:
            return None
        out_path = self._dir / f"memo_{int(time.time())}.wav"
        try:
            # Try pydub first
            try:
                from pydub import AudioSegment
                combined = AudioSegment.empty()
                for fp in self._captured:
                    try:
                        seg = AudioSegment.from_file(str(fp))
                        combined += seg
                    except Exception:
                        pass
                if len(combined) > 0:
                    combined.export(str(out_path), format="wav")
                    return out_path
            except ImportError:
                pass

            # Fallback: just copy the first file if only one
            if len(self._captured) == 1:
                import shutil
                shutil.copy2(str(self._captured[0]), str(out_path))
                return out_path

            # Fallback: concatenate wav files
            import wave
            import io
            frames = []
            params = None
            for fp in self._captured:
                try:
                    with wave.open(str(fp), 'rb') as wf:
                        if params is None:
                            params = wf.getparams()
                        frames.append(wf.readframes(wf.getnframes()))
                except Exception:
                    pass
            if params and frames:
                with wave.open(str(out_path), 'wb') as wf:
                    wf.setparams(params)
                    for frm in frames:
                        wf.writeframes(frm)
                return out_path
        except Exception:
            pass
        return None

    def _tick(self):
        self._elapsed += 1

    def _make_del(self, i: int):
        def fn():
            del self._memos[i]
            self._save()
            self._show()
        return fn

    def _save(self):
        try:
            (self._dir / "memos.json").write_text(
                json.dumps(self._memos, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _load(self):
        try:
            p = self._dir / "memos.json"
            if p.is_file():
                self._memos = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            self._memos = []


def _top_bar(title: str, on_back) -> QWidget:
    w = QWidget()
    w.setFixedHeight(48)
    w.setStyleSheet("background: transparent;")
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


def _clear(layout):
    while layout.count():
        w = layout.takeAt(0).widget()
        if w: w.deleteLater()


def _fmt_dur(sec):
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"
