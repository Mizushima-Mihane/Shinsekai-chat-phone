"""Chat Phone plugin entry point."""

from __future__ import annotations

import json as _json
import threading
from pathlib import Path

from sdk.hooks import MessageAddedContext
from sdk.logging import get_logger
from sdk.plugin import PluginBase
from sdk.plugin_host_context import PluginHostContext
from sdk.register import PluginCapabilityRegistry
from sdk.tool_registry import tool
from sdk.types import FrontendConfigAction, FrontendConfigContribution, FrontendPageContribution

logger = get_logger(__name__, plugin_id="com.shinsekai.chat_phone")

# ── Shared references (replaces phone_context cross-module import) ────

_monitor: object | None = None
_frontend_ui: object | None = None
_pending_incoming_caller = ""
_pending_incoming_lock = threading.Lock()

# Host page presentation: the registered phone page + a stable presentation id so
# an incoming call pops (present) and a hang-up dismisses the same overlay.
_FRONTEND_PAGE_ID = "chat_phone_app"
_INCOMING_CALL_PRESENTATION_ID = "chat-phone.incoming-call"


def get_monitor() -> object | None:
    return _monitor


def set_monitor(m: object) -> None:
    global _monitor
    _monitor = m


def clear_refs() -> None:
    global _monitor, _frontend_ui, _pending_incoming_caller
    _monitor = None
    _frontend_ui = None
    with _pending_incoming_lock:
        _pending_incoming_caller = ""


def get_pending_incoming_caller() -> str:
    with _pending_incoming_lock:
        return _pending_incoming_caller


def clear_pending_incoming_call(name: str = "") -> None:
    global _pending_incoming_caller
    with _pending_incoming_lock:
        if not name or _pending_incoming_caller == name:
            _pending_incoming_caller = ""


def set_frontend_ui(controller: object | None) -> None:
    global _frontend_ui
    _frontend_ui = controller


def _emit_call_event(event: dict) -> None:
    """Present or dismiss the phone page through the host's generic page channel.

    Incoming calls now surface via the host's feature-neutral plugin-page
    presentation API (present_page / dismiss_page, wired by main-repo PR 241):
    call.incoming pops the phone overlay with the caller payload, call.ended
    dismisses the same presentation. The original stream-sink emit is kept as a
    compatibility fallback for hosts without the runtime frontend_ui controller
    (legacy Qt mode, or a host predating PR 241).
    """
    event_type = str(event.get("type") or "").strip()
    if event_type == "call.incoming":
        caller = str(event.get("name") or "").strip()
        if caller:
            global _pending_incoming_caller
            with _pending_incoming_lock:
                _pending_incoming_caller = caller
    elif event_type == "call.ended":
        clear_pending_incoming_call()
    controller = _frontend_ui
    if controller is not None:
        try:
            if event_type == "call.incoming":
                caller = str(event.get("name") or "").strip()
                controller.present_page(
                    _FRONTEND_PAGE_ID,
                    presentation_id=_INCOMING_CALL_PRESENTATION_ID,
                    payload={
                        "view": "incoming-call",
                        "caller": caller,
                        "callType": (
                            "video"
                            if str(event.get("callType") or "").lower() == "video"
                            else "voice"
                        ),
                    },
                )
                logger.info("phone: presented incoming-call overlay for %r", caller)
                return
            if event_type == "call.ended":
                controller.dismiss_page(_INCOMING_CALL_PRESENTATION_ID)
                logger.info("phone: dismissed incoming-call overlay")
                return
        except RuntimeError:
            # No active React Chat stream (e.g. legacy Qt mode) — fall back below.
            logger.info("phone: present skipped, no active React stream; using stream-sink fallback")
        except Exception:
            logger.exception("generic phone page event failed")
    elif event_type in ("call.incoming", "call.ended"):
        logger.info("phone: no frontend_ui controller bound; using stream-sink fallback (backend not restarted?)")

    # Compatibility fallback for hosts that implemented the original phone events.
    try:
        import sys
        for key in ("__main__", "main"):
            mod = sys.modules.get(key)
            getter = getattr(mod, "get_stream_sink", None) if mod is not None else None
            if getter is None:
                continue
            sink = getter()
            if sink is not None and hasattr(sink, "emit"):
                sink.emit(event)
                return
    except Exception:
        logger.debug("call event emit failed", exc_info=True)


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
    from plugins.shinsekai_chat_phone import phone_core
    phone_core.add_contact(character_name)
    return ""


# ── LLM tool: send SMS ──────────────────────────────────────────────

@tool(
    name="send_sms",
    group="default",
    description=(
        "发送手机短信给玩家。两种时机都用它：①玩家在手机短信里发来消息时回复；"
        "②剧情演绎中你扮演的角色想主动给玩家发短信时（旁白可描写掏手机的动作，但短信正文只走本工具、不写进 dialog）。"
        "character_name是发信角色名（你自己扮演的角色），message是短信正文。可以连续调用多次发送多条短信。"
    ),
)
def send_sms(character_name: str, message: str) -> str:
    from plugins.shinsekai_chat_phone import phone_core
    phone_core.deliver_sms_paced(character_name, message)   # 逐条 10-30s，不再一次全弹出
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
    from plugins.shinsekai_chat_phone import phone_core
    phone_core.deliver_sms_paced(character_name, message, known=False)   # 逐条 10-30s
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
    from plugins.shinsekai_chat_phone import phone_core
    phone_core.group_route_reply(group_name, character_name, message)
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
    mem = [m.strip() for m in members.replace("，", ",").replace("、", ",").split(",") if m.strip()]
    from plugins.shinsekai_chat_phone import phone_core
    gid = phone_core.group_create(group_name, mem)
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
    from plugins.shinsekai_chat_phone import phone_core
    ok = phone_core.group_join(group_name, character_name, operator_name)
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
    from plugins.shinsekai_chat_phone import phone_core
    ok = phone_core.group_kick(group_name, character_name, operator_name)
    return "" if ok else f"无法把「{character_name}」移出群「{group_name}」（群不存在或不在群里）。"


