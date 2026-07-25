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


def _split_moment_image(text: str) -> tuple[str, str]:
    """Split a trailing ``[图:描述]`` marker off a moment body. Returns (body, desc)."""
    import re
    m = re.search(r'[\[【]\s*图\s*[:：]\s*(.+?)\s*[\]】]\s*$', text or "")
    if m:
        return (text[:m.start()].strip(), m.group(1).strip())
    return ((text or "").strip(), "")


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

    # 场景是「状态」不是「计时」：角色一旦当面在场，就一直算在场，直到 clear_scene()
    # （转场/时间跳跃）或 remove_scene_character()（某人离开）显式释放。这里的时间戳只做
    # 一个很长的安全兜底（防止漏检转场导致某角色被永久排除主动联系）。
    _SCENE_BACKSTOP_SEC = 7200  # 2 小时
    _MOMENT_K = 0.03  # 朋友圈主动发的阻尼常数（默认偏静：freq 0.02 → 约每 28h/角色）

    def set_scene_character(self, name: str) -> None:
        """标记某角色此刻与玩家当面同场（持续在场，直到显式转场/离开才释放）。

        当面说话也算一次「互动」——同步刷新 last_interaction 作为辅助保护。
        """
        name = (name or "").strip()
        if not name:
            return
        now = time.time()
        self._scene_char = name
        self._scene_ts = now
        self._scene_chars[name] = now
        # 只按超长兜底剪枝，不按短时窗口——在场是状态，靠 clear/remove 释放。
        self._scene_chars = {n: ts for n, ts in self._scene_chars.items()
                             if now - ts < self._SCENE_BACKSTOP_SEC}
        try:
            self._contacts.touch_interaction(name)
        except Exception:
            pass

    def clear_scene(self) -> None:
        """转场 / 时间跳跃 —— 上一个场景结束，清空全部在场角色。"""
        self._scene_char = ""
        self._scene_chars = {}

    def remove_scene_character(self, name: str) -> None:
        """某角色离开当前场景 —— 单独移出在场集合（其余人仍在场）。"""
        name = (name or "").strip()
        if not name:
            return
        self._scene_chars.pop(name, None)
        if self._scene_char == name:
            self._scene_char = ""

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
        # 在场（当面）角色 —— 主动监控绝不给他们发短信/打电话：人就在玩家旁边，有话当面说。
        # 「在场」是状态：从当面说话起一直保持，直到 clear_scene()（转场）或 remove_scene_character()
        # （离开）释放；这里只用超长兜底防漏检。剧情确实需要的在场短信由主 LLM 判断，不走这里。
        scene_recent = {
            n for n, ts in getattr(self, '_scene_chars', {}).items()
            if now - ts < self._SCENE_BACKSTOP_SEC
        }
        for name in contacts:
            if name not in valid_names:
                continue
            # 朋友圈：独立低频 roll，不受在场/叠发门约束（异步「拉」型社交，不打扰）。
            if self._maybe_post_moment(name):
                self._contacts.touch_interaction(name)
                continue
            if name in scene_recent:
                continue  # in-scene (face-to-face) — don't call/text
            # 病娇提前判定（病娇允许追问/叠发，是其人设；普通角色不叠发）
            try:
                from plugins.shinsekai_chat_phone.settings_app import is_character_yandere
                yandere = is_character_yandere(name)
            except Exception:
                yandere = False
            # 不叠发（场景/剧情驱动，替代原「距上次互动<5分钟」的纯计时门）：
            # 普通角色若已主动发过一条、玩家还没回，就不再连发（避免「在吗?在吗?」）；
            # 空会话（首次联系）或玩家最后发言（球在角色这边）才可主动；病娇不受此限。
            _lastmsg = self._messages.last_message(name)
            if not yandere and _lastmsg is not None and not _lastmsg.get("is_user"):
                continue
            fc = getattr(self, '_freq_config', {}).get(name, {})
            sms_base = fc.get("sms", 0.1)
            call_base = fc.get("call", 0.03)
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
            # 来电比短信打扰得多——同样的频率设定要稀得多。加 0.06 阻尼：滑块 0–0.5 → 每 tick 0–0.03，
            # 即满值(0.5)约 33 分钟一通、默认(0.03)约 9 小时一通。相对偏好（谁更爱打）保留。
            call_chance = call_base * 0.06
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
            result = _call_llm(name, setting, prompt, sms_hist, story_context=story, initiate=True)
            if result and len(result) > 2:
                return result
        except Exception:
            pass
        return ""

    def _maybe_post_moment(self, name: str) -> bool:
        """低频掷骰：命中则让该角色静默发一条朋友圈动态（进库+红点，不开主 LLM 回合）。"""
        mo_base = getattr(self, '_freq_config', {}).get(name, {}).get("moments", 0.02)
        try:
            from plugins.shinsekai_chat_phone.settings_app import is_character_yandere
            if is_character_yandere(name):
                mo_base = min(mo_base * 1.6, 0.4)
        except Exception:
            pass
        if random.random() >= mo_base * self._MOMENT_K:
            return False
        text = self._generate_moment(name)
        body, desc = _split_moment_image(text)
        if not body and not desc:
            return False
        try:
            from plugins.shinsekai_chat_phone.plugin import get_phone_widget
            w = get_phone_widget()
            if w is not None:
                w.post_moment_from_llm(name, body, desc)
                return True
        except Exception:
            pass
        return False

    def _generate_moment(self, name: str) -> str:
        """LLM 自拟一条朋友圈动态（可选结尾 [图:描述]）。"""
        setting = self._character_settings.get(name, "")
        story = _recent_story_context()
        try:
            from plugins.shinsekai_chat_phone.sms_llm import _call_llm
            prompt = (
                "你现在想发一条朋友圈动态。结合你此刻的心情、近况和当前剧情，写一两句朋友圈文案。"
                "可选：如果想配张图，就在结尾用 [图:简短画面描述] 表示（例如 [图:窗外的雨]）。"
                "只输出动态正文（含可选的 [图:...]），不要加任何前缀、引号或其它格式。"
            )
            result = _call_llm(name, setting, prompt, [], story_context=story, initiate=True)
            if result and len(result.strip()) > 1:
                return result.strip()
        except Exception:
            pass
        return ""


# ── probability helpers ───────────────────────────────────────────────


