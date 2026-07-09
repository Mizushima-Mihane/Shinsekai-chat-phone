"""Background timer that makes contacts proactively send messages or call."""

from __future__ import annotations

import random
import time

from PySide6.QtCore import QObject, QTimer, Signal

from plugins.shinsekai_chat_phone.contact_store import ContactStore
from plugins.shinsekai_chat_phone.message_store import MessageStore, MessageType


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


def _recent_story_context(max_lines: int = 8) -> str:
    """Digest the most recent main-story dialogue from chat_history.

    Returns a short "谁: 说了什么" transcript (player + characters + narration,
    excluding internal markers) so a proactive SMS can stay coherent with the
    plot. Empty string if no active session is found.
    """
    import json
    import re
    from pathlib import Path

    base = Path("data/chat_history")
    if not base.is_dir():
        return ""
    try:
        dirs = sorted((d for d in base.iterdir() if d.is_dir()),
                      key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        return ""
    _SKIP = {"COT", "PHONE", "CALL", "CHOICE", "STAT", "bgm", "CG"}
    for d in dirs:
        aj = d / "active.json"
        if not aj.is_file():
            continue
        try:
            data = json.loads(aj.read_text(encoding="utf-8"))
        except Exception:
            continue
        msgs = data if isinstance(data, list) else data.get("messages", data.get("history", []))
        if not isinstance(msgs, list):
            return ""
        lines: list[str] = []
        for m in msgs[-14:]:
            if not isinstance(m, dict):
                continue
            role = m.get("role")
            content = m.get("content", "")
            if not isinstance(content, str):
                continue
            if role == "user":
                raw = content.strip()
                # Skip phone-scene turns and tool directives — those aren't
                # face-to-face story (SMS history is already passed separately).
                if re.match(r'^\s*\[(短信|通话|视频|视频通话)\]', raw):
                    continue
                if "请调用" in raw or "send_sms" in raw:
                    continue
                txt = re.sub(r'^\s*\[[^\]]*\]\s*', '', raw).strip()
                if txt:
                    lines.append(f"玩家: {txt[:80]}")
            elif role == "assistant":
                idx = content.find("{")
                if idx < 0:
                    continue
                try:
                    dd = json.loads(content[idx:])
                except Exception:
                    continue
                for it in dd.get("dialog", []):
                    if not isinstance(it, dict):
                        continue
                    cn = str(it.get("character_name", "") or "").strip()
                    sp = str(it.get("speech", "") or "").strip()
                    if not cn or not sp or cn in _SKIP:
                        continue
                    label = "旁白" if cn in ("NARR", "旁白") else cn
                    lines.append(f"{label}: {sp[:80]}")
        return "\n".join(lines[-max_lines:])
    return ""


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
        self._scene_char: str = ""          # legacy single value (compat)
        self._scene_ts: float = 0
        self._scene_chars: dict[str, float] = {}  # {name: last_seen_ts}

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def set_character_settings(self, settings: dict[str, str]) -> None:
        """Set {name: character_setting} map for personality classification."""
        self._character_settings = dict(settings)

    def set_scene_character(self, name: str) -> None:
        """Mark a character as currently face-to-face in the scene.

        Tracks a *set* of recent scene characters (with timestamps) so that
        multi-character scenes are all skipped for proactive SMS/calls, not just
        the last speaker. Stale entries are pruned to keep the dict bounded.
        """
        now = time.time()
        self._scene_char = name
        self._scene_ts = now
        self._scene_chars[name] = now
        self._scene_chars = {n: ts for n, ts in self._scene_chars.items()
                             if now - ts < 300}

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
        # Characters seen face-to-face in the last ~3 min — don't proactively
        # text or call them; they're right next to the player, so it should be
        # said in person (LLM handles the rare in-scene SMS via system prompt).
        scene_recent = {
            n for n, ts in getattr(self, '_scene_chars', {}).items()
            if now - ts < 180
        }
        for name in contacts:
            if name not in valid_names:
                continue
            if name in scene_recent:
                continue  # in-scene (face-to-face) — don't call/text
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
                from plugins.shinsekai_chat_phone.settings_app import is_character_yandere
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
                from plugins.shinsekai_chat_phone.plugin import get_phone_widget
                w = get_phone_widget()
                if w:
                    call_char = getattr(w, '_call_char', '')
                    call_state = getattr(w, '_state', None)
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
        """LLM generates a context-aware message from relationship + main story."""
        setting = self._character_settings.get(name, "")
        # Build SMS history context
        sms_hist = []
        for m in self._messages.get_messages(name)[-6:]:
            who = "对方" if m.get("is_user") else name
            sms_hist.append(f"{who}: {m.get('text','')}")
        # Recent main-story dialogue, so the SMS follows the current plot
        story = _recent_story_context()
        try:
            from plugins.shinsekai_chat_phone.sms_llm import _call_llm
            prompt = (
                f"你(主动方)给对方发了一条短信，不是对方找你。"
                f"结合当前剧情最近发生的事、你们之前的短信记录和你的性格，"
                f"作为主动联系的一方，你会发一条什么短信？"
                f"只回复短信内容，不要加任何前缀、引号或格式。"
            )
            result = _call_llm(name, setting, prompt, sms_hist, story_context=story)
            if result and len(result) > 2:
                return result
        except Exception:
            pass
        return ""


# ── probability helpers ───────────────────────────────────────────────