@tool(
    name="leave_group",
    group="default",
    description=(
        "让某个角色主动退出群聊（他自己离开）。group_name是群名，character_name是退群的角色。"
    ),
)
def leave_group(group_name: str, character_name: str) -> str:
    from plugins.shinsekai_chat_phone import phone_core
    ok = phone_core.group_leave(group_name, character_name)
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
    from plugins.shinsekai_chat_phone import phone_core
    final = phone_core.group_rename(group_name, new_name, operator_name)
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
    from plugins.shinsekai_chat_phone import phone_core
    pid = phone_core.moment_add_post(character_name, text, image_desc)
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
    from plugins.shinsekai_chat_phone import phone_core
    phone_core.moment_add_comment(_coerce_pid(post_id), character_name, text, reply_to=reply_to)
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
    from plugins.shinsekai_chat_phone import phone_core
    phone_core.moment_add_like(_coerce_pid(post_id), character_name)
    return ""


@tool(
    name="browser_result",
    group="default",
    description=(
        "为玩家的一次浏览器搜索生成搜索结果页。当用户消息以[浏览器]开头时调用："
        "你此刻是这个世界的搜索引擎，不是角色本人。query 传玩家搜索的关键词；"
        "results 传一个 JSON 数组（4-6 条），每项包含 title（标题）、snippet（摘要）、"
        "site（来源站点，可选）三个字段。结果要具体、有细节、够劲爆吸睛（八卦、猛料、反转、"
        "都市传说皆可），可结合当前剧情与相关角色，让玩家有一探究竟的欲望。只调用本工具，不要输出对话或旁白。"
    ),
)
def browser_result(query: str, results: str = "") -> str:
    import json as _json
    parsed: list = []
    raw = results
    if isinstance(raw, list):
        parsed = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            parsed = _json.loads(raw)
        except Exception:
            for line in raw.splitlines():
                line = line.strip().lstrip("-•*0123456789. ").strip()
                if not line:
                    continue
                sep = "::" if "::" in line else ("|" if "|" in line else "")
                if sep:
                    _t, _s = line.split(sep, 1)
                    parsed.append({"title": _t.strip(), "snippet": _s.strip()})
                else:
                    parsed.append({"title": line, "snippet": ""})
    if not isinstance(parsed, list):
        parsed = []
    from plugins.shinsekai_chat_phone import phone_core
    ok = phone_core.save_browser_results(query, parsed)
    return f"已生成 {len(parsed)} 条搜索结果。" if ok else "搜索结果生成失败。"


@tool(
    name="adjust_affinity",
    group="default",
    description=(
        "调整某个角色对玩家的好感度（0-100）。当剧情推进让该角色对玩家的感情发生变化时调用："
        "被关心、心动、亲密、玩家投其所好 → 加（+1~+10）；被冷落、敷衍、伤害、忽视 → 减（-1~-15）。"
        "character_name 是角色名，delta 是变化量（正负整数）。好感度会影响该角色主动联系玩家的频率和平时的态度，"
        "所以只在关系确有升温/降温时调用，日常普通对话不必每轮都调。"
    ),
)
def adjust_affinity(character_name: str, delta: str = "0") -> str:
    from plugins.shinsekai_chat_phone import phone_core
    try:
        d = int(str(delta).strip())
    except Exception:
        d = 0
    v = phone_core.adjust_affinity(character_name, d)
    return f"{character_name} 好感度 → {v}/100。"


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
    from plugins.shinsekai_chat_phone.phone_settings import add_hacked_character
    added = add_hacked_character(character_name)
    if added:
        return f"已成功在「{character_name}」的手机上安装监控程序。玩家可以查看其手机私密活动。"
    else:
        return f"「{character_name}」的手机已经被监控了，无需重复操作。"


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

