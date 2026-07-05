"""Settings app — DND mode + wallpaper."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)
from plugins.chat_phone.styles import get_surface, get_accent, _darken, ON_SURFACE, ON_SURFACE_VARIANT, OUTLINE_VARIANT

_CONFIG = Path("data/plugins/com.shinsekai.chat_phone/phone_settings.json")


def load_settings() -> dict:
    try:
        if _CONFIG.is_file():
            data = json.loads(_CONFIG.read_text(encoding="utf-8"))
            # Migrate legacy "monitor: bool" → "hacked_characters: list"
            if "monitor" in data and "hacked_characters" not in data:
                data["hacked_characters"] = []
                del data["monitor"]
                save_settings(data)
            return data
    except Exception:
        pass
    return {"dnd": False, "hacked_characters": [], "theme": "#FFFAFA"}


def save_settings(data: dict) -> None:
    _CONFIG.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def is_dnd() -> bool:
    return load_settings().get("dnd", False)


def get_hacked_characters() -> list[str]:
    """Return list of character names whose phones are currently bugged."""
    return load_settings().get("hacked_characters", [])


def add_hacked_character(name: str) -> bool:
    """Bug a character's phone. Returns True if newly added."""
    s = load_settings()
    hacked = s.setdefault("hacked_characters", [])
    if name in hacked:
        return False
    hacked.append(name)
    save_settings(s)
    return True


def remove_hacked_character(name: str) -> bool:
    """Remove monitoring from a character's phone."""
    s = load_settings()
    hacked = s.get("hacked_characters", [])
    if name not in hacked:
        return False
    hacked.remove(name)
    s["hacked_characters"] = hacked
    save_settings(s)
    return True


def is_character_hacked(name: str) -> bool:
    """Check if a specific character's phone is being monitored."""
    return name in load_settings().get("hacked_characters", [])


def is_monitor() -> bool:
    """Legacy: True if any character is hacked. Kept for backward compat."""
    return len(load_settings().get("hacked_characters", [])) > 0


def is_yandere() -> bool:
    """Master kill switch for yandere easter egg."""
    return load_settings().get("yandere", False)


_YANDERE_KEYWORDS = ["病娇", "yandere", "监禁", "偏执", "占有欲极强", "占有欲很强", "极端占有"]


def _get_character_setting(name: str) -> str:
    """Load a character's setting text from config. Returns '' on failure."""
    try:
        from config.config_manager import ConfigManager
        for c in ConfigManager().config.characters:
            if c.name == name:
                return (c.character_setting or "").lower()
    except Exception:
        pass
    return ""


def get_yandere_characters() -> list[str]:
    """Return list of characters that have yandere keywords in their settings.

    Respects the global yandere kill switch — returns empty list if disabled.
    """
    if not is_yandere():
        return []
    try:
        from config.config_manager import ConfigManager
        chars = [c.name for c in ConfigManager().config.characters]
        result = []
        for name in chars:
            setting = _get_character_setting(name)
            if any(kw in setting for kw in _YANDERE_KEYWORDS):
                result.append(name)
        return result
    except Exception:
        return []


def is_character_yandere(name: str) -> bool:
    """Check if a specific character has yandere traits AND the kill switch is on."""
    if not is_yandere():
        return False
    setting = _get_character_setting(name)
    return any(kw in setting for kw in _YANDERE_KEYWORDS)


def get_yandere_tampering() -> dict[str, bool]:
    """Return {character_name: True} for characters whose phone tampering has been
    established in the story. Once recorded, hangup block is active for them."""
    return load_settings().get("yandere_tampering", {})


def record_yandere_tampering(name: str) -> bool:
    """Record that a yandere character has tampered with the player's phone.
    Returns True if newly recorded."""
    s = load_settings()
    tampering = s.setdefault("yandere_tampering", {})
    if tampering.get(name):
        return False
    tampering[name] = True
    save_settings(s)
    return True


def is_yandere_tampering_active(name: str) -> bool:
    """Check if hangup block should be active for this yandere character."""
    if not is_character_yandere(name):
        return False
    return get_yandere_tampering().get(name, False)


