"""Qt settings page for per-character proactive frequency."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

_FREQ_FILE = Path("data/plugins/com.shinsekai.chat_phone/freq_config.json")


def load_freq_config() -> dict:
    try:
        if _FREQ_FILE.is_file():
            return json.loads(_FREQ_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"_enabled": True}


def save_freq_config(cfg: dict) -> None:
    _FREQ_FILE.parent.mkdir(parents=True, exist_ok=True)
    _FREQ_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


class FreqConfigWidget(QWidget):
    """Per-character frequency settings with individual save buttons."""
    on_back = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cfg = load_freq_config()
        self._spinners: dict[str, tuple] = {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12); layout.setSpacing(8)

        # Back button
        back = QPushButton("← 返回设置")
        back.setStyleSheet("QPushButton { background: transparent; color: #FFB3BA; border: none; font-size: 16px; padding: 6px 10px; font-weight: 600; }")
        back.clicked.connect(self.on_back.emit)
        layout.addWidget(back)

        # Global enable
        enable_row = QWidget()
        er = QHBoxLayout(enable_row); er.setContentsMargins(0, 0, 0, 0)
        self._enable_cb = QCheckBox("开启主动联系")
        self._enable_cb.setChecked(self._cfg.get("_enabled", True))
        self._enable_cb.toggled.connect(lambda v: self._save_enable(v))
        er.addWidget(self._enable_cb)
        er.addStretch()
        layout.addWidget(enable_row)

        # Per-character settings
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        sw = QWidget()
        self._sl = QVBoxLayout(sw)
        self._sl.setContentsMargins(0, 0, 0, 0); self._sl.setSpacing(4)

        try:
            from config.config_manager import ConfigManager
            chars = [c.name for c in ConfigManager().config.characters]
        except Exception:
            chars = []

        for name in chars:
            fc = self._cfg.get(name, {"sms": 0.1, "call": 0.03, "video_call": 0.01, "moments": 0.02})
            row = QWidget()
            rl = QHBoxLayout(row); rl.setContentsMargins(0, 2, 0, 2); rl.setSpacing(6)

            lbl = QLabel(name)
            lbl.setFixedWidth(80)
            lbl.setStyleSheet("font-size: 13px; font-weight: 500;")
            rl.addWidget(lbl)

            sms_label = QLabel("短信")
            sms_label.setStyleSheet("font-size: 11px; color: #888;")
            rl.addWidget(sms_label)
            sms_spin = QDoubleSpinBox()
            sms_spin.setRange(0, 1); sms_spin.setSingleStep(0.05)
            sms_spin.setValue(fc.get("sms", 0.1)); sms_spin.setFixedWidth(60)
            rl.addWidget(sms_spin)

            call_label = QLabel("来电")
            call_label.setStyleSheet("font-size: 11px; color: #888;")
            rl.addWidget(call_label)
            call_spin = QDoubleSpinBox()
            call_spin.setRange(0, 0.5); call_spin.setSingleStep(0.01)
            call_spin.setValue(fc.get("call", 0.03)); call_spin.setFixedWidth(60)
            rl.addWidget(call_spin)

            vid_label = QLabel("视频")
            vid_label.setStyleSheet("font-size: 11px; color: #888;")
            rl.addWidget(vid_label)
            vid_spin = QDoubleSpinBox()
            vid_spin.setRange(0, 0.3); vid_spin.setSingleStep(0.01)
            vid_spin.setValue(fc.get("video_call", 0.01)); vid_spin.setFixedWidth(60)
            rl.addWidget(vid_spin)

            mo_label = QLabel("朋友圈")
            mo_label.setStyleSheet("font-size: 11px; color: #888;")
            rl.addWidget(mo_label)
            mo_spin = QDoubleSpinBox()
            mo_spin.setRange(0, 0.3); mo_spin.setSingleStep(0.02)
            mo_spin.setValue(fc.get("moments", 0.02)); mo_spin.setFixedWidth(60)
            rl.addWidget(mo_spin)

            save_btn = QPushButton("保存")
            save_btn.setFixedWidth(50)
            save_btn.setStyleSheet(
                "QPushButton { background: #FFB3BA; color: white; border-radius: 8px;"
                " padding: 4px 8px; font-size: 11px; font-weight: 600; border: none; }"
            )
            save_btn.clicked.connect(
                lambda checked, n=name, s=sms_spin, c=call_spin, v=vid_spin, mo=mo_spin:
                    self._save_char(n, s, c, v, mo))
            rl.addWidget(save_btn)

            self._spinners[name] = (sms_spin, call_spin, vid_spin, mo_spin)
            self._sl.addWidget(row)

        self._sl.addStretch()
        scroll.setWidget(sw)
        layout.addWidget(scroll, 1)

        # Apply all button
        notify = QPushButton("全部应用")
        notify.setStyleSheet(
            "QPushButton { background: #C7CEEA; color: white; border-radius: 12px;"
            " padding: 8px 16px; font-size: 13px; font-weight: 600; border: none; }"
        )
        notify.clicked.connect(self._apply_all)
        layout.addWidget(notify)

    def _save_enable(self, enabled: bool):
        self._cfg["_enabled"] = enabled
        save_freq_config(self._cfg)

    def _save_char(self, name: str, sms_spin: QDoubleSpinBox, call_spin: QDoubleSpinBox,
                   vid_spin: QDoubleSpinBox | None = None, mo_spin: QDoubleSpinBox | None = None):
        entry = {"sms": sms_spin.value(), "call": call_spin.value()}
        if vid_spin is not None:
            entry["video_call"] = vid_spin.value()
        if mo_spin is not None:
            entry["moments"] = mo_spin.value()
        self._cfg[name] = entry
        save_freq_config(self._cfg)
        self._notify_monitor()

    @staticmethod
    def _notify_monitor():
        try:
            from plugins.shinsekai_chat_phone.plugin import get_monitor
            m = get_monitor()
            if m:
                m.set_frequency_config(load_freq_config())
        except Exception:
            pass

    def _apply_all(self):
        # Read all spinner values
        for name, spinners in self._spinners.items():
            entry = {"sms": spinners[0].value(), "call": spinners[1].value()}
            if len(spinners) > 2:
                entry["video_call"] = spinners[2].value()
            if len(spinners) > 3:
                entry["moments"] = spinners[3].value()
            self._cfg[name] = entry
        save_freq_config(self._cfg)
        try:
            from plugins.shinsekai_chat_phone.plugin import get_monitor
            m = get_monitor()
            if m:
                m.set_frequency_config(self._cfg)
        except Exception:
            pass
