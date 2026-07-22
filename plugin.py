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


# ── LLM tool: send SMS as an unknown/stranger number ──────────────────

@tool(
    name="send_sms_stranger",
    group="default",
    description=(
        "以「未知联系人」身份给玩家发短信——当角色还没和玩家交换联系方式、"
        "但剧情里他已通过某种途径（手段不限、可含非法方式，自行演绎）拿到玩家号码时用。"
        "character_name是发信角色名，message是短信正文。玩家侧会显示为「未知联系人」、"
        "真名隐藏，直到正式 exchange_contacts 才显示真名并升级为正常联系人。"
    ),
)
def send_sms_stranger(character_name: str, message: str) -> str:
    w = get_phone_widget()
    if w is None:
        return "手机插件尚未初始化。"
    w.route_llm_reply(character_name, message, known=False)
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


# ── LLM tools: moments (朋友圈) ─────────────────────────────────────────

def _coerce_pid(x) -> int:
    """Coerce a tool-supplied post id ('#12' / '12' / 12) to int; 0 on failure."""
    try:
        return int(str(x).strip().lstrip("#"))
    except Exception:
        return 0


@tool(
    name="post_moment",
    group="default",
    description=(
        "以某个角色的身份发一条朋友圈动态。character_name是发动态的角色名，text是动态正文。"
        "image_desc可选，是这条动态配图的简短文字描述（如「海边的晚霞」）——"
        "本期只作为文字占位显示、不会生成真实图片，不需要配图就留空。"
        "角色想在朋友圈发状态、晒近况、抒发心情时调用。"
    ),
)
def post_moment(character_name: str, text: str, image_desc: str = "") -> str:
    w = get_phone_widget()
    if w is None:
        return "手机插件尚未初始化。"
    pid = w.post_moment_from_llm(character_name, text, image_desc)
    return f"已发布动态 #{pid}。" if pid else "发布失败。"


@tool(
    name="comment_moment",
    group="default",
    description=(
        "以某个角色的身份评论一条朋友圈动态。post_id是被评论动态的编号"
        "（[朋友圈]提示里每条动态前的 #数字；想评论最新一条就用其中最大的编号）。"
        "character_name是评论的角色名，text是评论内容。"
        "reply_to可选：如果这条不是评论动态本身、而是回复动态下某人的评论，就填被回复者的名字"
        "（回复玩家填「玩家」，回复某角色填角色名）——界面会显示成「谁 回复 谁」。"
        "角色之间也可以互相评论、接话——多次调用即可让不同角色评论或来回对话。"
    ),
)
def comment_moment(post_id: str, character_name: str, text: str, reply_to: str = "") -> str:
    w = get_phone_widget()
    if w is None:
        return "手机插件尚未初始化。"
    w.route_moment_comment(_coerce_pid(post_id), character_name, text, reply_to)
    return ""


