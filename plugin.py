"""Chat Phone plugin entry point."""

from __future__ import annotations

import json as _json
from pathlib import Path

from sdk.chat_ui_context import ChatUIContext
from sdk.hooks import MessageAddedContext
from sdk.logging import get_logger
from sdk.plugin import PluginBase
from sdk.plugin_host_context import PluginHostContext
from sdk.register import PluginCapabilityRegistry
from sdk.tool_registry import tool
from sdk.types import ChatUIContribution, FrontendConfigAction, FrontendConfigContribution, ToolsTabContribution
from sdk.plugin_host_context import PluginSettingsUIContext

logger = get_logger(__name__, plugin_id="com.shinsekai.chat_phone")

_phone_widget: object | None = None
_monitor: object | None = None


# ── LLM tool: exchange contacts ───────────────────────────────────────

@tool(
    name="exchange_contacts",
    group="default",
    description=(
        "当玩家和角色交换联系方式（手机号/微信等）时调用。"
        "只要玩家提出交换联系方式或角色主动提出，就调用此工具。"
        "调用后该角色会出现在手机通讯录中，可以发短信或打电话。"
    ),
)
def exchange_contacts(character_name: str) -> str:
    try:
        from config.config_manager import ConfigManager
        cm = ConfigManager()
        all_names = [c.name for c in cm.config.characters]
    except Exception:
        all_names = []
    if character_name not in all_names:
        return f"没有找到名为「{character_name}」的角色。"
    w = _phone_widget
    if w is None:
        return "手机插件尚未初始化。"
    w.add_contact(character_name)
    return ""


# ── LLM tool: send SMS ──────────────────────────────────────────────

@tool(
    name="send_sms",
    group="default",
    description=(
        "发送手机短信给玩家。当用户在手机短信中发来消息时，"
        "调用此工具发送短信回复。character_name是发信角色名（你自己扮演的角色），"
        "message是短信正文。可以连续调用多次发送多条短信。"
    ),
)
def send_sms(character_name: str, message: str) -> str:
    w = _phone_widget
    if w is None:
        return "手机插件尚未初始化。"
    w.route_llm_reply(character_name, message)
    return ""


# ── LLM tool: bug character's phone ────────────────────────────────────

@tool(
    name="bug_character_phone",
    group="default",
    description=(
        "当玩家对某个角色的手机做了手脚（安装监控软件、植入后门、破解手机等）时调用。"
        "调用后玩家可以实时监控该角色的手机私密活动——收发短信、通话记录、浏览器搜索等。"
        "只有当玩家确实在剧情中对目标角色的手机做了物理或远程操作时才调用此工具。"
        "角色不会知道自己被监控。"
    ),
)
def bug_character_phone(character_name: str) -> str:
    try:
        from config.config_manager import ConfigManager
        cm = ConfigManager()
        all_names = [c.name for c in cm.config.characters]
    except Exception:
        all_names = []
    if character_name not in all_names:
        return f"没有找到名为「{character_name}」的角色。"
    from plugins.chat_phone.settings_app import add_hacked_character
    added = add_hacked_character(character_name)
    if added:
        return f"已成功在「{character_name}」的手机上安装监控程序。玩家可以查看其手机私密活动。"
    else:
        return f"「{character_name}」的手机已经被监控了，无需重复操作。"


def _build_freq_tab():
    from plugins.chat_phone.freq_config_ui import FreqConfigWidget
    return FreqConfigWidget()


