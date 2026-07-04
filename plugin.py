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
from sdk.types import ChatUIContribution, FrontendConfigContribution

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
                # Proactive monitor disabled for now
                # monitor = ProactiveMonitor(w.contact_store(), w.message_store())
                # monitor.set_character_settings(char_settings)
                # monitor.new_message.connect(w.notify_new_message)
                # monitor.incoming_call.connect(w.notify_incoming_call)
                # monitor.start(interval_sec=60)
                _monitor = None
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
                        w.route_llm_reply(cn, sp)
                    else:
                        (pdb2 / "debug_phone.txt").write_text(f"PHONE NO MATCH: speech={speech}", encoding="utf-8")
                    continue
                # Filter: during a call, only allow target character
                call_target = getattr(w, '_call_char', '')
                if call_target and name != call_target:
                    continue
                if name in ("NARR", "CHOICE", "STAT", "bgm", "CG", "COT", "旁白", "PHONE"):
                    continue
                w.route_llm_reply(name, speech)

        register.register_message_added_hook(on_message_added)

        # Before-chat hook: inject PHONE format into system prompt
        def on_before_chat(ctx):
            try:
                msg = (
                    "[手机系统] 玩家有手机。重要规则："
                    "收到[短信]标记时，dialog数组只包含PHONE项，"
                    "不要输出其他在场角色的对话或旁白。"
                    "PHONE: character_name=\"PHONE\", sprite=\"-1\", "
                    "speech=\"角色名：回复内容\"。"
                )
                ctx.messages.insert(0, {"role": "system", "content": msg})
                (pdb / "debug_system.txt").write_text("INJECTED OK", encoding="utf-8")
            except Exception as e:
                (pdb / "debug_system.txt").write_text(f"FAIL: {e}", encoding="utf-8")

        register.register_before_chat_hook(on_before_chat)
        (pdb / "debug_system.txt").write_text("HOOK REGISTERED", encoding="utf-8")

        # Avatar config page
        char_names = list(char_settings.keys())
        register.register_frontend_config_page(FrontendConfigContribution(
            page_id="chat_phone_avatars",
            title="Chat Phone 头像",
            kind="settings",
            description="设置手机通讯录中角色的头像。",
            schema=[{
                "id": "avatars", "title": "头像设置",
                "fields": [
                    {"key": "character", "label": "选择角色", "type": "select",
                     "options": [{"label": n, "value": n} for n in char_names],
                     "defaultValue": char_names[0] if char_names else ""},
                    {"key": "avatar_path", "label": "自定义头像路径", "type": "text",
                     "defaultValue": "", "placeholder": "图片路径"},
                ],
            }],
            load_values=lambda: {"character": char_names[0] if char_names else "", "avatar_path": ""},
            save_values=_save_avatar_config,
            order=50.0,
        ))

        logger.info("Chat Phone initialized (chars=%d)", len(char_settings))

    def shutdown(self) -> None:
        global _phone_widget, _monitor
        if _monitor is not None:
            _monitor.stop()
        _phone_widget = None
        _monitor = None