@tool(
    name="like_moment",
    group="default",
    description=(
        "以某个角色的身份给一条朋友圈动态点赞。post_id是动态编号"
        "（[朋友圈]提示里每条动态前的 #数字）。character_name是点赞的角色名。"
    ),
)
def like_moment(post_id: str, character_name: str) -> str:
    w = get_phone_widget()
    if w is None:
        return "手机插件尚未初始化。"
    w.moment_like_from_llm(_coerce_pid(post_id), character_name)
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

    # ── 场景状态维护：在场角色一直保持在场，直到「转场/时间跳跃」或「有人离开」才释放。
    # 主动监控据此绝不给当面在场的角色发短信（保守检测——宁可漏放、不误清，以免又骚扰在场角色）。
    _mon_scene = get_monitor()
    if _mon_scene is not None:
        try:
            import re as _re6
            _narr = " ".join(narration_parts)
            _last_user = ""
            for _m in reversed(getattr(ctx, "messages", None) or []):
                if isinstance(_m, dict) and _m.get("role") == "user" and isinstance(_m.get("content"), str):
                    _last_user = _m["content"]
                    break
            # 玩家显式移动（开场括号动作）或旁白明确的时间跳跃/换地点 → 视为转场
            _player_moved = bool(_re6.match(
                r'^\s*[（(]\s*(?:去|前往|赶去|赶往|离开|回家|回到|出门|走出|回房|回公寓|回住处)', _last_user))
            _TRANSITION_KW = ("第二天", "次日", "翌日", "隔天", "几天后", "数日后", "一周后", "一个月后",
                              "几小时后", "半小时后", "场景切换", "转场",
                              "回到家", "回到房间", "回到公寓", "回到住处", "回到自己的")
            if _player_moved or any(k in _narr for k in _TRANSITION_KW):
                _mon_scene.clear_scene()              # 上一场景结束
                for _s in spoke_chars:                # 新场景的当面角色 = 本轮说话的人
                    _mon_scene.set_scene_character(_s)
            # 有人离开：旁白里「X 离开/走了/告辞…」→ 把 X 移出在场（其余人仍在场）
            for _cn in char_settings:
                if _re6.search(
                    rf'{_re6.escape(_cn)}[^。！？!?\n]{{0,6}}(?:离开|走了|离去|告辞|离席|先走|先行离|转身离|起身离|扬长而去)',
                    _narr,
                ):
                    _mon_scene.remove_scene_character(_cn)
        except Exception:
            pass

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
            _player_tokens = ["你", "用户", "玩家"] + ([_pname] if _pname else [])
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

    # ── Heuristic fallback: LLM narrated a stranger/unknown-contact SMS in 旁白/COT
    # instead of calling send_sms_stranger. Recover the message body + attribute the
    # sender, then deliver so it actually lands in the SMS app. Only fires when the
    # sender is a single, unambiguous roster character.
    if narration_parts:
        import re as _re4
        _narr = " ".join(narration_parts)
        _mm = _re4.search(
            r'(?:未知联系人|陌生号码|未知号码|陌生人|陌生短信)[^「『"（(]{0,10}[「『"]([^」』"]{1,200})[」』"]',
            _narr,
        )
        if _mm:
            _stranger_msg = _mm.group(1).strip()
            _sms_cue = (r'(?:未知联系人|发来短信|发短信|发条短信|发了短信|发送短信|'
                        r'拿到[^。！？!?\n]{0,6}号码|要到[^。！？!?\n]{0,6}号码|搞到[^。！？!?\n]{0,6}号码)')
            _cands: set[str] = set()
            for _cn in char_settings:
                _cn = (_cn or "").strip()
                if not _cn:
                    continue
                _al = {_cn}
                if len(_cn) >= 4:
                    _al.add(_cn[:2]); _al.add(_cn[-2:])
                elif len(_cn) == 3:
                    _al.add(_cn[-2:])
                _alt = "|".join(_re4.escape(a) for a in _al if len(a) >= 2)
                if not _alt:
                    continue
                if (_re4.search(rf'(?:{_alt})[^。！？!?\n]{{0,20}}{_sms_cue}', _narr)
                        or _re4.search(rf'{_sms_cue}[^。！？!?\n]{{0,20}}(?:{_alt})', _narr)):
                    _cands.add(_cn)
            _sender = next(iter(_cands)) if len(_cands) == 1 else ""
            if _sender and _sender not in spoke_chars and _stranger_msg:
                logger.info("Recovered narrated stranger SMS -> %s: %s", _sender, _stranger_msg[:40])
                w.route_llm_reply(_sender, _stranger_msg, known=False)

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


# ── opening-scene contact seeding ─────────────────────────────────────

# 联系方式声明的线索词（开场从「用户情景」/首条消息里确定性播种联系人用）
_CONTACT_KW = r"(?:联系方式|联络方式|号码|微信|电话号)"
_HOLD_VERB = r"(?:只?有|留了?|存了?|加了?|保存了?|存着|留着)"
_DROP_VERB = r"(?:删|拉黑|屏蔽|移除)"


def _opening_char_aliases(roster: list[str]) -> dict[str, str]:
    """构造「别名 -> 角色名」映射；跨角色歧义的别名剔除，避免误配。

    别名候选 = 全名 + 常见简称（四字名取前两字/后两字，如 房石阳明→房石、坂田银时→银时）。
    """
    counts: dict[str, list[str]] = {}
    for name in roster:
        name = (name or "").strip()
        if not name:
            continue
        cands = {name}
        if len(name) >= 4:
            cands.add(name[:2])
            cands.add(name[-2:])
        elif len(name) == 3:
            cands.add(name[-2:])
        for alias in cands:
            if len(alias) >= 2:
                counts.setdefault(alias, [])
                if name not in counts[alias]:
                    counts[alias].append(name)
    return {alias: names[0] for alias, names in counts.items() if len(names) == 1}