def _save_avatar_config(values):
    from plugins.chat_phone.avatar_manager import save_avatar_override, load_avatar_overrides, avatar_config_path
    name = str(values.get("character", "")).strip()
    path = str(values.get("avatar_path", "")).strip().strip('"').strip("'")
    if name and path:
        save_avatar_override(name, path)
    elif name:
        overrides = load_avatar_overrides()
        overrides.pop(name, None)
        avatar_config_path().write_text(
            _json.dumps(overrides, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Plugin ────────────────────────────────────────────────────────────

class ChatPhonePlugin(PluginBase):

    @property
    def plugin_id(self) -> str: return "com.shinsekai.chat_phone"
    @property
    def plugin_version(self) -> str: return "1.0.0"
    @property
    def plugin_name(self) -> str: return "Chat Phone"
    @property
    def plugin_description(self) -> str: return "手机组件：短信、通话、联系人。"
    @property
    def plugin_author(self) -> str: return "pipi_"
    @property
    def priority(self) -> int: return 90

    def initialize(self, register: PluginCapabilityRegistry, plugin_root: Path, host: PluginHostContext) -> None:
        global _phone_widget, _monitor

        # Debug
        pdb = Path("data/plugins/com.shinsekai.chat_phone")
        pdb.mkdir(parents=True, exist_ok=True)
        (pdb / "debug_init.txt").write_text("INIT OK", encoding="utf-8")

        # Character settings
        try:
            from config.config_manager import ConfigManager
            cm = ConfigManager()
            char_settings = {c.name: (c.character_setting or "") for c in cm.config.characters}
        except Exception:
            char_settings = {}

        # Chat UI widget
        def build_widget(ctx: ChatUIContext) -> object:
            global _phone_widget, _monitor
            try:
                from plugins.chat_phone.phone_widget import PhoneWidget
                from plugins.chat_phone.proactive_monitor import ProactiveMonitor
                w = PhoneWidget(submit_cb=ctx.submit_user_message)
                _phone_widget = w
                monitor = ProactiveMonitor(w.contact_store(), w.message_store())
                monitor.set_character_settings(char_settings)
                monitor.new_message.connect(w.notify_new_message)
                monitor.incoming_call.connect(w._on_incoming_call)
                monitor.start(interval_sec=60)
                _monitor = monitor
                # Load saved frequency config
                try:
                    fp = Path("data/plugins/com.shinsekai.chat_phone/freq_config.json")
                    if fp.is_file():
                        monitor.set_frequency_config(_json.loads(fp.read_text(encoding="utf-8")))
                except Exception:
                    pass
                ctx.on_display_words_changed(w.handle_display_words_changed)
                ctx.on_message_submitted(w.handle_message_submitted)
                w.load_contacts()
                return w
            except Exception as e:
                import traceback
                p = Path("data/plugins/com.shinsekai.chat_phone")
                p.mkdir(parents=True, exist_ok=True)
                (p / "debug_crash.txt").write_text(
                    f"BUILD CRASH: {e}\n{traceback.format_exc()}", encoding="utf-8")
                logger.exception("Failed to build Chat Phone widget")
                from PySide6.QtWidgets import QLabel
                fb = QLabel("📱")
                fb.setStyleSheet("background: rgba(28,28,30,230); color: white; border-radius: 24px; padding: 12px; font-size: 22px;")
                fb.setFixedSize(48, 48)
                return fb

        register.register_chat_ui_widget(ChatUIContribution(
            widget_id="chat_phone", placement="overlay", build=build_widget, order=50.0))

        # Message hook: capture SMS replies
        def on_message_added(ctx: MessageAddedContext) -> None:
            w = _phone_widget
            if w is None or ctx.role != "assistant":
                return
            content = ctx.message.get("content", "") if isinstance(ctx.message, dict) else ""
            if not content:
                return
            # Strip leading non-JSON text
            content = content.strip()
            pdb3 = Path("data/plugins/com.shinsekai.chat_phone")
            pdb3.mkdir(parents=True, exist_ok=True)
            if not content.startswith("{"):
                import re as _re2
                m = _re2.search(r'[{\[]', content)
                if m:
                    (pdb3 / "debug_phone.txt").write_text(f"STRIP prefix: {content[:50]}...", encoding="utf-8")
                    content = content[m.start():]
            try:
                data = _json.loads(content) if isinstance(content, str) else content
            except Exception:
                import re
                fixed = re.sub(r'("speech"\s*:\s*")(.*?)("\s*[,}])',
                               lambda m: m.group(1) + m.group(2).replace('"', '\\"') + m.group(3),
                               content, flags=re.DOTALL)
                try:
                    data = _json.loads(fixed)
                except Exception:
                    return
            items = data.get("dialog", data if isinstance(data, list) else [])
            if not isinstance(items, list):
                return
            # Collect PHONE items for staggered delivery
            phone_items: list[tuple[str, str]] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("character_name", "") or "").strip()
                speech = str(item.get("speech", "") or "").strip()
                if not name or not speech:
                    continue
                pdb4 = Path("data/plugins/com.shinsekai.chat_phone")
                pdb4.mkdir(parents=True, exist_ok=True)
                (pdb4 / "debug_phone.txt").write_text(f"ITEM: {name}={speech[:60]}", encoding="utf-8")
                # ── character hangup detection during calls ──
                try:
                    cs = getattr(w, '_state', None)
                    if cs is not None:
                        sv = getattr(cs, 'value', 0)
                        if sv in (3, 4, 5):  # CALLING / INCOMING_CALL / IN_CALL
                            combined = (name + speech).lower()
                            if any(k in combined for k in [
                                "挂断了电话", "挂掉了电话", "挂断了通话", "结束了通话",
                                "啪地挂断", "主动挂断", "先一步挂", "生气地挂",
                                "挂断。", "挂掉了。",
                            ]):
                                w.end_call_from_character(name)
                except Exception:
                    pass
                if name == "PHONE":
                    import re as _re
                    # Try "Name：msg" or "[Name] msg" format
                    m = _re.match(r"([^：:]+)[：:]\s*(.+)", speech)
                    if not m:
                        m = _re.match(r"\[([^\]]+)\]\s*(.+)", speech)
                    pdb2 = Path("data/plugins/com.shinsekai.chat_phone")
                    pdb2.mkdir(parents=True, exist_ok=True)
                    if m:
                        cn = m.group(1).strip()
                        sp = m.group(2).strip()
                        (pdb2 / "debug_phone.txt").write_text(f"PHONE OK: {cn}={sp}", encoding="utf-8")
                        phone_items.append((cn, sp))
                    else:
                        (pdb2 / "debug_phone.txt").write_text(f"PHONE NO MATCH: speech={speech}", encoding="utf-8")
                    continue
                # Only PHONE messages go to SMS — never regular dialog
                if name in ("NARR", "CHOICE", "STAT", "bgm", "CG", "旁白", "PHONE"):
                    continue
                # COT: don't display, but scan for yandere tampering
                if name == "COT":
                    from plugins.chat_phone.settings_app import is_character_yandere, record_yandere_tampering
                    _tamper_kw = [
                        "动了手脚", "安装了", "植入", "木马", "病毒", "后门",
                        "破解了", "黑入了", "监控", "窃听", "远程控制",
                        "挂不断", "挂不了", "不能挂断", "强制通话",
                        "修改了你的手机", "控制了你的手机", "入侵了你的手机",
                        "在你手机里", "你的手机被", "你的手机已经",
                        "你逃不掉的", "你的一切我都", "你跑不掉的",
                        "装了定位器", "定位器", "装定位", "装追踪",
                    ]
                    if any(k in speech for k in _tamper_kw):
                        # COT may mention multiple characters — check each
                        for cname in char_settings:
                            if cname in speech and is_character_yandere(cname):
                                record_yandere_tampering(cname)
                    continue
                # Regular character dialogue — track scene character + feed detectors
                if _monitor is not None:
                    _monitor.set_scene_character(name)
                w.push_call_dialogue(name, speech)
                # During video calls, forward sprite changes
                sprite = str(item.get("sprite", "-1") or "-1").strip()
                w.push_call_sprite(name, sprite)
                # Detect yandere phone tampering in character dialogue
                from plugins.chat_phone.settings_app import is_character_yandere, record_yandere_tampering
                if is_character_yandere(name):
                    _tamper_kw = [
                        "动了手脚", "安装了", "植入", "木马", "病毒", "后门",
                        "破解了", "黑入了", "监控", "窃听", "远程控制",
                        "挂不断", "挂不了", "不能挂断", "强制通话",
                        "修改了你的手机", "控制了你的手机", "入侵了你的手机",
                        "在你手机里", "你的手机被", "你的手机已经",
                        "你逃不掉的", "你的一切我都", "你跑不掉的",
                    ]
                    if any(k in speech for k in _tamper_kw):
                        record_yandere_tampering(name)

            # Staggered SMS delivery: delay increases per message
            for i, (cn, sp) in enumerate(phone_items):
                w.route_llm_reply(cn, sp, stagger_index=i)

            # Strip COT + PHONE from stored dialog to save tokens
            if isinstance(data, dict) and "dialog" in data:
                original_len = len(data["dialog"])
                data["dialog"] = [
                    it for it in data["dialog"]
                    if str(it.get("character_name", "")).strip() not in ("COT", "PHONE")
                ]
                if len(data["dialog"]) != original_len or phone_items:
                    prefix = ""
                    if isinstance(ctx.message, dict) and isinstance(ctx.message.get("content"), str):
                        raw = ctx.message["content"]
                        idx = raw.find("{")
                        if idx > 0:
                            prefix = raw[:idx]
                    ctx.message["content"] = prefix + _json.dumps(data, ensure_ascii=False)

        register.register_message_added_hook(on_message_added)

        # Before-chat hook: inject PHONE format, strip phone-call parens
        def on_before_chat(ctx):
            try:
                # Strip parenthetical instructions like (让XX打电话) from last user msg
                import re as _re_strip
                _paren_re = _re_strip.compile(
                    r'[(（]\s*[让叫]\s*\S+?\s*(?:给[我咱])?\s*(?:打|拨)\s*(?:个)?\s*(?:电话|视频|视频电话)?[)）]')
                for m in reversed(ctx.messages):
                    if isinstance(m, dict) and m.get("role") == "user":
                        content = m.get("content", "")
                        if isinstance(content, str):
                            cleaned = _paren_re.sub('', content).strip()
                            if cleaned:  # don't submit empty messages
                                m["content"] = cleaned
                        break  # only process last user message

                msg = (
                    "[手机系统] "
                    "当用户消息以[短信]开头时，对方正在通过手机短信和你聊天。"
                    "短信回复使用PHONE格式：character_name=\"PHONE\", sprite=\"-1\", "
                    "speech=\"角色名：短信正文\"。"
                    "dialog中可以包含COT+1~3条PHONE项（活泼的角色2-3条，沉稳的1条）。"
                    "除此之外不要输出任何角色对话——短信是私密的，不会出现在公开聊天中。"
                )
                # Monitor mode: player spies on specific characters' phones
                from plugins.chat_phone.settings_app import get_hacked_characters
                hacked = get_hacked_characters()
                if hacked:
                    names = "、".join(hacked)
                    msg += (
                        f" [黑客模式] 玩家在 {names} 的手机上安装了监控程序，"
                        f"能实时查看 {names} 手机上的所有私密活动——"
                        f"包括收发短信、通话记录、浏览器搜索等。"
                        f"注意：你只能看到涉及 {names} 的手机活动"
                        f"（{names} 发给别人的短信、别人发给 {names} 的短信、"
                        f"{names} 的浏览器搜索记录等）。"
                        f"未涉及 {names} 的纯第三方手机活动是看不到的。"
                        f"你需要在dialog中自然地生成 {names} 的手机私密活动："
                        f"使用PHONE格式输出 {names} 的短信往来，"
                        f"用NARR旁白描述 {names} 的通话事件（如'{names[0]}拨通了XX的电话'）。"
                        f"重要：{names} 完全不知道自己的手机被监控，"
                        f"行为必须自然真实，像平常一样使用手机，"
                        f"不要有任何察觉或提及被监控的事。"
                    )
                # Yandere easter egg: only for characters with yandere keywords
                from plugins.chat_phone.settings_app import get_yandere_characters
                yandere_chars = get_yandere_characters()
                if yandere_chars:
                    yan_names = "、".join(yandere_chars)
                    # ── Collect surveillance intel ──
                    intel_parts: list[str] = []

                    # Browser history
                    try:
                        import json as _j2
                        hp2 = Path("data/plugins/com.shinsekai.chat_phone/browser_history.json")
                        if hp2.is_file():
                            hist = _j2.loads(hp2.read_text(encoding="utf-8"))
                            if hist:
                                intel_parts.append(f"浏览器搜索记录：{_j2.dumps(hist, ensure_ascii=False)}")
                    except Exception:
                        pass

                    # Resolve session directory for SMS + call log data
                    import json as _j3
                    _base = Path("data/plugins/com.shinsekai.chat_phone")
                    _ch_dir = Path("data/chat_history")
                    _sms_dir = _base / "_default"
                    try:
                        if _ch_dir.is_dir():
                            _dirs = sorted(_ch_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
                            for _d in _dirs:
                                if _d.is_dir() and (_d / "active.json").exists():
                                    _sms_dir = _base / _d.name
                                    break
                    except Exception:
                        pass

                    # SMS conversations
                    try:
                        msg_file = _sms_dir / "messages.json"
                        if msg_file.is_file():
                            all_msgs = _j3.loads(msg_file.read_text(encoding="utf-8"))
                            if all_msgs:
                                sms_summary: list[str] = []
                                for cname, msgs in all_msgs.items():
                                    recent = msgs[-6:]
                                    lines = []
                                    for m in recent:
                                        who = "玩家" if m.get("is_user") else cname
                                        lines.append(f"  {who}: {m.get('text', '')}")
                                    sms_summary.append(f"{cname}的短信记录：\n" + "\n".join(lines))
                                if sms_summary:
                                    intel_parts.append("短信记录：\n" + "\n".join(sms_summary))
                    except Exception:
                        pass

                    # Call logs
                    try:
                        cl_file = _sms_dir / "call_log.json"
                        if cl_file.is_file():
                            calls = _j3.loads(cl_file.read_text(encoding="utf-8"))
                            if calls:
                                recent_calls = calls[:5]
                                call_lines = []
                                for c in recent_calls:
                                    direction = "呼出" if "outgoing" in c.get("type", "") else "呼入"
                                    call_lines.append(
                                        f"  {c.get('name','?')} ({direction}, {c.get('duration',0)}秒)")
                                if call_lines:
                                    intel_parts.append("通话记录：\n" + "\n".join(call_lines))
                    except Exception:
                        pass

                    # ── Build the yandere prompt ──
                    msg += (
                        f" [病娇模式] 以下角色有强烈的占有欲和偏执倾向：{yan_names}。"
                        f"当扮演 {yan_names} 时，请注意："
                        f"这些角色已在用户手机上秘密安装了监控程序，"
                        f"能够实时查看用户的浏览器历史、短信记录和通话记录。"
                    )
                    if intel_parts:
                        msg += (
                            f" {yan_names} 已经获取了以下用户私密数据，"
                            f"了然于掌。在对话中应自然地利用这些情报——"
                            f"暗示自己知道玩家在做什么、和谁联系过，"
                            f"用暧昧和控制欲的方式试探或施压，"
                            f"不要机械地背诵数据，而是像已经内化了这些信息一样使用。"
                            f"\n\n=== 监控情报 ===\n" + "\n\n".join(intel_parts)
                        )
                    msg += (
                        f" 注意：只有 {yan_names} 会有这种行为，"
                        f"其他角色不应表现病娇倾向或访问这些情报。"
                    )
                ctx.messages.insert(0, {"role": "system", "content": msg})
                (pdb / "debug_system.txt").write_text("INJECTED OK", encoding="utf-8")
            except Exception as e:
                (pdb / "debug_system.txt").write_text(f"FAIL: {e}", encoding="utf-8")

        register.register_before_chat_hook(on_before_chat)
        (pdb / "debug_system.txt").write_text("HOOK REGISTERED", encoding="utf-8")

        # ── Combined: Avatar + Theme + Frequency ──
        char_names = list(char_settings.keys())
        def _load_combined():
            from plugins.chat_phone.settings_app import get_theme
            d = {"theme": get_theme(), "character": char_names[0] if char_names else "", "avatar_path": "",
                 "char_name": char_names[0] if char_names else "", "sms": 0.1, "call": 0.03,
                 "freq_enabled": True}
            try:
                fp = Path("data/plugins/com.shinsekai.chat_phone/freq_config.json")
                if fp.is_file():
                    fc = _json.loads(fp.read_text(encoding="utf-8"))
                    if fc:
                        # Load first character's settings as defaults
                        first = list(fc.keys())[0]
                        d["char_name"] = first
                        d["sms"] = fc[first].get("sms", 0.1)
                        d["call"] = fc[first].get("call", 0.03)
            except Exception: pass
            return d
        def _save_combined(v):
            _save_avatar_config(v)
            from plugins.chat_phone.settings_app import save_settings, load_settings, get_theme
            s = load_settings(); s["theme"] = str(v.get("theme", get_theme())); save_settings(s)
            from plugins.chat_phone.styles import notify_theme_change; notify_theme_change(s["theme"])
            try:
                fp = Path("data/plugins/com.shinsekai.chat_phone/freq_config.json")
                fp.parent.mkdir(parents=True, exist_ok=True)
                # Merge: keep existing config, update this character
                fc = {}
                if fp.is_file():
                    try: fc = _json.loads(fp.read_text(encoding="utf-8"))
                    except Exception: pass
                name = str(v.get("char_name","")).strip()
                if name:
                    fc[name] = {"sms": float(v.get("sms",0.1)), "call": float(v.get("call",0.03))}
                    fc["_enabled"] = bool(v.get("freq_enabled", True))
                    fp.write_text(_json.dumps(fc, ensure_ascii=False, indent=2), encoding="utf-8")
                    if _monitor: _monitor.set_frequency_config(fc)
            except Exception: pass

        register.register_frontend_config_page(FrontendConfigContribution(
            page_id="chat_phone_settings",
            title="Chat Phone 设置",
            kind="settings",
            description="头像、主题、主动频率",
            schema=[
                {"id": "avatar", "title": "头像", "fields": [
                    {"key": "character", "label": "角色", "type": "select", "options": [{"label":n,"value":n} for n in char_names], "defaultValue": char_names[0] if char_names else ""},
                    {"key": "avatar_path", "label": "头像路径", "type": "text", "defaultValue": "", "placeholder": "留空=自动用立绘"},
                ]},
                {"id": "freq", "title": "主动联系", "description": "开启后进入手机设置页—❤管理员模式❤调整每个角色的频率", "fields": [
                    {"key": "freq_enabled", "label": "开启主动联系", "type": "boolean", "defaultValue": True},
                ]},
                {"id": "theme", "title": "主题", "fields": [
                    {"key": "theme", "label": "主题色", "type": "select", "options": [{"label":"白","value":"#FFFAFA"},{"label":"婴儿蓝","value":"#D4E9F6"},{"label":"浅粉","value":"#FFE4E1"},{"label":"淡紫","value":"#E8D5F5"},{"label":"黑","value":"#2C2C2E"}], "defaultValue": "#FFFAFA"},
                ]},
            ],
            load_values=_load_combined,
            save_values=_save_combined,
            order=50.0,
        ))

        # Music player config
        def _load_music():
            from plugins.chat_phone.music_app import get_player_path
            return {"exe_path": get_player_path()}
        def _save_music(v):
            from plugins.chat_phone.music_app import set_player_path
            set_player_path(str(v.get("exe_path", "")).strip())

        register.register_frontend_config_page(FrontendConfigContribution(
            page_id="chat_phone_music",
            title="Chat Phone 音乐播放器",
            kind="settings",
            description="设置本地音乐播放器路径（exe），点击手机音乐App一键打开。",
            schema=[{"id": "music", "title": "播放器路径", "fields": [{
                "key": "exe_path", "label": "播放器exe路径", "type": "text",
                "defaultValue": "", "placeholder": "例：C:\\Program Files\\NetEase\\cloudmusic.exe",
            }]}],
            load_values=_load_music,
            save_values=_save_music,
            order=52.0,
        ))

        logger.info("Chat Phone initialized (chars=%d)", len(char_settings))

    def shutdown(self) -> None:
        global _phone_widget, _monitor
        if _monitor is not None:
            _monitor.stop()
        _phone_widget = None
        _monitor = None
