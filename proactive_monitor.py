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
        "在做什么呢？",
        "今天过得怎么样？",
        "突然想你了...",
        "方便聊天吗？",
        "我刚刚梦到你了",
        "看到个东西想到你了",
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

    new_message = Signal(str, str)      # (character_name, text)
    incoming_call = Signal(str, str)    # (character_name, call_type: "voice"|"video")

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
        self._scene_char: str = ""
        self._scene_ts: float = 0

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def set_character_settings(self, settings: dict[str, str]) -> None:
        """Set {name: character_setting} map for personality classification."""
        self._character_settings = dict(settings)

    def set_scene_character(self, name: str) -> None:
        """Mark the character currently active in the chat scene (skip proactive)."""
        self._scene_char = name
        self._scene_ts = time.time()

    def start(self, interval_sec: float = 120.0) -> None:
        self._interval_ms = int(interval_sec * 1000)
        self._timer.start(self._interval_ms)

    def stop(self) -> None:
        self._timer.stop()

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def set_frequency_config(self, config: dict[str, dict]):
        """Set per-character frequencies: {name: {sms: float, call: float}}"""
        self._freq_config = config
        self._urge: dict[str, float] = {}

    def _tick(self) -> None:
        # Check if proactive is enabled
        fc = getattr(self, '_freq_config', {})
        if not fc.get("_enabled", True):
            return
        contacts = self._contacts.get_contacts()
        if not contacts:
            return
        try:
            from config.config_manager import ConfigManager
            valid_names = {c.name for c in ConfigManager().config.characters}
        except Exception:
            valid_names = set(contacts)
        now = time.time()
        # Don't bother characters who are currently in the scene (face-to-face)
        scene_char = getattr(self, '_scene_char', '')
        scene_ts = getattr(self, '_scene_ts', 0)
        scene_active = scene_char and (now - scene_ts < 120)  # within 2 minutes
        for name in contacts:
            if name not in valid_names:
                continue
            if scene_active and name == scene_char:
                continue  # same scene — don't call/text
                continue
            last = self._contacts.last_interaction(name)
            idle_sec = now - last
            # Don't message if recently interacted (active chat in progress)
            if idle_sec < 300:  # 5 minutes
                continue
            fc = getattr(self, '_freq_config', {}).get(name, {})
            sms_base = fc.get("sms", 0.1)
            call_base = fc.get("call", 0.03)
            # Yandere multiplier: only if character has yandere traits
            try:
                from plugins.chat_phone.settings_app import is_character_yandere
                yandere = is_character_yandere(name)
            except Exception:
                yandere = False
            if yandere:
                sms_base = min(sms_base * 2.5, 0.8)
                call_base = min(call_base * 3, 0.3)
            # Accumulate random urge each tick (60s)
            urge = self._urge.get(name, 0.0)
            urge += random.uniform(0, sms_base * 2)
            self._urge[name] = urge
            # SMS: skip if already on a call with this character
            try:
                from plugins.chat_phone.plugin import _phone_widget
                if _phone_widget:
                    call_char = getattr(_phone_widget, '_call_char', '')
                    call_state = getattr(_phone_widget, '_state', None)
                    if call_state is not None:
                        sv = getattr(call_state, 'value', 0)
                        if sv in (3, 4, 5) and call_char == name:
                            continue
            except Exception: pass
            if urge > 0.8 + random.uniform(-0.2, 0.3):
                self._urge[name] = random.uniform(0, 0.3)
                text = self._generate_message(name)
                if text:
                    self.new_message.emit(name, text)
                    self._contacts.touch_interaction(name)
                    continue
            # Call: rarer, separate check
            call_chance = call_base * 0.3 + min(idle_sec / 3600, 0.3)
            if yandere:
                call_chance *= 2
            if random.random() < call_chance:
                # Determine voice vs video — video is much rarer (close relationship only)
                video_base = fc.get("video_call", 0.01)
                is_video = random.random() < video_base
                self.incoming_call.emit(name, "video" if is_video else "voice")
                self._contacts.touch_interaction(name)

    def _generate_message(self, name: str) -> str:
        """LLM generates context-aware message based on relationship."""
        setting = self._character_settings.get(name, "")
        # Build SMS history context
        sms_hist = []
        for m in self._messages.get_messages(name)[-6:]:
            who = "对方" if m.get("is_user") else name
            sms_hist.append(f"{who}: {m.get('text','')}")
        try:
            from plugins.chat_phone.sms_llm import _call_llm
            prompt = (
                f"你(主动方)给对方发了一条短信，不是对方找你。"
                f"根据你们之前的短信记录和你的性格，作为主动联系的一方，你会说什么？"
                f"只回复短信内容，不要加任何前缀、引号或格式。"
            )
            result = _call_llm(name, setting, prompt, sms_hist)
            if result and len(result) > 2:
                return result
        except Exception:
            pass
        return ""


# ── probability helpers ───────────────────────────────────────────────