def _apply_scene_transition(ctx, mon, char_settings, narration_parts, spoke_chars) -> None:
    """Track explicit shared scenes: private togetherness blocks all contact, quiet places block calls."""
    try:
        import re as _re6
        narr = " ".join(narration_parts)
        last_user = ""
        for m in reversed(getattr(ctx, "messages", None) or []):
            if isinstance(m, dict) and m.get("role") == "user" and isinstance(m.get("content"), str):
                last_user = m["content"]
                break
        player_moved = bool(_re6.match(
            r'^\s*[（(]\s*(?:去|前往|赶去|赶往|离开|回家|回到|出门|走出|回房|回公寓|回住处)', last_user))
        _TRANSITION_KW = ("第二天", "次日", "翌日", "隔天", "几天后", "数日后", "一周后", "一个月后",
                          "几小时后", "半小时后", "场景切换", "转场",
                          "回到家", "回到房间", "回到公寓", "回到住处", "回到自己的")
        if player_moved or any(k in narr for k in _TRANSITION_KW):
            mon.clear_scene()
        quiet_terms = r"图书馆|自习室|教室|课堂|上课|开会|会议|办公室|考场|讲座"
        together_terms = r"同处一室|独处|并肩|在你身边|在你身旁|站在你面前|坐在你对面|和你面对面|房间里|客厅里|公寓里|家里|宿舍里"
        generic_shared = r"你们|两人|二人"
        for cn in char_settings:
            named_quiet = rf"{_re6.escape(cn)}[^。！？!？\n]{{0,20}}(?:{quiet_terms})"
            named_together = rf"{_re6.escape(cn)}[^。！？!？\n]{{0,20}}(?:{together_terms})"
            shared_quiet = cn in spoke_chars and _re6.search(rf"(?:{generic_shared})[^。！？!？\n]{{0,20}}(?:{quiet_terms})", narr)
            shared_together = cn in spoke_chars and _re6.search(rf"(?:{generic_shared})[^。！？!？\n]{{0,20}}(?:{together_terms})", narr)
            if _re6.search(named_quiet, narr) or shared_quiet:
                mon.set_scene_character(cn, "quiet")
            elif _re6.search(named_together, narr) or shared_together:
                mon.set_scene_character(cn, "together")
        for cn in char_settings:
            if _re6.search(
                rf'{_re6.escape(cn)}[^。！？!?\n]{{0,6}}(?:离开|走了|离去|告辞|离席|先走|先行离|转身离|起身离|扬长而去)',
                narr,
            ):
                mon.remove_scene_character(cn)
    except Exception:
        pass


def _recover_stranger_sms(char_settings, narration_parts, spoke_chars, deliver) -> None:
    """从旁白/COT 里回收「未知联系人发来短信」的正文并投递（deliver(sender, msg)）。

    仅当发信人能唯一归属到一名在册角色、且该角色本轮没当面说话时才投递。Qt 与 React 共用。
    """
    import re as _re4
    narr = " ".join(narration_parts)
    mm = _re4.search(
        r'(?:未知联系人|陌生号码|未知号码|陌生人|陌生短信)[^「『"（(]{0,10}[「『"]([^」』"]{1,200})[」』"]',
        narr,
    )
    if not mm:
        return
    stranger_msg = mm.group(1).strip()
    sms_cue = (r'(?:未知联系人|发来短信|发短信|发条短信|发了短信|发送短信|'
               r'拿到[^。！？!?\n]{0,6}号码|要到[^。！？!?\n]{0,6}号码|搞到[^。！？!?\n]{0,6}号码)')
    cands: set[str] = set()
    for cn in char_settings:
        cn = (cn or "").strip()
        if not cn:
            continue
        al = {cn}
        if len(cn) >= 4:
            al.add(cn[:2]); al.add(cn[-2:])
        elif len(cn) == 3:
            al.add(cn[-2:])
        alt = "|".join(_re4.escape(a) for a in al if len(a) >= 2)
        if not alt:
            continue
        if (_re4.search(rf'(?:{alt})[^。！？!?\n]{{0,20}}{sms_cue}', narr)
                or _re4.search(rf'{sms_cue}[^。！？!?\n]{{0,20}}(?:{alt})', narr)):
            cands.add(cn)
    sender = next(iter(cands)) if len(cands) == 1 else ""
    if sender and sender not in spoke_chars and stranger_msg:
        logger.info("Recovered narrated stranger SMS -> %s: %s", sender, stranger_msg[:40])
        try:
            deliver(sender, stranger_msg)
        except Exception:
            logger.debug("stranger sms deliver failed", exc_info=True)


def _on_message_added(ctx: MessageAddedContext, char_settings: dict) -> None:
    """Route assistant responses through the React phone implementation."""
    if ctx.role == "assistant":
        _on_message_added_react(ctx, char_settings)


def _phone_text_kind(ctx) -> str:
    """If this assistant turn answers a background phone *text* action (SMS / group / moment /
    browser, injected via _trigger_runtime_turn), return its kind so the reply is kept OFF the
    public stage. Voice calls ([通话]/[视频通话]) are excluded — their dialogue belongs on stage."""
    try:
        msgs = getattr(ctx, "messages", None) or []
    except Exception:
        return ""
    for m in reversed(msgs):
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        c = str(m.get("content", "") or "").lstrip()
        if c.startswith("[短信]"):
            return "sms"
        if c.startswith("[群聊]"):
            return "group"
        if c.startswith("[朋友圈]"):
            return "moment"
        if c.startswith("[浏览器]"):
            return "browser"
        return ""   # newest user turn isn't a phone-text trigger → normal story turn
    return ""


def _phone_group_name(ctx) -> str:
    """Group name from the most recent [群聊] trigger, to route a stray dialog line into the
    right group when the LLM answered with plain dialogue instead of the send_group_sms tool."""
    try:
        import re
        for m in reversed(getattr(ctx, "messages", None) or []):
            if isinstance(m, dict) and m.get("role") == "user":
                c = str(m.get("content", "") or "")
                if c.lstrip().startswith("[群聊]"):
                    mm = re.search(r'群[「"]([^」"]+)[」"]', c)
                    return mm.group(1).strip() if mm else ""
                return ""
    except Exception:
        pass
    return ""


