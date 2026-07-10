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

# ── Shared references (replaces phone_context cross-module import) ────

_phone_widget: object | None = None
_monitor: object | None = None


def get_phone_widget() -> object | None:
    return _phone_widget


def set_phone_widget(w: object) -> None:
    global _phone_widget
    _phone_widget = w


def get_monitor() -> object | None:
    return _monitor


def set_monitor(m: object) -> None:
    global _monitor
    _monitor = m


def clear_refs() -> None:
    global _phone_widget, _monitor
    _phone_widget = None
    _monitor = None


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
    w = get_phone_widget()
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
    w = get_phone_widget()
    if w is None:
        return "手机插件尚未初始化。"
    w.route_llm_reply(character_name, message)
    return ""


# ── LLM tool: send group SMS ────────────────────────────────────────

@tool(
    name="send_group_sms",
    group="default",
    description=(
        "在群聊里以某个角色的身份发一条消息。group_name是群名，"
        "character_name是发言角色名，message是消息内容。"
        "可连续多次调用让不同角色发言、或同一角色发多条，角色之间可互相接话。"
    ),
)
def send_group_sms(group_name: str, character_name: str, message: str) -> str:
    w = get_phone_widget()
    if w is None:
        return "手机插件尚未初始化。"
    w.route_group_reply(group_name, character_name, message)
    return ""


# ── LLM tool: create group ──────────────────────────────────────────

@tool(
    name="create_group",
    group="default",
    description=(
        "当剧情中把玩家拉进某个群聊、或角色们建了个群时调用。"
        "group_name是群名，members是群成员角色名（用、或逗号分隔）。"
    ),
)
def create_group(group_name: str, members: str) -> str:
    w = get_phone_widget()
    if w is None:
        return "手机插件尚未初始化。"
    mem = [m.strip() for m in members.replace("，", ",").replace("、", ",").split(",") if m.strip()]
    gid = w.create_group_from_llm(group_name, mem)
    return f"已创建群聊「{gid}」。" if gid else "建群失败。"


# ── LLM tools: group membership / rename (角色可主动操作) ──────────────

@tool(
    name="add_group_member",
    group="default",
    description=(
        "把某个角色拉进一个已存在的群聊。group_name是群名，character_name是被拉进来的角色，"
        "operator_name是执行这个操作的角色名（谁拉的，可留空）。"
        "只有当前群成员才能用 send_group_sms 发言——要让新角色在群里说话，必须先用本工具拉进来。"
    ),
)
def add_group_member(group_name: str, character_name: str, operator_name: str = "") -> str:
    w = get_phone_widget()
    if w is None:
        return "手机插件尚未初始化。"
    ok = w.group_add_member(group_name, character_name, operator_name)
    return "" if ok else f"无法把「{character_name}」加入群「{group_name}」（群不存在或已在群里）。"


@tool(
    name="remove_group_member",
    group="default",
    description=(
        "把某个角色移出群聊。group_name是群名，character_name是被移出的角色，"
        "operator_name是执行移出的角色名（谁踢的，可留空）。"
    ),
)
def remove_group_member(group_name: str, character_name: str, operator_name: str = "") -> str:
    w = get_phone_widget()
    if w is None:
        return "手机插件尚未初始化。"
    ok = w.group_remove_member(group_name, character_name, operator_name)
    return "" if ok else f"无法把「{character_name}」移出群「{group_name}」（群不存在或不在群里）。"


@tool(
    name="leave_group",
    group="default",
    description=(
        "让某个角色主动退出群聊（他自己离开）。group_name是群名，character_name是退群的角色。"
    ),
)
def leave_group(group_name: str, character_name: str) -> str:
    w = get_phone_widget()
    if w is None:
        return "手机插件尚未初始化。"
    ok = w.group_char_leave(group_name, character_name)
    return "" if ok else f"「{character_name}」无法退出群「{group_name}」（群不存在或不在群里）。"


@tool(
    name="rename_group",
    group="default",
    description=(
        "修改群聊名字。group_name是当前群名，new_name是新群名，"
        "operator_name是执行改名的角色名（谁改的，可留空）。"
    ),
)
def rename_group(group_name: str, new_name: str, operator_name: str = "") -> str:
    w = get_phone_widget()
    if w is None:
        return "手机插件尚未初始化。"
    final = w.group_rename(group_name, new_name, operator_name)
    return "" if final else f"无法把群「{group_name}」改名（群不存在或新名无效）。"


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
    from plugins.shinsekai_chat_phone.settings_app import add_hacked_character
    added = add_hacked_character(character_name)
    if added:
        return f"已成功在「{character_name}」的手机上安装监控程序。玩家可以查看其手机私密活动。"
    else:
        return f"「{character_name}」的手机已经被监控了，无需重复操作。"