def _seed_contacts_from_opening(ctx) -> None:
    """从开场设定确定性播种手机联系人（纯插件侧，绕开首轮工具预算）。

    仅当通讯录为空时运行（播种后自然不再触发，也能自愈空存档）。扫描来源两路并集：
    - 全部 system 消息（覆盖填进「用户情景」字段、被拼入系统提示的设定）；
    - 第一条 user 消息（覆盖直接打字进开场消息的设定）；
    - 兜底：`_temp_split.json` 的 scenario 字段（用户情景的权威副本）。
    用角色名锚定 + 联系方式关键词共现判定，故不会误读工具说明里的泛指「角色…联系方式」。
    玩家声明「有/加了…联系方式」→ 建联系人；声明「删了/拉黑/没有…」→ 跳过。
    """
    import re
    try:
        w = get_phone_widget()
        if w is None:
            return
        store = w.contact_store()
        if store.get_contacts():
            return  # 已有联系人，不重复播种

        parts: list[str] = []
        first_user_seen = False
        for m in getattr(ctx, "messages", None) or []:
            if not isinstance(m, dict):
                continue
            content = m.get("content")
            if not isinstance(content, str) or not content:
                continue
            role = m.get("role")
            if role == "system":
                parts.append(content)
            elif role == "user" and not first_user_seen:
                parts.append(content)
                first_user_seen = True
        try:
            _sp = Path("data/character_templates/_temp_split.json")
            if _sp.is_file():
                _sc = _json.loads(_sp.read_text(encoding="utf-8")).get("scenario")
                if isinstance(_sc, str) and _sc:
                    parts.append(_sc)
        except Exception:
            pass
        text = "\n".join(parts)
        if not text:
            return

        try:
            from config.config_manager import ConfigManager
            roster = [c.name for c in ConfigManager().config.characters if (c.name or "").strip()]
        except Exception:
            roster = []
        if not roster:
            return

        alias_to_name = _opening_char_aliases(roster)

        # 按「小句」判定，比逐名锚定更稳：
        # 切句时【保留顿号】，让「A、B 的联系方式」这类名字列表留在同一小句；
        # 每个提到「联系方式」的小句先判正/负极性，再把该句里出现的角色按极性归类。
        # 例：「我有乌尔比安、银时的联系方式」→ 正（乌尔比安+银时）；
        #     「房石的联系方式还没有」→ 负（还没→房石不建）。
        _CONTACT_KWS = ("联系方式", "联络方式", "号码", "微信", "电话号")
        _NEG_MARKS = ("没", "未", "尚未", "删", "拉黑", "屏蔽", "移除", "还没", "不知道", "丢了", "找不到")
        seed_names: set[str] = set()
        drop_names: set[str] = set()
        for clause in re.split(r"[。，；！？!?\n]", text):
            if not any(k in clause for k in _CONTACT_KWS):
                continue
            is_neg = any(n in clause for n in _NEG_MARKS)
            for alias, name in alias_to_name.items():
                if alias in clause:
                    (drop_names if is_neg else seed_names).add(name)

        seeded: list[str] = []
        for name in sorted(seed_names - drop_names):  # 删除/否定声明胜过持有
            if store.add_contact(name, known=True):
                seeded.append(name)

        if seeded:
            # 仅写数据；不在此 worker 线程直接碰 Qt 控件（proactive 直接读 store，
            # UI 在下次打开短信时自然刷新）。
            logger.info("Seeded contacts from opening scenario: %s", "、".join(seeded))
    except Exception:
        logger.exception("seed contacts from opening failed")


# 开场若声明「过去收到过短信」的检测（只扫用户开场+scenario，不扫系统提示——
# 否则会命中工具说明里的「未知联系人/短信」而永远误触发）
_INTRO_SMS_RE = None  # 延迟编译