def _on_message_added_react(ctx, char_settings: dict) -> None:
    """React-mode assistant hook (no Qt widget): capture PHONE SMS, track face-to-face
    scene for the proactive monitor, recover narrated stranger SMS, and strip
    COT/PHONE/CALL from the stored dialog. Call/video is Qt-only, so it's skipped here.
    """
    import re
    from plugins.shinsekai_chat_phone import phone_core
    content = ctx.message.get("content", "") if isinstance(ctx.message, dict) else ""
    if not isinstance(content, str) or not content.strip():
        return
    content = content.strip()
    if not content.startswith("{"):
        m = re.search(r'[{\[]', content)
        if m:
            content = content[m.start():]
    try:
        data = _json.loads(content)
    except Exception:
        fixed = re.sub(r'("speech"\s*:\s*")(.*?)("\s*[,}])',
                       lambda mm: mm.group(1) + mm.group(2).replace('"', '\\"') + mm.group(3),
                       content, flags=re.DOTALL)
        try:
            data = _json.loads(fixed)
        except Exception:
            return
    if isinstance(data, dict):
        items = data.get("dialog", [])
    elif isinstance(data, list):
        items = data
    else:
        return
    if not isinstance(items, list):
        return

    phone_kind = _phone_text_kind(ctx)   # 本轮由手机文字操作(短信/群聊/朋友圈/浏览器)触发？其回复不上主舞台
    phone_items: list[tuple[str, str]] = []
    narration_parts: list[str] = []
    spoke_chars: set[str] = set()
    mon = get_monitor()
    pending_callers = {get_pending_incoming_caller()} - {""}
    # A CALL marker can appear after an eager line from the same character in one
    # model response. Treat the whole response as ringing, so that line cannot
    # leak onto the stage before the player answers.
    for pending_item in items:
        if not isinstance(pending_item, dict):
            continue
        if str(pending_item.get("character_name", "") or "").strip() == "CALL":
            pending_caller = str(pending_item.get("speech", "") or "").split(":")[0].split("：")[0].strip()
            if pending_caller:
                pending_callers.add(pending_caller)
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("character_name", "") or "").strip()
        speech = str(item.get("speech", "") or "").strip()
        if not name or not speech:
            continue
        if name == "PHONE":
            m = re.match(r"([^：:]+)[：:]\s*(.+)", speech) or re.match(r"\[([^\]]+)\]\s*(.+)", speech)
            if m:
                cn = m.group(1).strip()
                if not (cn.startswith("【") or "监控情报" in cn):  # never deliver 监控情报 as SMS
                    phone_items.append((cn, m.group(2).strip()))
            continue
        if name == "CALL":
            # character-initiated call: signal the frontend to ring / pop the phone.
            call_char = speech.split(":")[0].split("：")[0].strip()
            call_type = "video" if ("视频" in speech or "video" in speech.lower()) else "voice"
            if call_char and call_char in char_settings:
                _dnd = False
                try:
                    from plugins.shinsekai_chat_phone.phone_settings import is_dnd as _is_dnd
                    _dnd = _is_dnd()
                except Exception:
                    _dnd = False
                if _dnd:  # 勿扰：不弹来电，只记一条未接
                    try:
                        phone_core.log_call(call_char, 0, "missed_video" if call_type == "video" else "missed_dnd")
                    except Exception:
                        pass
                else:
                    _emit_call_event({"type": "call.incoming", "name": call_char, "callType": call_type,
                                      "pluginId": "com.shinsekai.chat_phone", "pageId": "chat_phone_app"})
            continue
        if name in ("NARR", "CHOICE", "STAT", "bgm", "CG", "旁白"):
            if name in ("NARR", "旁白"):
                narration_parts.append(speech)
            continue
        if name == "COT":
            narration_parts.append(speech)
            try:
                from plugins.shinsekai_chat_phone.phone_settings import is_character_yandere, record_yandere_tampering
                if any(k in speech for k in _TAMPER_KW):
                    for cname in char_settings:
                        if cname in speech and is_character_yandere(cname):
                            record_yandere_tampering(cname)
            except Exception:
                pass
            continue
        # 手机文字回合(短信/群聊/朋友圈/浏览器)：角色本应只调工具、不出台词。万一 LLM 直接写了普通
        # 对话，就转存进对应手机记录、并从主舞台抹掉——私聊内容绝不漏进正文舞台。
        if phone_kind:
            if phone_kind == "sms":
                phone_items.append((name, speech))
            elif phone_kind == "group":
                _grp = _phone_group_name(ctx)
                if _grp:
                    try:
                        phone_core.group_route_reply(_grp, name, speech)
                    except Exception:
                        logger.debug("react group reply capture failed", exc_info=True)
            continue   # moment/browser 走各自工具，这里只需从舞台 strip
        if name in pending_callers:
            continue
        # Regular stage dialogue is not itself proof of a face-to-face scene.
        spoke_chars.add(name)
        try:
            from plugins.shinsekai_chat_phone.phone_settings import is_character_yandere, record_yandere_tampering
            if is_character_yandere(name) and any(k in speech for k in _TAMPER_KW[:-4]):
                record_yandere_tampering(name)
        except Exception:
            pass

    # Deliver PHONE items straight to the phone (fallback if the LLM used a PHONE
    # dialog item instead of the send_sms tool).
    for cn, sp in phone_items:
        try:
            phone_core.deliver_sms_paced(cn, sp)   # 逐条 10-30s
        except Exception:
            logger.debug("react PHONE deliver failed", exc_info=True)

    if mon is not None:
        _apply_scene_transition(ctx, mon, char_settings, narration_parts, spoke_chars)
    if narration_parts:
        _recover_stranger_sms(char_settings, narration_parts, spoke_chars,
                              lambda s, m: phone_core.deliver_sms(s, m, known=False))
        # Stage narration is dialogue, not a phone-control protocol. A call ends
        # only when the player uses the explicit hang-up action in the phone UI.

    # Strip COT + PHONE + CALL from the stored dialog to save tokens / keep them off stage.
    if isinstance(data, dict) and "dialog" in data:
        original_len = len(data["dialog"])
        if phone_kind:
            # 手机文字回合：整轮都不该出现在主舞台，清掉全部台词，只留系统性非对话项
            data["dialog"] = [
                it for it in data["dialog"]
                if str(it.get("character_name", "")).strip() in ("CHOICE", "STAT", "bgm", "CG")
            ]
        else:
            data["dialog"] = [
                it for it in data["dialog"]
                if str(it.get("character_name", "")).strip() not in ({"COT", "PHONE", "CALL"} | pending_callers)
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

    别名候选 = 全名 + 常见简称（四字名取前两字/后两字，如「甲乙丙丁」→「甲乙」「丙丁」）。
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
        from plugins.shinsekai_chat_phone import phone_core
        if phone_core.contacts_list():
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
        # 例：「我有 甲、乙 的联系方式」→ 正（甲+乙）；
        #     「丙 的联系方式还没有」→ 负（还没→丙不建）。
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
            if phone_core.add_contact(name, known=True):
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
        from plugins.shinsekai_chat_phone import phone_core
        dd = phone_core.session_dir()
        marker = dd / "_intro_sms_done"
        if marker.exists():
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

        try:
            from config.config_manager import ConfigManager
            chars = [(c.name, (c.character_setting or ""))
                     for c in ConfigManager().config.characters if (c.name or "").strip()]
        except Exception:
            chars = []
        if not chars:
            return
        # 已有任何短信 → 主模型/之前已投递，别重复
        if any(phone_core.messages_for(n) for n, _ in chars):
            return
        known = set(phone_core.contacts_list())
        cands = [(n, s) for n, s in chars if n not in known]
        if not cands:
            return
        # 选发信人：优先设定里暗示对玩家有兴趣/暧昧/病娇的，否则第一个未建联系人
        cands.sort(key=lambda it: sum(k in it[1] for k in
                   ("暧昧", "喜欢", "占有", "病娇", "执着", "兴趣", "追求", "痴迷")), reverse=True)
        sender, setting = cands[0]

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
                    phone_core.deliver_sms_paced(sender, r, known=False)
            except Exception:
                logger.exception("intro sms generation failed")

        threading.Thread(target=_run, daemon=True, name="intro-sms").start()
    except Exception:
        logger.exception("maybe seed intro sms failed")


def _reset_phone_data() -> None:
    """Clear the active React phone session when a genuinely new game begins."""
    import contextlib
    import shutil
    from plugins.shinsekai_chat_phone import phone_core

    dd = phone_core.session_dir(write_marker=False)
    for fn in ("contacts.json", "messages.json", "groups.json", "moments.json",
               "call_log.json", "video_call_log.json", "pending_proactive.json",
               "browser_history.json", "browser_results.json", "char_freq.json",
               "affinity.json", "_intro_sms_done"):
        with contextlib.suppress(Exception):
            (dd / fn).unlink(missing_ok=True)
    with contextlib.suppress(Exception):
        shutil.rmtree(dd / "moments_images", ignore_errors=True)
    logger.info("Phone data reset for new game")


def _context_is_compacted(msgs) -> bool:
    """上下文里是否出现「历史压缩摘要」。

    摘要以 ``role=user`` 注入（见 llm/compact_manager.py），压缩恰好发生在「你刚发消息、
    AI 还没回」时，会让上下文变成「有 user、无 assistant」——正是新局判定的样子，从而误报。
    一旦检测到摘要标记，就说明这是被压缩过的进行中对话，绝不重置。
    """
    markers = ("历史对话总结", "历史摘要", "较早历史已省略")
    try:
        from llm.compact_manager import CompactManager
        markers = tuple(getattr(CompactManager, "SUMMARY_MARKERS", markers)) or markers
    except Exception:
        pass
    for m in (msgs or []):
        if isinstance(m, dict):
            c = m.get("content")
            if isinstance(c, str) and any(mk in c for mk in markers):
                return True
    return False


def _phone_data_dir() -> object | None:
    """Current React phone session directory."""
    try:
        from plugins.shinsekai_chat_phone import phone_core
        return phone_core.session_dir(write_marker=False)
    except Exception:
        return None


def _mark_phone_initialized() -> None:
    """标记本存档已初始化过手机，之后永不自动重置（新游戏是新目录、无此标记）。"""
    import contextlib
    with contextlib.suppress(Exception):
        dd = _phone_data_dir()
        if dd is not None:
            dd.mkdir(parents=True, exist_ok=True)
            (dd / "_phone_initialized").write_text("1", encoding="utf-8")


def _maybe_reset_phone_on_new_game(ctx) -> None:
    """新开存档时清空手机数据（仅新局第一轮、且确有旧数据时）。

    双重守卫，绝不误清进行中的存档：
    1) 上下文含历史压缩摘要 → 被压缩过的对话（摘要是 role=user，伪装成"有 user 无
       assistant"的新局判定），直接跳过；
    2) 本存档已写过 ``_phone_initialized`` 标记 → 曾初始化过，永不重置。
    """
    try:
        msgs = getattr(ctx, "messages", None) or []
        # 守卫①：压缩摘要在场 → 绝不重置
        if _context_is_compacted(msgs):
            return
        # 守卫②：已初始化标记在场 → 绝不重置
        dd = _phone_data_dir()
        if dd is not None:
            with __import__("contextlib").suppress(Exception):
                if (dd / "_phone_initialized").is_file():
                    return
        has_user = any(isinstance(m, dict) and m.get("role") == "user" for m in msgs)
        has_assistant = any(isinstance(m, dict) and m.get("role") == "assistant" for m in msgs)
        if not has_user or has_assistant:
            return  # 继续存档 / 尚无开场 → 不清
        from plugins.shinsekai_chat_phone import phone_core
        has_data = bool(phone_core.contacts_list()) or any(
            phone_core.messages_for(name) for name in phone_core.contacts_list())
        if has_data:
            _reset_phone_data()
    except Exception:
        logger.exception("maybe reset phone on new game failed")
    finally:
        # 幂等标记：见过本存档即写标记，之后任何一轮都不再自动重置。
        _mark_phone_initialized()


def _on_before_chat(ctx) -> None:
    """Inject PHONE-format system message + hacker/yandere context."""
    try:
        # 新开存档：先清空旧手机数据（仅新局第一轮触发），再按开场设定播种联系人
        _maybe_reset_phone_on_new_game(ctx)
        # 开场从设定/首条消息确定性播种联系人（须在注入 [手机系统] 之前，避免扫到自身注入内容）
        _seed_contacts_from_opening(ctx)
        # 开场若声明「过去收到过（未知）短信」，插件自拟一条并按未知联系人投递（每存档一次）
        _maybe_seed_intro_sms(ctx)
        # Detect + strip parenthetical "让XX打电话" from the last user msg, and remember it
        # so we can turn it into an explicit incoming-call directive below. (The old phone
        # acted on this request; the React port only stripped it and silently dropped it.)
        import re as _re_strip
        _paren_re = _re_strip.compile(
            r'[(（]\s*[让叫]\s*(\S+?)\s*(?:给[我咱])?\s*(?:打|拨)\s*(?:个)?\s*(电话|视频|视频电话)?[)）]')
        _call_request = None
        # 本轮玩家用了哪类手机功能 → 对应的大段协议按需注入（省 token，也减少角色跑题）
        _use_group = _use_moment = _use_browser = False
        for m in reversed(ctx.messages):
            if isinstance(m, dict) and m.get("role") == "user":
                content = m.get("content", "")
                if isinstance(content, str):
                    _lu = content.lstrip()
                    _use_group = _lu.startswith("[群聊]")
                    _use_moment = _lu.startswith("[朋友圈]")
                    _use_browser = _lu.startswith("[浏览器]")
                    _mo = _paren_re.search(content)
                    if _mo:
                        _call_request = (_mo.group(1).strip(), "视频" in (_mo.group(2) or ""))
                    cleaned = _paren_re.sub('', content).strip()
                    if cleaned:
                        m["content"] = cleaned
                break

        msg = (
            "[手机系统]（以下全部是给你的幕后规则和工具用法，绝不可作为台词说出、复述、"
            "或让玩家察觉；当这一轮玩家并没有通过手机做任何操作时，就当这些规则不存在、"
            "专心演绎当前的当面剧情，不要主动提手机、短信、好感度之类的元信息。）"
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
            " [通话状态铁律] 一通电话的接通、进行、挂断，全部由系统事件驱动：只有出现 "
            "[通话]/[视频通话]/[通话结束] 这类系统提示时，通话状态才真正改变。玩家在通话中或通话后"
            "打字说「挂了」「喂？」「别挂」之类只是台词，并不代表真的接通或挂断了电话——"
            "在出现对应系统提示之前，绝不要自行脑补电话接通/挂断、也不要提前替角色生成挂断后的反应。"
            "（注意：玩家要求某角色「给我打电话」属于要发起来电，应按 [来电] 协议输出 CALL 信号，不在此限。）"
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
            "另外不要在 dialog/旁白里描写「手机亮起、震动、有短信进来」这类氛围——玩家的手机通知只在手机 App 里体现，主舞台不要提及；短信正文只走 send_sms / send_sms_stranger 工具。"
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
        if _call_request:
            _cr_name, _cr_video = _call_request
            _cr_kind = "视频电话" if _cr_video else "电话"
            # 玩家点名要来电是明确的元指令 —— 直接发起来电，不再赌 LLM 输出 CALL 信号。
            # （13k-token 的大 prompt + flash 小模型经常忽略它，就成了"让他打电话却没打"。）
            try:
                _emit_call_event({"type": "call.incoming", "name": _cr_name,
                                  "callType": "video" if _cr_video else "voice",
                                  "pluginId": "com.shinsekai.chat_phone", "pageId": "chat_phone_app"})
            except Exception:
                logger.debug("direct player-requested call.incoming failed", exc_info=True)
            msg += (
                f" [幕后安排来电]（玩家在幕后安排剧情、不是当面对白）系统已替「{_cr_name}」向玩家拨出一通{_cr_kind}，"
                f"玩家手机此刻正在响铃、尚未接听。本轮你【不要】把它当成当面对话来演、【不要】替玩家接听、"
                f"【不要】再输出通话正文或 CALL 信号（来电已由系统发起）；至多给一句「{_cr_name}」拨号时的简短心理或旁白。"
                f"等玩家接听后，系统会用 [通话] 提示你再正式开始通话。"
                f"【演绎要求】把这通电话处理成「{_cr_name} 自己主动想打给玩家」——结合此刻的心情、剧情和你们的关系给个自发理由，"
                f"绝不要表现出、更不要说出「是玩家要求／安排我才打的」。")
        # ── Player's chosen name (so characters can address them naturally) ──
        try:
            from plugins.shinsekai_chat_phone.phone_settings import get_player_name as _gpn, get_player_signature as _gps
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
        # ── Affinity（好感度）+ manual-frequency override（幕后态度参照，勿念成台词）──
        try:
            from config.config_manager import ConfigManager as _CM_aff
            from plugins.shinsekai_chat_phone import phone_core as _pc_aff
            _aff_lines = []
            _any_manual = False
            for _c in _CM_aff().config.characters:
                _cn = _c.name
                _mn = _pc_aff.is_manual_freq(_cn)
                _any_manual = _any_manual or _mn
                _aff_lines.append(f"{_cn} {_pc_aff.get_affinity(_cn)}/100" + ("（玩家强开了手动频率）" if _mn else ""))
            if _aff_lines:
                msg += (
                    " [好感度] 仅供你把握态度、绝不可说出口的内部数值——各角色对玩家的好感度："
                    + "；".join(_aff_lines) + "。好感度低就冷淡、疏离、被动，高就亲密、主动、黏人，"
                    "自然融进语气即可；切勿把数字、「好感度」字样或本条说明念成台词。"
                )
                if _any_manual:
                    msg += (
                        " 上面标注「玩家强开了手动频率」的角色：若是普通人设则毫无察觉、也不在意；"
                        "唯有【病娇/极端占有型】人设才会隐约觉得玩家在刻意操纵与自己的联系频率，"
                        "并在玩家转为冷淡敷衍时逐渐情绪失控、质问玩家为何疏远——如何流露完全自行演绎，不要套用固定台词。"
                    )
        except Exception:
            pass
        # ── Group chat protocol — inject only when the player is in a group this turn ──
        if _use_group:
            try:
                _group_lines: list[str] = []
                from plugins.shinsekai_chat_phone import phone_core
                for _gname in phone_core.group_names():
                    _gmem = "、".join(phone_core.group_members(_gname))
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
        # ── Moments (朋友圈) protocol — inject only when the player used 朋友圈 this turn ──
        if _use_moment:
            try:
                _moment_lines: list[str] = []
                from plugins.shinsekai_chat_phone import phone_core
                _posts = phone_core.moment_get_posts()[-6:]
                for _p in _posts:
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
        # ── Browser (浏览器) protocol — only when the player searched this turn ──
        if _use_browser:
            msg += (
                " [浏览器] 当用户消息以[浏览器]开头时，玩家在手机浏览器里做了一次搜索。"
                "此刻你要扮演这个世界的“搜索引擎”，而不是任何角色——调用 browser_result 工具，"
                "为这次搜索返回 4-6 条结果：query 传搜索词，results 传一个 JSON 数组，"
                "每项包含 title（标题）、snippet（摘要）、site（来源站点，可选）三个字段。"
                "结果要具体、有细节、够劲爆吸睛，可结合当前剧情与相关角色制造猛料、八卦或反转，"
                "勾起玩家继续深挖的欲望。本轮除该工具调用外，不要输出任何台词或旁白。"
            )
        # ── Recording (录音) awareness — player may be recording your voice ──
        try:
            _rf = Path("data/plugins/com.shinsekai.chat_phone/recording.json")
            if _rf.is_file() and _json.loads(_rf.read_text(encoding="utf-8")).get("active"):
                msg += ("（旁白提示：玩家此刻正举着手机，像是在录你的声音——你可以自然地察觉并作出反应，"
                        "也可以毫无察觉，由你把握，别显得生硬。）")
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
        from plugins.shinsekai_chat_phone.phone_settings import get_hacked_characters
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
        from plugins.shinsekai_chat_phone.phone_settings import get_yandere_characters
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

            # Browser history (session-scoped) — incl. searches the player tried to delete
            try:
                hp2 = _sms_dir / "browser_history.json"
                if hp2.is_file():
                    hist = _j3.loads(hp2.read_text(encoding="utf-8"))
                    if hist:
                        vis, deleted = [], []
                        for _x in hist:
                            if isinstance(_x, str):
                                vis.append(_x)
                            elif isinstance(_x, dict) and str(_x.get("q", "")).strip():
                                (deleted if _x.get("del") else vis).append(str(_x["q"]))
                        _bparts = []
                        if vis:
                            _bparts.append("浏览器搜索记录：" + _j3.dumps(vis, ensure_ascii=False))
                        if deleted:
                            _bparts.append(
                                "玩家偷偷删掉、以为无人知晓的搜索：" + _j3.dumps(deleted, ensure_ascii=False))
                        if _bparts:
                            intel_parts.append("\n".join(_bparts))
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


def _on_init_chat(ctx, char_settings: dict) -> None:
    """Start the React phone's proactive-contact driver once per chat."""
    try:
        if get_monitor() is not None:
            return
        from plugins.shinsekai_chat_phone.proactive_core import ProactiveCore
        m = ProactiveCore(on_incoming_call=_emit_call_event)
        m.set_character_settings(char_settings)
        try:
            fp = Path("data/plugins/com.shinsekai.chat_phone/freq_config.json")
            if fp.is_file():
                m.set_frequency_config(_json.loads(fp.read_text(encoding="utf-8")))
        except Exception:
            pass
        m.start(interval_sec=60)
        set_monitor(m)
    except Exception:
        logger.exception("Failed to start proactive core (React mode)")


# ── Plugin ────────────────────────────────────────────────────────────

class ChatPhonePlugin(PluginBase):

    @property
    def plugin_id(self) -> str: return "com.shinsekai.chat_phone"
    @property
    def plugin_version(self) -> str: return "2.0.0"
    @property
    def plugin_name(self) -> str: return "doki_chat"
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

        # Message hook: capture SMS replies
        register.register_message_added_hook(lambda ctx: _on_message_added(ctx, char_settings))

        # Before-chat hook: inject PHONE format, strip phone-call parens
        register.register_before_chat_hook(_on_before_chat)

        # Init-chat hook: start the Qt-free proactive monitor when running headless
        # (React desktop). In Qt mode the widget path starts its own QTimer monitor.
        register.register_init_chat_hook(lambda ctx: _on_init_chat(ctx, char_settings))

        # ── Combined: Avatar + Theme + Frequency ──
        char_names = list(char_settings.keys())
        def _load_combined():
            from plugins.shinsekai_chat_phone.phone_settings import get_theme
            d = {"theme": get_theme(), "char_name": char_names[0] if char_names else "", "sms": 0.1, "call": 0.03,
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
            from plugins.shinsekai_chat_phone.phone_settings import save_settings, load_settings, get_theme
            s = load_settings(); s["theme"] = str(v.get("theme", get_theme())); save_settings(s)
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
            from plugins.shinsekai_chat_phone.phone_core import get_music_path
            return {"exe_path": get_music_path()}
        def _save_music(v):
            from plugins.shinsekai_chat_phone.phone_core import set_music_path
            set_music_path(str(v.get("exe_path", "")).strip())

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

        # ── Doki-style web phone (new 2.3 React UI) ──
        # An iframe page + a single JSON-RPC action that drives the whole phone.
        try:
            from plugins.shinsekai_chat_phone import webface
            # plugin_root is the DATA dir; the bundled frontend lives next to the code.
            phone_entry = str((Path(__file__).parent / "frontend" / "dist" / "index.html").resolve())
            logger.info("Doki phone entry=%s exists=%s", phone_entry, Path(phone_entry).is_file())
            register.register_frontend_page(FrontendPageContribution(
                page_id="chat_phone_app",
                title="Phone (Doki)",
                kind="tools",
                entry=phone_entry,
                description="Doki-style phone: SMS / contacts / moments",
                order=40.0,
            ))
            register.register_frontend_config_page(FrontendConfigContribution(
                page_id="chat_phone_app",
                title="Phone (Doki)",
                kind="tools",
                description="Doki-style phone: SMS / contacts / moments",
                schema=[],
                load_values=lambda: {},
                save_values=lambda _v: None,
                actions=[FrontendConfigAction(id="rpc", label="rpc", run=webface.rpc)],
                order=40.0,
            ))
            # Runtime page presentation: hand the plugin the host's frontend_ui
            # controller so an incoming call can pop the phone overlay through the
            # generic plugin-page channel. Guarded: hosts without it just skip.
            try:
                set_frontend_ui(register.frontend_ui())
            except AttributeError:
                logger.debug("runtime frontend page presentation is unavailable")
            except Exception:
                logger.exception("Failed to bind runtime phone page presentation")
            # Toolbar entry (host: codex chat-UI slots) — a phone button in the top
            # stage toolbar that pops the phone page as a floating overlay. Guarded:
            # hosts without register_frontend_chat_ui simply skip it.
            try:
                from sdk.types import FrontendChatUIContribution
                from plugins.shinsekai_chat_phone.phone_settings import load_settings
                if hasattr(register, "register_frontend_chat_ui"):
                    _phone_prefs = load_settings()
                    register.register_frontend_chat_ui(FrontendChatUIContribution(
                        contribution_id="open_phone",
                        slot="chat-top-toolbar",
                        title="手机",
                        icon="smartphone",
                        action={"type": "open-plugin-page", "page_id": "chat_phone_app", "mode": "overlay"},
                        # Overlay window shape: a tall, narrow phone silhouette.
                        # Host clamps to width[240,640] / height[320,960]. The
                        # background is only the pre-load placeholder — it matches
                        # the phone's default pink theme (--bg) so the first paint
                        # is seamless; the phone then streams its live theme color
                        # and the host recolors the shell + drag bar to follow it.
                        overlay_width=400,
                        overlay_height=860,
                        overlay_background="#ebe6ee",
                        overlay_initial_mini=str(_phone_prefs.get("phone_size", "normal")) == "mini",
                        order=40.0,
                    ))
            except Exception:
                logger.debug("chat-UI toolbar slot unavailable; skipping phone toolbar entry", exc_info=True)
        except Exception:
            logger.exception("Failed to register Doki web phone page")

        logger.info("Chat Phone initialized (chars=%d)", len(char_settings))

    def shutdown(self) -> None:
        m = get_monitor()
        if m is not None:
            m.stop()
        clear_refs()