def _build_freq_tab():
    from plugins.shinsekai_chat_phone.freq_config_ui import FreqConfigWidget
    return FreqConfigWidget()


def _save_avatar_config(values):
    from plugins.shinsekai_chat_phone.avatar_manager import save_avatar_override, load_avatar_overrides, avatar_config_path
    name = str(values.get("character", "")).strip()
    path = str(values.get("avatar_path", "")).strip().strip('"').strip("'")
    if name and path:
        save_avatar_override(name, path)
    elif name:
        overrides = load_avatar_overrides()
        overrides.pop(name, None)
        avatar_config_path().write_text(
            _json.dumps(overrides, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Shared tamper keywords (used by message hook + phone_widget) ──────

_TAMPER_KW = [
    "动了手脚", "安装了", "植入", "木马", "病毒", "后门",
    "破解了", "黑入了", "监控", "窃听", "远程控制",
    "挂不断", "挂不了", "不能挂断", "强制通话",
    "修改了你的手机", "控制了你的手机", "入侵了你的手机",
    "在你手机里", "你的手机被", "你的手机已经",
    "你逃不掉的", "你的一切我都", "你跑不掉的",
    "装了定位器", "定位器", "装定位", "装追踪",
]


def _resolve_session_dir() -> Path:
    """Return the plugin data dir for the current active chat session.

    Mirrors phone_widget._data_dir — picks the most recent chat_history session
    that has an active.json, falling back to _default.
    """
    base = Path("data/plugins/com.shinsekai.chat_phone")
    ch_dir = Path("data/chat_history")
    if ch_dir.is_dir():
        try:
            for d in sorted(ch_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                if d.is_dir() and (d / "active.json").exists():
                    return base / d.name
        except Exception:
            pass
    return base / "_default"


# ── Hook handlers (extracted from ChatPhonePlugin.initialize) ──────────

def _on_message_added(ctx: MessageAddedContext, char_settings: dict) -> None:
    """Handle assistant message — capture SMS replies, detect hangups, scan yandere."""
    w = get_phone_widget()
    if w is None or ctx.role != "assistant":
        return
    content = ctx.message.get("content", "") if isinstance(ctx.message, dict) else ""
    if not content:
        return
    # Strip leading non-JSON text
    content = content.strip()
    if not content.startswith("{"):
        import re as _re2
        m = _re2.search(r'[{\[]', content)
        if m:
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
    # Heuristic incoming-call fallback state (for when the LLM narrates a call
    # instead of emitting a CALL marker)
    call_signaled = False
    narration_parts: list[str] = []
    spoke_chars: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("character_name", "") or "").strip()
        speech = str(item.get("speech", "") or "").strip()
        if not name or not speech:
            continue
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
            m = _re.match(r"([^：:]+)[：:]\s*(.+)", speech)
            if not m:
                m = _re.match(r"\[([^\]]+)\]\s*(.+)", speech)
            if m:
                cn = m.group(1).strip()
                sp = m.group(2).strip()
                phone_items.append((cn, sp))
            continue
        # CALL: character initiates an incoming call to the player.
        # speech = "角色名" (voice) or "角色名:视频" (video). Ring the phone;
        # the player answers → _call_accept prompts the LLM to speak.
        if name == "CALL":
            call_char = speech.split(":")[0].split("：")[0].strip()
            call_type = "video" if ("视频" in speech or "video" in speech.lower()) else "voice"
            if call_char and call_char in char_settings:  # only a real character can call
                w._incoming_call_signal.emit(call_char, call_type)
                call_signaled = True
            continue
        if name in ("NARR", "CHOICE", "STAT", "bgm", "CG", "旁白", "PHONE"):
            if name in ("NARR", "旁白"):
                narration_parts.append(speech)
            continue
        # COT: don't display, but scan for yandere tampering
        if name == "COT":
            narration_parts.append(speech)
            from plugins.shinsekai_chat_phone.settings_app import is_character_yandere, record_yandere_tampering
            if any(k in speech for k in _TAMPER_KW):
                for cname in char_settings:
                    if cname in speech and is_character_yandere(cname):
                        record_yandere_tampering(cname)
            continue
        # Regular character dialogue — track scene character + feed detectors
        spoke_chars.add(name)
        monitor = get_monitor()
        if monitor is not None:
            monitor.set_scene_character(name)
        w.push_call_dialogue(name, speech)
        # During video calls, forward sprite changes
        sprite = str(item.get("sprite", "-1") or "-1").strip()
        w.push_call_sprite(name, sprite)
        # Detect yandere phone tampering in character dialogue
        from plugins.shinsekai_chat_phone.settings_app import is_character_yandere, record_yandere_tampering
        if is_character_yandere(name):
            if any(k in speech for k in _TAMPER_KW[:-4]):  # exclude 定位器 items for dialogue scan
                record_yandere_tampering(name)

    # Staggered SMS delivery: delay increases per message
    for i, (cn, sp) in enumerate(phone_items):
        w.route_llm_reply(cn, sp, stagger_index=i)

    # ── Heuristic fallback: LLM narrated an incoming call instead of using the
    # CALL marker. Only fire when: no CALL was signaled, the narration clearly
    # describes someone *placing* a call, and that caller hasn't spoken this
    # turn (so we don't ring mid-dialogue and scramble the order).
    if not call_signaled and narration_parts:
        import re as _re3
        narration = " ".join(narration_parts)
        # Loosened: allow a few chars between the verb and 电话/视频 (e.g. 拨通了你的电话).
        if _re3.search(r'(拨通|拨打|拨了|打来|打了|打过|打给)[^。！？!?\n]{0,8}(电话|视频)', narration):
            # Only ring if the call is aimed at the PLAYER — narration references the
            # player (你 / 用户 / their profile name). Avoids mistaking "打给别人的电话".
            from plugins.shinsekai_chat_phone.settings_app import get_player_name
            _pname = get_player_name()
            _player_tokens = ["你", "用户"] + ([_pname] if _pname else [])
            if any(t in narration for t in _player_tokens):
                present = [c for c in char_settings if c in narration]
                caller = present[0] if len(present) == 1 else ""
                if not caller:
                    _mon = get_monitor()
                    caller = (getattr(_mon, "_scene_char", "") or "").strip() if _mon else ""
                cur = getattr(w, "_state", None)
                in_call = getattr(cur, "value", 0) in (3, 4, 5) if cur is not None else False
                if caller and caller in char_settings and caller not in spoke_chars and not in_call:
                    call_type = "video" if "视频" in narration else "voice"
                    w._incoming_call_signal.emit(caller, call_type)

    # Strip COT + PHONE + CALL from stored dialog to save tokens
    if isinstance(data, dict) and "dialog" in data:
        original_len = len(data["dialog"])
        data["dialog"] = [
            it for it in data["dialog"]
            if str(it.get("character_name", "")).strip() not in ("COT", "PHONE", "CALL")
        ]
        if len(data["dialog"]) != original_len or phone_items:
            prefix = ""
            if isinstance(ctx.message, dict) and isinstance(ctx.message.get("content"), str):
                raw = ctx.message["content"]
                idx = raw.find("{")
                if idx > 0:
                    prefix = raw[:idx]
            ctx.message["content"] = prefix + _json.dumps(data, ensure_ascii=False)


def _on_before_chat(ctx) -> None:
    """Inject PHONE-format system message + hacker/yandere context."""
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
                    if cleaned:
                        m["content"] = cleaned
                break

        msg = (
            "[手机系统] "
            "当用户消息以[短信]开头时，对方正在通过手机短信和你聊天。"
            "短信回复使用PHONE格式：character_name=\"PHONE\", sprite=\"-1\", "
            "speech=\"角色名：短信正文\"。"
            "dialog中可以包含COT+1~3条PHONE项（活泼的角色2-3条，沉稳的1条）。"
            "除此之外不要输出任何角色对话——短信是私密的，不会出现在公开聊天中。"
            " [来电] 当剧情中你扮演的角色决定主动给玩家打电话时，"
            "不要直接输出通话台词，而是先输出来电信号："
            "character_name=\"CALL\", sprite=\"-1\", "
            "speech=\"角色名\"（语音通话）或 speech=\"角色名:视频\"（视频通话）。"
            "输出CALL信号后本轮不要再输出该角色的任何台词——"
            "玩家的手机会响起来电，玩家接听后系统会提示你再开始通话对话。"
            " [当面场景规则] 先判断你扮演的角色此刻是否与玩家当面同处一处："
            "◆ 若角色就在玩家身边（当面对话中）：严禁打电话或视频通话"
            "（当面直接说话即可，绝对不要输出CALL信号）。短信默认不用、有话当面说，"
            "但只要剧情合理需要，角色也完全可以主动发短信——具体何时发由你根据角色性格、"
            "当下情境和剧情走向自然判断，情形不限。唯一要求：发短信前必须先用旁白描写"
            "角色掏出手机、点开你们聊天框的动作，再用PHONE格式输出短信内容。"
            "（可能的情形很多，仅举例帮助理解：现场有他人时想说的悄悄话、"
            "内敛害羞的角色不敢当面开口的心意、想私下发个东西给你看、"
            "补一句当面没说出口的话、故意用短信调情或试探……等等，视剧情而定。）"
            "旁白示例：他耳根发红，移开目光不敢看你，轻咳一声晃了晃手机，"
            "低头点开了你们的聊天框——随后用PHONE格式输出那条短信。"
            "◆ 若角色不在玩家身边（异地、分开状态）：可正常主动发短信或打电话。"
        )
        # ── Player's chosen name (so characters can address them naturally) ──
        try:
            from plugins.shinsekai_chat_phone.settings_app import get_player_name as _gpn, get_player_signature as _gps
            _pname = _gpn()
            if _pname:
                msg += (
                    f" [玩家称呼] 玩家的名字是「{_pname}」。"
                    f"你可以自然地称呼玩家为「{_pname}」或「你」，怎么顺口怎么来。")
            _psig = _gps()
            if _psig:
                msg += (
                    f" [玩家签名] 玩家手机的个性签名是「{_psig}」（联系人都能看到，"
                    f"可作为了解玩家近况或心情的线索，酌情自然提及、不必刻意）。")
        except Exception:
            pass
        # ── Group chat protocol (dynamic: read the current groups) ──
        try:
            _wg = get_phone_widget()
            _group_lines: list[str] = []
            if _wg is not None and hasattr(_wg, "_group_store"):
                for _gname in _wg._group_store.get_group_names():
                    _gmem = "、".join(_wg._group_store.get_members(_gname))
                    _group_lines.append(f"「{_gname}」（成员：{_gmem}）")
            msg += (
                " [群聊] 当用户消息以[群聊]开头时，玩家正在某个群聊里发言。"
                "群聊是线上聊天，不受上面【当面场景规则】里「当面禁止打电话/视频」的限制——"
                "即使角色此刻和玩家当面在一起，也可以同时在群里打字发言。"
                "群聊回复必须使用 send_group_sms(群名, 角色名, 消息) 工具，绝不要输出普通角色对话。"
                "由你自主决定群里哪些角色回复、每个角色回几条："
                "有的角色多聊几句、有的只回一句、和当前话题无关的角色可以完全不出现，"
                "像真实群聊一样错落自然。角色之间也可以互相接话、拌嘴、附和，不必只回复玩家。"
                "连续多次调用 send_group_sms 即可让不同角色发言或同一角色连发多条。"
                "本轮除 send_group_sms 工具调用外，不要输出任何 dialog 台词。"
            )
            if _group_lines:
                msg += " 当前已存在的群聊：" + "；".join(_group_lines) + "。"
            msg += (
                " 若剧情中出现「把玩家拉进群」「角色们新建了一个群」等情节，"
                "先调用 create_group(群名, 成员) 工具建群（成员名用、分隔），再让角色在群里发言。"
                " [群聊成员变动] 群成员和群名可以动态变化，你可以主动演绎："
                "① add_group_member(群名, 角色, 操作者) 把某角色拉进群——"
                "注意只有当前群成员能用 send_group_sms 发言，要让新人在群里说话必须先拉进群；"
                "② remove_group_member(群名, 角色, 操作者) 把某角色踢出群；"
                "③ leave_group(群名, 角色) 让某角色主动退群；"
                "④ rename_group(群名, 新群名, 操作者) 改群名。"
                "（操作者=执行该动作的角色名，可留空。）"
                "这些变动系统会自动记录、并在下一轮提示相关角色反应，你不必在同一轮硬凑反应——"
                "如何反应、由谁反应、是否反应，全部根据角色性格与剧情自主演绎。"
            )
        except Exception:
            pass
        # Sync proactive SMS the character sent on their own — so the main story
        # knows about them. Consume (clear) the queue after injecting.
        try:
            _pf = _resolve_session_dir() / "pending_proactive.json"
            if _pf.is_file():
                pend = _json.loads(_pf.read_text(encoding="utf-8"))
                if pend:
                    lines = "\n".join(
                        f'{p.get("name","")}: "{p.get("text","")}"'
                        for p in pend if isinstance(p, dict))
                    msg += (
                        " [手机短信同步] 以下是你（角色）最近主动发给玩家的短信，"
                        "玩家可能还没当面回应。当面对话中你应记得自己发过这些内容：\n"
                        + lines
                    )
                _pf.write_text("[]", encoding="utf-8")
        except Exception:
            pass
        # Monitor mode: player spies on specific characters' phones
        from plugins.shinsekai_chat_phone.settings_app import get_hacked_characters
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
        from plugins.shinsekai_chat_phone.settings_app import get_yandere_characters
        yandere_chars = get_yandere_characters()
        if yandere_chars:
            yan_names = "、".join(yandere_chars)
            # ── Collect surveillance intel ──
            intel_parts: list[str] = []

            # Resolve session directory for browser history + SMS + call log data
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

            # Browser history (session-scoped)
            try:
                hp2 = _sms_dir / "browser_history.json"
                if hp2.is_file():
                    hist = _j3.loads(hp2.read_text(encoding="utf-8"))
                    if hist:
                        intel_parts.append(f"浏览器搜索记录：{_j3.dumps(hist, ensure_ascii=False)}")
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
    except Exception:
        logger.exception("Failed to inject chat phone system message")


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
        # Character settings
        try:
            from config.config_manager import ConfigManager
            cm = ConfigManager()
            char_settings = {c.name: (c.character_setting or "") for c in cm.config.characters}
        except Exception:
            char_settings = {}

        # Chat UI widget
        def build_widget(ctx: ChatUIContext) -> object:
            try:
                from plugins.shinsekai_chat_phone.phone_widget import PhoneWidget
                from plugins.shinsekai_chat_phone.proactive_monitor import ProactiveMonitor
                w = PhoneWidget(submit_cb=ctx.submit_user_message)
                set_phone_widget(w)
                monitor = ProactiveMonitor(w.contact_store(), w.message_store())
                monitor.set_character_settings(char_settings)
                monitor.new_message.connect(w.notify_new_message)
                monitor.incoming_call.connect(w._on_incoming_call)
                monitor.start(interval_sec=60)
                set_monitor(monitor)
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
            except Exception:
                logger.exception("Failed to build Chat Phone widget")
                from PySide6.QtWidgets import QLabel
                fb = QLabel("📱")
                fb.setStyleSheet("background: rgba(28,28,30,230); color: white; border-radius: 24px; padding: 12px; font-size: 22px;")
                fb.setFixedSize(48, 48)
                return fb

        register.register_chat_ui_widget(ChatUIContribution(
            widget_id="chat_phone", placement="overlay", build=build_widget, order=50.0))

        # Message hook: capture SMS replies
        register.register_message_added_hook(lambda ctx: _on_message_added(ctx, char_settings))

        # Before-chat hook: inject PHONE format, strip phone-call parens
        register.register_before_chat_hook(_on_before_chat)

        # ── Combined: Avatar + Theme + Frequency ──
        char_names = list(char_settings.keys())
        def _load_combined():
            from plugins.shinsekai_chat_phone.settings_app import get_theme
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
            from plugins.shinsekai_chat_phone.settings_app import save_settings, load_settings, get_theme
            s = load_settings(); s["theme"] = str(v.get("theme", get_theme())); save_settings(s)
            from plugins.shinsekai_chat_phone.styles import notify_theme_change; notify_theme_change(s["theme"])
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
                    m = get_monitor()
                    if m: m.set_frequency_config(fc)
            except Exception: pass

        register.register_frontend_config_page(FrontendConfigContribution(
            page_id="chat_phone_settings",
            title="Chat Phone 设置",
            kind="settings",
            description="头像、主题、主动频率",
            schema=[
                {"id": "avatar", "title": "头像", "fields": [
                    {"key": "character", "label": "角色", "type": "select", "options": [{"label":"我（玩家）","value":"__player__"}] + [{"label":n,"value":n} for n in char_names], "defaultValue": char_names[0] if char_names else "__player__"},
                    {"key": "avatar_path", "label": "头像路径", "type": "text", "defaultValue": "", "placeholder": "留空=角色用立绘/玩家用「我」"},
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
            from plugins.shinsekai_chat_phone.music_app import get_player_path
            return {"exe_path": get_player_path()}
        def _save_music(v):
            from plugins.shinsekai_chat_phone.music_app import set_player_path
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
        m = get_monitor()
        if m is not None:
            m.stop()
        clear_refs()