def _maybe_seed_intro_sms(ctx) -> None:
    """开场声明「手机里已有/过去收到过（未知）短信」时，插件生成一条并按未知联系人投递。

    背景短信的正文需要内容，确定性代码生成不了；而主模型受首轮工具预算限制、且「未知联系人」
    匿名难归属，常只在旁白里含糊带过。这里用轻量 LLM 调用（复用 sms_llm，独立 API、绕开主
    模型预算）自拟一条正文，选一个「未建联系人」的角色作发信人，known=False 显示为未知联系人。
    每存档只跑一次（marker）；已有任何短信则跳过（避免与主模型 send_sms_stranger 重复）。
    """
    import re
    global _INTRO_SMS_RE
    try:
        w = get_phone_widget()
        if w is None:
            return
        dd = getattr(w, "_data_dir", None)
        marker = (dd / "_intro_sms_done") if dd is not None else None
        if marker is not None and marker.exists():
            return

        # 只扫「首条 user 消息 + _temp_split.json scenario」
        parts: list[str] = []
        for m in getattr(ctx, "messages", None) or []:
            if isinstance(m, dict) and m.get("role") == "user" and isinstance(m.get("content"), str):
                parts.append(m["content"])
                break
        try:
            _sp = Path("data/character_templates/_temp_split.json")
            if _sp.is_file():
                _sc = _json.loads(_sp.read_text(encoding="utf-8")).get("scenario")
                if isinstance(_sc, str) and _sc:
                    parts.append(_sc)
        except Exception:
            pass
        opening = "\n".join(parts)
        if not opening:
            return
        if _INTRO_SMS_RE is None:
            _INTRO_SMS_RE = re.compile(
                r"(?:未知联系人|陌生号码|陌生人|陌生短信)"
                r"|(?:收到|收过|发来|发过|来过|给我发|发给我)[^。！？!?\n]{0,8}(?:短信|消息|信息)"
            )
        if not _INTRO_SMS_RE.search(opening):
            return

        ms = w.message_store()
        try:
            from config.config_manager import ConfigManager
            chars = [(c.name, (c.character_setting or ""))
                     for c in ConfigManager().config.characters if (c.name or "").strip()]
        except Exception:
            chars = []
        if not chars:
            return
        # 已有任何短信 → 主模型/之前已投递，别重复
        if any(ms.get_messages(n) for n, _ in chars):
            return
        known = set(w.contact_store().get_contacts())
        cands = [(n, s) for n, s in chars if n not in known]
        if not cands:
            return
        # 选发信人：优先设定里暗示对玩家有兴趣/暧昧/病娇的，否则第一个未建联系人
        cands.sort(key=lambda it: sum(k in it[1] for k in
                   ("暧昧", "喜欢", "占有", "病娇", "执着", "兴趣", "追求", "痴迷")), reverse=True)
        sender, setting = cands[0]

        if marker is not None:
            try:
                marker.write_text("1", encoding="utf-8")  # 先置位，避免并发/重入重复生成
            except Exception:
                pass

        import threading

        def _run():
            try:
                from plugins.shinsekai_chat_phone.sms_llm import _call_llm
                reply = _call_llm(
                    sender, setting,
                    "这是你第一次用【未知号码】给对方发短信（对方还没存你的号码，在对方那里显示为未知联系人）。"
                    "结合你的性格写一条简短开场白（一两句），可带点悬念或试探，但不要报出真名。",
                    [],
                    initiate=True,
                )
                r = (reply or "").strip().strip("「」『』\"'")
                if r and len(r) > 1 and not r.startswith("["):
                    logger.info("Intro SMS generated from %s (unknown)", sender)
                    w.route_llm_reply(sender, r, known=False)
            except Exception:
                logger.exception("intro sms generation failed")

        threading.Thread(target=_run, daemon=True, name="intro-sms").start()
    except Exception:
        logger.exception("maybe seed intro sms failed")


def _reset_phone_data(w) -> None:
    """清空本存档手机数据（内存 + 文件），用于新开存档。

    不做 Qt UI 刷新（本函数跑在 LLM worker 线程；UI 在下次打开手机时自然读到空状态）。
    每步独立 try/except，尽量清干净、任何一步失败不影响其余。头像等资产缓存保留。
    """
    import contextlib
    with contextlib.suppress(Exception):
        cs = w.contact_store()
        for n in list(cs.get_contacts()):
            cs.remove_contact(n)
    with contextlib.suppress(Exception):
        w.message_store()._messages.clear()
    with contextlib.suppress(Exception):
        ma = w._messages_app
        ma._own_messages.clear()
        ma._previews.clear()
    with contextlib.suppress(Exception):
        gs = w._group_store
        gs._groups.clear()
        gs._msg_idx = 0
        gs._save()
    with contextlib.suppress(Exception):
        ms = w._moments_store
        ms._posts.clear()
        ms._post_idx = 0
        ms._comment_idx = 0
        ms._save()
    with contextlib.suppress(Exception):
        import shutil
        imgdir = getattr(w, "_moments_images", None)
        if imgdir is not None and imgdir.is_dir():
            shutil.rmtree(imgdir, ignore_errors=True)
    dd = getattr(w, "_data_dir", None)
    if dd is not None:
        for fn in ("messages.json", "groups.json", "moments.json", "call_log.json",
                   "video_call_log.json", "pending_proactive.json", "browser_history.json",
                   "_intro_sms_done"):
            with contextlib.suppress(Exception):
                p = dd / fn
                if p.is_file():
                    p.unlink()
    logger.info("Phone data reset for new game")


