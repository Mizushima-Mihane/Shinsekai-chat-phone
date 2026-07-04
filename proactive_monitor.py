"""Background timer that makes contacts proactively send messages or call."""

from __future__ import annotations

import random
import time

from PySide6.QtCore import QObject, QTimer, Signal

from plugins.chat_phone.contact_store import ContactStore
from plugins.chat_phone.message_store import MessageStore, MessageType


# ── message templates grouped by personality keywords ─────────────────

_TEMPLATES = {
    "cheerful": [
        "今天天气真好呀~",
        "在干嘛呢？",
        "想你了！",
        "嘿嘿，我刚看到一只超可爱的小猫！",
        "喂喂喂！在不在？",
        "今天心情特别好！",
    ],
    "cool": [
        "...",
        "没什么事",
        "嗯。",
        "...在吗",
        "有点无聊",
    ],
    "gentle": [
        "要注意休息哦~",
        "吃饭了吗？",
        "今天也要开开心心的~",
        "晚安，早点休息",
        "你还好吗？",
        "我在想你呢...",
    ],
    "default": [
        "在吗？",
        "你好呀",
        "最近怎么样？",
        "有空聊聊吗",
    ],
}


def _classify_personality(character_setting: str) -> str:
    """Heuristic: scan *character_setting* for keywords and return a template group."""
    if not character_setting:
        return "default"
    text = character_setting.lower()
    cheerful_kw = [
        "活泼", "开朗", "元气", "乐天", "阳光", "热情", "外向",
        "cheerful", "energetic", "lively", "outgoing",
    ]
    cool_kw = [
        "冷淡", "冷酷", "孤傲", "冷漠", "冰山", "无口", "寡言",
        "cool", "cold", "aloof", "quiet", "silent",
    ]
    gentle_kw = [
        "温柔", "体贴", "善良", "温暖", "治愈", "优雅", "文静",
        "kind", "gentle", "warm", "caring", "soft",
    ]
    for kw in cheerful_kw:
        if kw in text:
            return "cheerful"
    for kw in cool_kw:
        if kw in text:
            return "cool"
    for kw in gentle_kw:
        if kw in text:
            return "gentle"
    return "default"


class ProactiveMonitor(QObject):
    """Periodic timer that may trigger SMS or call events from contacts.

    Usage::

        monitor = ProactiveMonitor(contact_store, message_store)
        monitor.new_message.connect(phone.notify_new_message)
        monitor.incoming_call.connect(phone.notify_incoming_call)
        monitor.start(interval_sec=120)
    """

    new_message = Signal(str, str)  # (character_name, text)
    incoming_call = Signal(str)     # character_name

    def __init__(
        self,
        contact_store: ContactStore,
        message_store: MessageStore,
    ) -> None:
        super().__init__()
        self._contacts = contact_store
        self._messages = message_store
        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)
        self._character_settings: dict[str, str] = {}
        self._interval_ms = 120_000

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def set_character_settings(self, settings: dict[str, str]) -> None:
        """Set {name: character_setting} map for personality classification."""
        self._character_settings = dict(settings)

    def start(self, interval_sec: float = 120.0) -> None:
        self._interval_ms = int(interval_sec * 1000)
        self._timer.start(self._interval_ms)

    def stop(self) -> None:
        self._timer.stop()

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        contacts = self._contacts.get_contacts()
        if not contacts:
            return

        # Only trigger for real character names
        try:
            from config.config_manager import ConfigManager
            valid_names = {c.name for c in ConfigManager().config.characters}
        except Exception:
            valid_names = set(contacts)

        now = time.time()
        for name in contacts:
            if name not in valid_names:
                continue
            last = self._contacts.last_interaction(name)
            idle_sec = now - last

            # ── SMS probability ──
            sms_chance = _sms_probability(idle_sec)
            if random.random() < sms_chance:
                text = self._generate_message(name)
                if text:
                    self.new_message.emit(name, text)
                    self._contacts.touch_interaction(name)
                    continue  # only one event per tick per contact

            # ── call probability (rarer) ──
            call_chance = _call_probability(idle_sec)
            if random.random() < call_chance:
                self.incoming_call.emit(name)
                self._contacts.touch_interaction(name)

    def _generate_message(self, name: str) -> str:
        setting = self._character_settings.get(name, "")
        group = _classify_personality(setting)
        templates = _TEMPLATES.get(group, _TEMPLATES["default"])
        return random.choice(templates)


# ── probability helpers ───────────────────────────────────────────────


def _sms_probability(idle_seconds: float) -> float:
    """Probability (0..1) that a contact sends an SMS after *idle_seconds*."""
    minutes = idle_seconds / 60.0
    if minutes < 3:
        return 0.0
    if minutes < 8:
        return 0.05
    if minutes < 15:
        return 0.12
    if minutes < 30:
        return 0.20
    return 0.30


def _call_probability(idle_seconds: float) -> float:
    """Probability (0..1) that a contact calls after *idle_seconds* (rarer)."""
    minutes = idle_seconds / 60.0
    if minutes < 8:
        return 0.0
    if minutes < 15:
        return 0.03
    if minutes < 30:
        return 0.06
    return 0.10