def get_theme() -> str:
    return load_settings().get("theme", "#FFFAFA")


class SettingsApp(QWidget):
    on_back = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = load_settings()
        self.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)
        self._layout = layout

        # Top bar
        tb = QWidget(); tb.setFixedHeight(48); tb.setStyleSheet("background: transparent;")
        tl = QHBoxLayout(tb); tl.setContentsMargins(4, 0, 12, 0)
        back = QPushButton("←")
        back.setStyleSheet("QPushButton { background: transparent; color: #FFB3BA; border: none; font-size: 18px; padding: 6px 10px; font-weight: 600; }")
        back.clicked.connect(self.on_back.emit)
        t = QLabel("设置"); t.setStyleSheet(f"color: {ON_SURFACE}; font-size: 17px; font-weight: 500;")
        tl.addWidget(back); tl.addWidget(t, 1)
        layout.addWidget(tb)

        # ── Do Not Disturb ──
        dnd_row = QWidget()
        dnd_row.setFixedHeight(56)
        dnd_row.setStyleSheet(f"background: {get_surface()}; border-bottom: 1px solid {OUTLINE_VARIANT};")
        dr = QHBoxLayout(dnd_row); dr.setContentsMargins(16, 8, 16, 8)
        dnd_label = QLabel("勿扰模式")
        dnd_label.setStyleSheet(f"color: {ON_SURFACE}; font-size: 15px; font-weight: 500;")
        dnd_desc = QLabel("屏蔽来电和短信通知")
        dnd_desc.setStyleSheet(f"color: {ON_SURFACE_VARIANT}; font-size: 11px;")
        dnd_text = QVBoxLayout(); dnd_text.setSpacing(2)
        dnd_text.addWidget(dnd_label); dnd_text.addWidget(dnd_desc)
        self._dnd_btn = QPushButton("关" if self._settings.get("dnd") else "开")
        self._dnd_btn.setFixedSize(52, 28)
        self._dnd_btn.setStyleSheet(
            f"QPushButton {{ background: {get_surface()}; color: #3C2A2A; border-radius: 14px; font-size: 11px; font-weight: 600; border: none; }}"
            f"QPushButton:checked {{ background: {get_accent()}; color: white; }}"
        )
        self._dnd_btn.setCheckable(True)
        self._dnd_btn.setChecked(self._settings.get("dnd", False))
        self._dnd_btn.clicked.connect(self._toggle_dnd)
        dr.addLayout(dnd_text, 1); dr.addWidget(self._dnd_btn)
        layout.addWidget(dnd_row)

        # ── Hacker Mode: per-character phone monitoring ──
        from plugins.chat_phone.avatar_manager import get_all_character_names
        self._all_chars = get_all_character_names()

        hack_header = QWidget()
        hack_header.setFixedHeight(56)
        hack_header.setStyleSheet(f"background: {get_surface()}; border-bottom: 1px solid {OUTLINE_VARIANT};")
        hh = QHBoxLayout(hack_header); hh.setContentsMargins(16, 8, 16, 8)
        hack_label = QLabel("❤黑客模式❤")
        hack_label.setStyleSheet(f"color: {ON_SURFACE}; font-size: 15px; font-weight: 500;")
        hack_desc = QLabel("在角色手机上安装监控程序后，可查看其私密动态")
        hack_desc.setStyleSheet(f"color: {ON_SURFACE_VARIANT}; font-size: 11px;")
        hack_text = QVBoxLayout(); hack_text.setSpacing(2)
        hack_text.addWidget(hack_label); hack_text.addWidget(hack_desc)
        hh.addLayout(hack_text, 1)
        layout.addWidget(hack_header)

        # ── Add character selector ──
        add_row = QWidget()
        add_row.setStyleSheet(f"background: {get_surface()}; border-bottom: 1px solid {OUTLINE_VARIANT};")
        ar = QHBoxLayout(add_row); ar.setContentsMargins(16, 6, 16, 6); ar.setSpacing(8)
        self._hack_combo = QComboBox()
        self._hack_combo.setStyleSheet(
            f"QComboBox {{ background: {OUTLINE_VARIANT}; color: {ON_SURFACE};"
            " border: none; border-radius: 8px; padding: 4px 8px; font-size: 13px; }"
            "QComboBox::drop-down { border: none; }"
        )
        self._hack_combo.setMinimumWidth(100)
        self._refresh_hack_combo()
        add_btn = QPushButton("添加监控")
        add_btn.setStyleSheet(
            f"QPushButton {{ background: {get_accent()}; color: white; border-radius: 10px;"
            " padding: 4px 12px; font-size: 12px; font-weight: 600; border: none; }}"
        )
        add_btn.clicked.connect(self._add_hacked_char)
        ar.addWidget(QLabel("目标:"))
        ar.addWidget(self._hack_combo, 1)
        ar.addWidget(add_btn)
        layout.addWidget(add_row)

        # ── Hacked character list ──
        self._hack_list_widget = QWidget()
        self._hack_list_widget.setStyleSheet(f"background: {get_surface()}; border-bottom: 1px solid {OUTLINE_VARIANT};")
        self._hack_list_layout = QVBoxLayout(self._hack_list_widget)
        self._hack_list_layout.setContentsMargins(0, 0, 0, 0)
        self._hack_list_layout.setSpacing(0)
        self._refresh_hack_list()
        layout.addWidget(self._hack_list_widget)

        # ── Yandere Easter Egg ──
        yan_row = QWidget()
        yan_row.setFixedHeight(56)
        yan_row.setStyleSheet(f"background: {get_surface()}; border-bottom: 1px solid {OUTLINE_VARIANT};")
        yr = QHBoxLayout(yan_row); yr.setContentsMargins(16, 8, 16, 8)
        yan_label = QLabel("❤病娇彩蛋❤")
        yan_label.setStyleSheet(f"color: {ON_SURFACE}; font-size: 15px; font-weight: 500;")
        yan_desc = QLabel("角色偷看手机/浏览器/阻止挂断等")
        yan_desc.setStyleSheet(f"color: {ON_SURFACE_VARIANT}; font-size: 11px;")
        yan_text = QVBoxLayout(); yan_text.setSpacing(2)
        yan_text.addWidget(yan_label); yan_text.addWidget(yan_desc)
        self._yan_btn = QPushButton("关" if self._settings.get("yandere") else "开")
        self._yan_btn.setFixedSize(52, 28)
        self._yan_btn.setStyleSheet(
            f"QPushButton {{ background: {get_surface()}; color: #3C2A2A; border-radius: 14px; font-size: 11px; font-weight: 600; border: none; }}"
            f"QPushButton:checked {{ background: {get_accent()}; color: white; }}"
        )
        self._yan_btn.setCheckable(True)
        self._yan_btn.setChecked(self._settings.get("yandere", False))
        self._yan_btn.clicked.connect(self._toggle_yandere)
        yr.addLayout(yan_text, 1); yr.addWidget(self._yan_btn)
        layout.addWidget(yan_row)

        # ── Hacker Mode: per-contact frequency ──
        hack_row = QWidget()
        hack_row.setFixedHeight(56)
        hack_row.setStyleSheet(f"background: {get_surface()}; border-bottom: 1px solid {OUTLINE_VARIANT};")
        hr = QHBoxLayout(hack_row); hr.setContentsMargins(16, 8, 16, 8)
        hack_label = QLabel("❤管理员模式❤")
        hack_label.setStyleSheet(f"color: {ON_SURFACE}; font-size: 15px; font-weight: 500;")
        hack_desc = QLabel("配置每个角色的主动联系频率")
        hack_desc.setStyleSheet(f"color: {ON_SURFACE_VARIANT}; font-size: 11px;")
        hack_text = QVBoxLayout(); hack_text.setSpacing(2)
        hack_text.addWidget(hack_label); hack_text.addWidget(hack_desc)
        hack_btn = QPushButton("进入")
        hack_btn.setStyleSheet(f"QPushButton {{ background: {get_accent()}; color: white; border-radius: 12px; padding: 4px 14px; font-size: 12px; font-weight: 600; border: none; }}")
        hack_btn.clicked.connect(self._open_hacker_mode)
        hr.addLayout(hack_text, 1); hr.addWidget(hack_btn)
        layout.addWidget(hack_row)

        layout.addStretch()

    def _toggle_dnd(self):
        self._settings["dnd"] = self._dnd_btn.isChecked()
        save_settings(self._settings)
        self._dnd_btn.setText("开" if self._settings["dnd"] else "关")
        from plugins.chat_phone.home_screen import _set_dnd_visible
        _set_dnd_visible(self._settings["dnd"])

    def _open_hacker_mode(self):
        from plugins.chat_phone.freq_config_ui import FreqConfigWidget
        self._hacker_widget = FreqConfigWidget()
        self._hacker_widget.on_back.connect(self._close_hacker_mode)
        # Replace content with hacker widget
        for i in reversed(range(self._layout.count())):
            w = self._layout.itemAt(i).widget()
            if w: w.hide()
        self._layout.addWidget(self._hacker_widget, 1)

    def _close_hacker_mode(self):
        if hasattr(self, '_hacker_widget'):
            self._hacker_widget.hide()
            self._hacker_widget.deleteLater()
        # Show all hidden widgets
        for i in range(self._layout.count()):
            w = self._layout.itemAt(i).widget()
            if w: w.show()

    def _toggle_yandere(self):
        self._settings["yandere"] = self._yan_btn.isChecked()
        save_settings(self._settings)
        self._yan_btn.setText("开" if self._settings["yandere"] else "关")

    def _toggle_monitor(self):
        """Deprecated — kept for reference, no longer used."""
        pass

    def _refresh_hack_combo(self):
        """Refresh the character dropdown, excluding already-hacked chars."""
        self._hack_combo.clear()
        hacked = get_hacked_characters()
        available = [c for c in self._all_chars if c not in hacked]
        if available:
            self._hack_combo.addItems(available)
        else:
            self._hack_combo.addItem("(所有角色已监控)")
            self._hack_combo.setEnabled(False)

    def _add_hacked_char(self):
        name = self._hack_combo.currentText().strip()
        if not name or name.startswith("("):
            return
        if add_hacked_character(name):
            self._refresh_hack_combo()
            self._refresh_hack_list()
            # Re-enable combo if it was disabled
            self._hack_combo.setEnabled(True)

    def _remove_hacked_char(self, name: str):
        remove_hacked_character(name)
        self._refresh_hack_combo()
        self._refresh_hack_list()
        self._hack_combo.setEnabled(True)

    def _refresh_hack_list(self):
        """Rebuild the hacked character list widgets."""
        # Clear existing rows
        while self._hack_list_layout.count():
            item = self._hack_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        hacked = get_hacked_characters()
        if not hacked:
            hint = QLabel("  尚未监控任何角色")
            hint.setStyleSheet(f"color: {ON_SURFACE_VARIANT}; font-size: 12px; padding: 8px 16px;")
            self._hack_list_layout.addWidget(hint)
            return
        for name in hacked:
            row = QWidget()
            row.setFixedHeight(40)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(16, 4, 12, 4)
            rl.setSpacing(8)
            chip = QLabel(f"  🔴 {name}  ")
            chip.setStyleSheet(
                f"background: {get_accent()}; color: white; border-radius: 10px;"
                " font-size: 13px; font-weight: 500; padding: 3px 8px;")
            rl.addWidget(chip)
            rl.addStretch()
            del_btn = QPushButton("移除")
            del_btn.setStyleSheet(
                "QPushButton { background: transparent; color: #FF3B30; border: none;"
                " font-size: 12px; font-weight: 600; padding: 4px 8px; }"
            )
            del_btn.clicked.connect(lambda checked, n=name: self._remove_hacked_char(n))
            rl.addWidget(del_btn)
            self._hack_list_layout.addWidget(row)

    def _set_theme(self, color: str):
        self._settings["theme"] = color
        save_settings(self._settings)
        from plugins.chat_phone.styles import notify_theme_change
        notify_theme_change(color)