def _maybe_reset_phone_on_new_game(ctx) -> None:
    """新开存档时清空手机数据。

    判定：本轮对话里「有开场 user 消息、但还没有任何 assistant 回合」→ 全新一局的第一轮。
    继续存档必然已有 assistant 消息，因此绝不会误清正在进行的存档。仅在确有旧数据时动作。
    """
    try:
        w = get_phone_widget()
        if w is None:
            return
        msgs = getattr(ctx, "messages", None) or []
        has_user = any(isinstance(m, dict) and m.get("role") == "user" for m in msgs)
        has_assistant = any(isinstance(m, dict) and m.get("role") == "assistant" for m in msgs)
        if not has_user or has_assistant:
            return  # 继续存档 / 尚无开场 → 不清
        try:
            has_data = bool(w.contact_store().get_contacts()) or bool(w.message_store()._messages)
        except Exception:
            has_data = False
        if has_data:
            _reset_phone_data(w)
    except Exception:
        logger.exception("maybe reset phone on new game failed")


def _on_before_chat(ctx) -> None:
    """Inject PHONE-format system message + hacker/yandere context."""
    try:
        # 新开存档：先清空旧手机数据（仅新局第一轮触发），再按开场设定播种联系人
        _maybe_reset_phone_on_new_game(ctx)
        # 开场从设定/首条消息确定性播种联系人（须在注入 [手机系统] 之前，避免扫到自身注入内容）
        _seed_contacts_from_opening(ctx)
        # 开场若声明「过去收到过（未知）短信」，插件自拟一条并按未知联系人投递（每存档一次）
        _maybe_seed_intro_sms(ctx)
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
            "短信回复必须调用 send_sms(角色名, 短信正文) 工具——可连续多次调用发多条"
            "（活泼的角色2-3条、沉稳的1条）；若还没和玩家交换过联系方式则用 send_sms_stranger。"
            "绝不要把短信正文写进 dialog（PHONE项/旁白/普通台词都会显示在主舞台上）——"
            "短信是私密的，只走工具、不出现在公开聊天里。"
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
            "当下情境和剧情走向自然判断，情形不限。可以先用旁白描写"
            "角色掏出手机、点开你们聊天框的动作，但短信正文本身必须调用 send_sms"
            "（未交换联系方式则 send_sms_stranger）工具投递，绝不写进 dialog。"
            "（可能的情形很多，仅举例帮助理解：现场有他人时想说的悄悄话、"
            "内敛害羞的角色不敢当面开口的心意、想私下发个东西给你看、"
            "补一句当面没说出口的话、故意用短信调情或试探……等等，视剧情而定。）"
            "旁白示例：他耳根发红，移开目光不敢看你，轻咳一声晃了晃手机，"
            "低头点开了你们的聊天框——随后调用 send_sms 工具发出那条短信。"
            "◆ 若角色不在玩家身边（异地、分开状态）：可正常主动发短信或打电话。"
            " [未知联系人] 若角色还没和玩家交换联系方式（没做过 exchange_contacts），"
            "但剧情里他通过某种手段（不限、可含非法方式，自行演绎）拿到了玩家号码，"
            "可用 send_sms_stranger 给玩家发短信——玩家会看到「未知联系人」（不显示真名），"
            "增添悬念；正式加好友仍用 exchange_contacts（届时升级为正常联系人、显示真名）。"
        )
        msg += (
            " [开场通讯录] 故事开场/设定阶段，若玩家声明「已持有／已加／留了某角色的联系方式」，"
            "请把该角色视为手机联系人——如尚未在通讯录中，本轮优先调用 exchange_contacts(角色名) 补登"
            "（此类补登优先于 search_tools 等其他工具）；若玩家声明「已删除／拉黑／没有」某角色的联系方式，"
            "则不要补登、也不要主动联系该角色。"
        )
        msg += (
            " [短信投递铁律] 极其重要：当剧情里某角色要给玩家发短信（不是玩家先在手机里发起的[短信]对话），"
            "短信正文必须通过【工具】投递，绝对不能写进 dialog——旁白/NARR/普通台词/PHONE 项都不行。"
            "原因：写进 dialog 会显示在主舞台的公开对话里（PHONE 项同样会露出来），而且不会真正到达手机短信。具体："
            "已是联系人→调用 send_sms(角色名, 短信正文)；未交换联系方式但已拿到玩家号码→调用 send_sms_stranger(角色真名, 短信正文)。"
            "可连续多次调用发多条。反例（禁止）：character_name=\"旁白\" 或 \"PHONE\"，speech=\"未知联系人：「……」\"。"
            "你可以用旁白描写「手机屏幕亮起、一条短信进来」的氛围，但短信正文本身只能走 send_sms / send_sms_stranger 工具。"
            " 【玩家指令】当玩家消息里出现「（xx给我发短信）」「（xx给我发消息）」「（让xx发短信）」这类括号指令时，"
            "就是要 xx 主动给玩家发短信——直接用上述工具投递（已建联系人用 send_sms、未建用 send_sms_stranger），"
            "同样不要写进 dialog（旁白/PHONE 都不行）。"
        )
        msg += (
            " [开场历史短信] 若玩家开场设定里提到手机里「已有／过去收到过」某条短信（尤其未知联系人发来的），"
            "系统会自动把那条短信补进手机短信 App——你【不要】在 dialog 里再重复输出那条短信的正文，"
            "也不必调工具补它；你只需在剧情里自然承接「玩家手机里确实有这样一条短信」。"
            "之后剧情中【新】产生的短信，仍按上面的[短信投递铁律]用 send_sms / send_sms_stranger 工具。"
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
        # ── Moments (朋友圈) protocol (dynamic: read recent posts) ──
        try:
            _wm = get_phone_widget()
            _moment_lines: list[str] = []
            if _wm is not None and hasattr(_wm, "_moments_store"):
                for _p in _wm._moments_store.get_posts()[-6:]:
                    _who = "我" if _p.get("author") == "__player__" else _p.get("author", "")
                    _body = (_p.get("text", "") or "").replace("\n", " ")[:30]
                    _img = "[图]" if (_p.get("image") or _p.get("image_desc")) else ""
                    _nl = len(_p.get("likes", [])); _nc = len(_p.get("comments", []))
                    _cm = ""
                    if _p.get("comments"):
                        _last = _p["comments"][-1]
                        _cw = "我" if _last.get("is_user") else _last.get("author", "")
                        _cm = f" 最近评论 {_cw}：{(_last.get('text', '') or '')[:16]}"
                    _moment_lines.append(
                        f"#{_p.get('id')} [{_who}]“{_body}”{_img}（赞{_nl} 评{_nc}）{_cm}")
            msg += (
                " [朋友圈] 当用户消息以[朋友圈]开头时，玩家在朋友圈发了动态、或点赞/评论了某条动态。"
                "朋友圈是线上社交，不受上面【当面场景规则】的限制——即使当面在一起也能刷、能评。"
                "你可以让相关角色用 post_moment(角色, 正文) 发动态、comment_moment(编号, 角色, 内容) 评论、"
                "like_moment(编号, 角色) 点赞来回应；角色之间也可以互相评论、接话。"
                "如果是回复动态下某个人的评论（而不是评论动态本身），在 comment_moment 里加 reply_to=被回复者的名字"
                "（回复玩家就填「玩家」），会显示成「谁 回复 谁」。"
                "由你自主决定谁回应、回几条、是否回应——不感兴趣的角色可以完全不理。"
                "引用某条动态时用它的 #编号。本轮除这些工具调用外，不要输出任何 dialog 台词。"
            )
            if _moment_lines:
                msg += (" 当前朋友圈近况（供参考，不必每轮都发动态；仅在剧情合适时才用 post_moment）："
                        + "；".join(_moment_lines) + "。")
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
