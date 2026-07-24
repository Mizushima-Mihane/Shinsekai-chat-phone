"""Web phone (Doki-style) backend: a single JSON-RPC action the iframe calls.

The Qt phone kept its live state in-process; the React desktop shell has no Qt,
so this module reads the *persisted* per-session JSON files directly from the
bridge process and returns plain dicts. One ``rpc(values)`` entry point dispatches
on ``values["cmd"]`` so a single registered FrontendConfigAction drives the whole
phone (list threads, open a thread, send an SMS, read contacts / moments).

Persistence layout (written by the legacy phone), per chat session:
    data/plugins/com.shinsekai.chat_phone/<session_hash>/messages.json  {name: [{text,is_user,idx,read}]}
                                          /contacts.json  {contacts: {name: {...}}}
                                          /moments.json   {posts: [...]}

Session binding note (v1 preview): the legacy phone binds to the runtime's
``--history`` arg, which the bridge process does not have. Until the de-Qt core
(route C) lands proper binding, we surface the *richest* file of each kind so the
preview shows real data on every screen. In normal single-session use every kind
lives in the one active session dir, so this collapses to that session.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Mapping

from sdk.logging import get_logger

logger = get_logger(__name__, plugin_id="com.shinsekai.chat_phone")

PLAYER = "__player__"
_BASE = Path("data/plugins/com.shinsekai.chat_phone")


# ── paths ────────────────────────────────────────────────────────────

def _base() -> Path:
    return _BASE


def _session_dirs() -> list[Path]:
    base = _base()
    return [d for d in base.iterdir() if d.is_dir()] if base.is_dir() else []


def _richest(name: str) -> Path | None:
    """Prefer the active session (where the LLM writes); else richest by size."""
    try:
        from plugins.shinsekai_chat_phone import phone_core
        sd = phone_core.session_dir(write_marker=False)
        fp = sd / name
        if fp.is_file() and fp.stat().st_size > 40:
            return sd
    except Exception:
        pass
    best: Path | None = None
    best_size = 0
    for d in _session_dirs():
        fp = d / name
        try:
            size = fp.stat().st_size if fp.is_file() else 0
        except OSError:
            size = 0
        if size > best_size:
            best_size = size
            best = d
    return best


def _read_json(path: Path | None, default: Any) -> Any:
    try:
        if path is not None and path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.debug("phone read failed: %s", path, exc_info=True)
    return default


# ── player identity ──────────────────────────────────────────────────

_PLAYER_CACHE: str | None = None


def _player_name() -> str:
    # Read from phone_settings.json (tiny file), NOT ConfigManager (which loads
    # all app config and costs ~1.2s). Matches the legacy phone's get_player_name.
    global _PLAYER_CACHE
    if _PLAYER_CACHE:
        return _PLAYER_CACHE
    prefs = _read_json(_base() / "phone_settings.json", {})
    name = ""
    if isinstance(prefs, dict):
        name = str(prefs.get("player_name") or "").strip()
    _PLAYER_CACHE = name or "我"
    return _PLAYER_CACHE


# ── data shaping ─────────────────────────────────────────────────────

def _messages_path() -> Path | None:
    d = _richest("messages.json")
    return (d / "messages.json") if d else None


def _threads() -> list[dict[str, Any]]:
    """Conversation list: one row per character with a message thread or contact."""
    msgs: dict[str, list] = _read_json(_messages_path(), {}) or {}
    contacts = _contacts()
    names: list[str] = [n for n in dict.fromkeys([*msgs.keys(), *contacts]) if not _is_junk_name(str(n))]
    rows: list[dict[str, Any]] = []
    for name in names:
        thread = msgs.get(name) or []
        last = thread[-1] if thread else None
        unread = sum(1 for m in thread if not m.get("is_user") and not m.get("read"))
        preview = ""
        if last:
            preview = str(last.get("text", "")).replace("\n", " ")
            if len(preview) > 30:
                preview = preview[:29] + "…"
        rows.append({
            "name": name,
            "preview": preview or ("还没有开始对话" if name in contacts else ""),
            "unread": unread,
            "count": len(thread),
            "lastIdx": int(last.get("idx", 0)) if last else 0,
        })
    rows.sort(key=lambda r: (r["count"] > 0, r["unread"] > 0, r["lastIdx"]), reverse=True)
    return rows


def _thread(name: str) -> list[dict[str, Any]]:
    msgs: dict[str, list] = _read_json(_messages_path(), {}) or {}
    out: list[dict[str, Any]] = []
    for m in msgs.get(name, []):
        out.append({
            "text": str(m.get("text", "")),
            "isUser": bool(m.get("is_user", False)),
            "idx": int(m.get("idx", 0)),
        })
    return out


def _is_junk_name(name: str) -> bool:
    """Names that must never surface as a contact/thread: monitoring-intel headers and
    markers. (A hacked/监控 mode PHONE line once leaked '【监控情报】…' in as a contact.)"""
    n = (name or "").strip()
    return (not n) or n.startswith("【") or "监控情报" in n or "浏览器搜索记录" in n


def _contacts() -> list[str]:
    """Contacts in the ACTIVE session only.

    The legacy phone bound to a single --history session. Unioning across every save
    (an early preview shortcut) leaked other saves' contacts in as '还没有开始对话' rows
    and dragged junk from old sessions into the current phone. Read just the active
    session, like every other reader here.
    """
    d = _richest("contacts.json")
    data = _read_json((d / "contacts.json") if d else None, {}) or {}
    names: list[str] = []
    for name in (data.get("contacts") or {}).keys():
        name = str(name)
        if not _is_junk_name(name) and name not in names:
            names.append(name)
    return names


def _moments() -> list[dict[str, Any]]:
    d = _richest("moments.json")
    data = _read_json((d / "moments.json") if d else None, {}) or {}
    player = _player_name()

    def disp(author: str) -> str:
        return player if author == PLAYER else author

    out: list[dict[str, Any]] = []
    for p in reversed(data.get("posts") or []):  # newest first
        out.append({
            "id": p.get("id"),
            "author": disp(str(p.get("author", ""))),
            "text": str(p.get("text", "")),
            "imageDesc": p.get("image_desc"),
            "likes": [disp(x) for x in (p.get("likes") or [])],
            "comments": [
                {"author": disp(str(c.get("author", ""))), "text": str(c.get("text", "")),
                 "replyTo": disp(str(c.get("reply_to", "") or ""))}
                for c in (p.get("comments") or [])
            ],
            "ts": p.get("ts"),
        })
    return out


def _coerce_int(v: Any) -> int:
    """Best-effort int from an id that may arrive as '#3', '3', or 3."""
    try:
        return int(str(v).strip().lstrip("#") or 0)
    except Exception:
        return 0


def _post_moment(text: str, image_desc: str = "") -> dict[str, Any]:
    """Player publishes a moment, then nudges characters to react via their LLM tools."""
    text = (text or "").strip()
    image_desc = (image_desc or "").strip()
    if not text and not image_desc:
        return {"ok": False, "error": "empty"}
    pid = 0
    try:
        from plugins.shinsekai_chat_phone import phone_core
        pid = phone_core.moment_add_post(_player_name(), text, image_desc, is_user=True)
    except Exception:
        logger.debug("post_moment failed", exc_info=True)
    try:
        import threading
        img = f"（配图：{image_desc}）" if image_desc else ""
        runtime_text = (f'[朋友圈] 玩家发布了一条新动态（#{pid}）：“{text}”{img}。'
                        f'请让通讯录里合适的角色用 comment_moment / like_moment 工具自然地评论或点赞，'
                        f'角色之间也可以互相接话；不要输出对话。')
        threading.Thread(target=_trigger_runtime_turn, args=(runtime_text,),
                         daemon=True, name="phone-moment-trigger").start()
    except Exception:
        pass
    return {"ok": bool(pid), "id": pid}


def _moment_comment(post_id: Any, text: str, reply_to: str = "") -> dict[str, Any]:
    """Player comments on a moment, then nudges the addressed character to reply."""
    text = (text or "").strip()
    reply_to = (reply_to or "").strip()
    pid = _coerce_int(post_id)
    if not text or not pid:
        return {"ok": False, "error": "empty"}
    cid = None
    try:
        from plugins.shinsekai_chat_phone import phone_core
        cid = phone_core.moment_add_comment(pid, _player_name(), text, is_user=True, reply_to=reply_to)
    except Exception:
        logger.debug("moment_comment failed", exc_info=True)
    try:
        import threading
        tgt = f"，回复的是 {reply_to}" if reply_to else ""
        runtime_text = (f'[朋友圈] 玩家在动态 #{pid} 下发表了评论：“{text}”{tgt}。'
                        f'若这条评论是冲着某个角色说的，请让该角色用 comment_moment(编号,角色,内容,reply_to=玩家) 回复；'
                        f'不要输出对话。')
        threading.Thread(target=_trigger_runtime_turn, args=(runtime_text,),
                         daemon=True, name="phone-moment-trigger").start()
    except Exception:
        pass
    return {"ok": bool(cid), "id": cid}


def _moment_like(post_id: Any) -> dict[str, Any]:
    """Player likes a moment (no runtime turn needed)."""
    pid = _coerce_int(post_id)
    if not pid:
        return {"ok": False, "error": "empty"}
    ok = False
    try:
        from plugins.shinsekai_chat_phone import phone_core
        ok = phone_core.moment_add_like(pid, _player_name(), is_user=True)
    except Exception:
        logger.debug("moment_like failed", exc_info=True)
    return {"ok": bool(ok)}


def _resolve_bridge_state():
    """Reach the live BridgeState without re-importing the bridge module.

    The bridge runs either as ``__main__`` (python frontend_bridge.py) or as an
    imported module (webui_react.py). ``import frontend_bridge`` would create a
    second module instance with a fresh (None) state, so instead we look it up in
    ``sys.modules`` and take the first that actually holds a state.
    """
    import sys
    for key in ("frontend_bridge", "__main__"):
        mod = sys.modules.get(key)
        getter = getattr(mod, "get_bridge_state", None) if mod is not None else None
        if getter is None:
            continue
        try:
            st = getter()
        except Exception:
            st = None
        if st is not None:
            return st
    return None


def _send_runtime_command(command: dict) -> bool:
    """Send a raw command to the live chat runtime over the chat stream (best-effort).
    Used for send-message turn injection and for skip-speech (the call-hangup interrupt)."""
    try:
        state = _resolve_bridge_state()
        if state is None:
            return False
        cs = getattr(state, "chat_stream", None)
        sess = getattr(state, "chat_session", None) or {}
        sid = str((sess.get("sessionId") if isinstance(sess, dict) else "") or "").strip()
        if cs is None or not sid:
            return False
        import uuid
        command = dict(command)
        command.setdefault("cmdId", uuid.uuid4().hex)
        return bool(cs.send_command(sid, command))
    except Exception:
        logger.debug("phone runtime command failed", exc_info=True)
        return False


def _trigger_runtime_turn(text: str) -> bool:
    """Inject a user turn (send-message) to the live runtime — calls the stream service
    directly so the private [短信]/[群聊]/[通话] trigger doesn't flash as a stage bubble."""
    return _send_runtime_command({"type": "send-message", "payload": {"text": text, "attachments": []}})


# ── Calls: inject the EXACT legacy turns + interrupt current speech on hangup ──

def _call_answer(name: str, video: bool) -> dict[str, Any]:
    """Player accepted an incoming (character-initiated) call → the caller opens up."""
    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "empty"}
    kind = "视频通话" if video else "通话"
    text = (f"[{kind}] {name}主动打给玩家，玩家接听了。这通电话是{name}自己发起的——"
            f"请{name}结合当前剧情、近况和你们之间的关系，主动开口，带着自己的目的或心情引出话题、"
            f"推进剧情（是{name}此刻有话想对玩家说、主动联系，不是玩家找{name}、也不是玩家让他打的），"
            f"不要反问玩家「有什么事」「找我干嘛」。请只输出{name}的对话。")
    import threading
    threading.Thread(target=_trigger_runtime_turn, args=(text,), daemon=True, name="phone-call-answer").start()
    return {"ok": True}


def _call_dial(name: str, video: bool) -> dict[str, Any]:
    """Player dialed a contact out → the character is the answerer."""
    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "empty"}
    if video:
        text = f"[视频通话] 玩家主动拨打了{name}的视频电话。{name}是接听方。请只输出{name}的对话。"
    else:
        text = f"[通话] 玩家主动拨打了{name}的电话。{name}是接听方。请只输出{name}的对话。"
    import threading
    threading.Thread(target=_trigger_runtime_turn, args=(text,), daemon=True, name="phone-call-dial").start()
    return {"ok": True}


def _call_hangup(name: str, duration: int, incoming: bool, video: bool) -> dict[str, Any]:
    """Player hangs up: interrupt current speech (skip-speech), log, then the character reacts."""
    name = (name or "").strip()

    def _run():
        _send_runtime_command({"type": "skip-speech"})  # 打断: cut the character's current speech now
        try:
            from plugins.shinsekai_chat_phone import phone_core
            ctype = ("incoming" if incoming else "outgoing") + ("_video" if video else "")
            phone_core.log_call(name, max(int(duration or 0), 1), ctype)
        except Exception:
            logger.debug("call log failed", exc_info=True)
        if name:
            _trigger_runtime_turn(
                f"[通话结束] 用户挂断了电话。请先以旁白身份写一句用户挂断电话的描述，再输出{name}的反应。")

    import threading
    threading.Thread(target=_run, daemon=True, name="phone-call-hangup").start()
    return {"ok": True}


def _call_decline(name: str, video: bool) -> dict[str, Any]:
    """Player declined / rang out → log a missed call, no LLM turn."""
    name = (name or "").strip()
    if name:
        try:
            from plugins.shinsekai_chat_phone import phone_core
            phone_core.log_call(name, 0, "missed_video" if video else "missed")
        except Exception:
            logger.debug("call decline log failed", exc_info=True)
    return {"ok": True}


def _send_sms(name: str, text: str) -> dict[str, Any]:
    """Append the player's SMS, then trigger the character's LLM reply (route C inc.2).

    The optimistic append shows the bubble instantly; the reply arrives async
    (character's send_sms tool -> messages.json) and the frontend polls the thread
    to pick it up. In React mode nothing holds messages.json in memory, so the
    append persists (no overwrite) — bridge writes the player line, runtime appends
    the reply, both via phone_core.
    """
    name = (name or "").strip()
    text = (text or "").strip()
    if not name or not text:
        return {"ok": False, "error": "empty"}
    try:
        from plugins.shinsekai_chat_phone import phone_core
        ok = phone_core.send_player_sms(name, text)
    except Exception:
        logger.debug("phone send failed", exc_info=True)
        ok = False
    # Trigger the reply through the live runtime off-thread, so this RPC returns
    # instantly even when no runtime is connected (send_command waits up to ~2s).
    try:
        import threading
        stranger = False
        try:
            if phone_core.is_stranger_contact(name):
                # baffled framing only until the character has replied at least once
                prior = phone_core.messages_for(name)
                stranger = not any(isinstance(m, dict) and not m.get("is_user") for m in prior)
        except Exception:
            stranger = False
        if stranger:
            runtime_text = (f'[短信] {name}收到了一条陌生短信："{text}"。'
                            f'发信人不在{name}的通讯录里，{name}也想不起何时把号码给过对方，你们或许素未谋面——'
                            f'请让{name}结合人设自然反应（困惑、警惕或好奇皆可），不要假装早就认识对方。'
                            f'请调用 send_sms 工具回复，不要输出对话。')
        else:
            runtime_text = (f'[短信] {name}收到了你的短信："{text}"。'
                            f'请调用 send_sms 工具回复，不要输出对话。')
        threading.Thread(target=_trigger_runtime_turn, args=(runtime_text,),
                         daemon=True, name="phone-sms-trigger").start()
    except Exception:
        pass
    return {"ok": bool(ok), "ts": time.time()}


def _send_group(name: str, text: str) -> dict[str, Any]:
    """Append the player's group message, then trigger character replies (route C).

    Mirrors _send_sms but formats the runtime turn as [群聊] (the injected group
    protocol keys on that prefix to force replies through the send_group_sms tool).
    """
    name = (name or "").strip()
    text = (text or "").strip()
    if not name or not text:
        return {"ok": False, "error": "empty"}
    members: list[str] = []
    try:
        from plugins.shinsekai_chat_phone import phone_core
        ok = phone_core.group_send_player(name, text)
        members = phone_core.group_members(name)
    except Exception:
        logger.debug("phone group send failed", exc_info=True)
        ok = False
    try:
        import threading
        mstr = "、".join(members)
        runtime_text = (f'[群聊] 群「{name}」（成员：{mstr}）里，玩家发了一条消息："{text}"。'
                        f'请由群里相关角色用 send_group_sms 工具回复（可多个角色、多条，'
                        f'角色之间也可以互相接话；不相关的角色可以不回）。不要输出对话。')
        threading.Thread(target=_trigger_runtime_turn, args=(runtime_text,),
                         daemon=True, name="phone-group-trigger").start()
    except Exception:
        pass
    return {"ok": bool(ok), "ts": time.time()}


# ── calls / browser / settings ───────────────────────────────────────

_RESERVED = {"COT", "NARR", "CALL", "CHOICE", "STAT", "PHONE", "CG", "bgm", "旁白"}


def _call_log() -> list[dict[str, Any]]:
    """Voice + video call history merged, newest first (video flagged)."""
    out: list[dict[str, Any]] = []
    for fn, is_video in (("call_log.json", False), ("video_call_log.json", True)):
        d = _richest(fn)
        raw = _read_json((d / fn) if d else None, [])
        for c in raw if isinstance(raw, list) else []:
            name = str(c.get("name", "")).strip()
            if not name or name in _RESERVED:
                continue
            raw_type = str(c.get("type", "") or "").strip().lower()
            kind = "outgoing" if "out" in raw_type else "incoming" if "in" in raw_type else "missed"
            out.append({
                "name": name,
                "duration": int(c.get("duration", 0) or 0),
                "type": kind,
                "video": bool(is_video or "video" in raw_type),
                "ts": c.get("timestamp"),
            })
    out.sort(key=lambda c: (c.get("ts") or 0), reverse=True)
    return out


def _groups() -> list[dict[str, Any]]:
    """Group chats: name, members, messages (player/char/system), unread, preview."""
    d = _richest("groups.json")
    data = _read_json((d / "groups.json") if d else None, {}) or {}
    groups = data.get("groups") or {}
    player = _player_name()
    out: list[dict[str, Any]] = []
    for name, g in (groups.items() if isinstance(groups, dict) else []):
        if not isinstance(g, dict):
            continue
        raw_msgs = g.get("messages") or []
        msgs: list[dict[str, Any]] = []
        for m in raw_msgs:
            is_user = bool(m.get("is_user", False))
            msgs.append({
                "who": player if is_user else str(m.get("sender", "")),
                "text": str(m.get("text", "")),
                "isUser": is_user,
                "isSystem": bool(m.get("is_system", False)),
                "idx": int(m.get("idx", 0)),
            })
        last = raw_msgs[-1] if raw_msgs else None
        preview = ""
        if last:
            if last.get("is_system"):
                preview = str(last.get("text", ""))
            else:
                who = player if last.get("is_user") else str(last.get("sender", ""))
                preview = f"{who}: {last.get('text', '')}"
            preview = preview.replace("\n", " ")
            if len(preview) > 30:
                preview = preview[:29] + "…"
        out.append({
            "name": str(g.get("name", name)),
            "members": [str(x) for x in (g.get("members") or [])],
            "messages": msgs,
            "unread": int(g.get("unread", 0) or 0),
            "preview": preview,
            "count": len(msgs),
        })
    out.sort(key=lambda x: x["count"] > 0, reverse=True)
    return out


def _browser_history() -> list[str]:
    d = _richest("browser_history.json")
    raw = _read_json((d / "browser_history.json") if d else None, [])
    return [str(x) for x in raw if str(x).strip()] if isinstance(raw, list) else []


def _browser_results() -> list[dict[str, Any]]:
    """LLM-generated search-result sets (newest first)."""
    try:
        from plugins.shinsekai_chat_phone import phone_core
        return phone_core.get_browser_results()
    except Exception:
        return []


def _browser_search(query: str) -> dict[str, Any]:
    """Record the query, then ask the runtime LLM (as a search engine) for results."""
    query = (query or "").strip()
    if not query:
        return {"ok": False, "error": "empty"}
    try:
        from plugins.shinsekai_chat_phone import phone_core
        phone_core.add_browser_history(query)
    except Exception:
        pass
    try:
        import threading
        runtime_text = (f'[浏览器] 玩家在浏览器里搜索了：“{query}”。'
                        f'请你此刻作为这个世界的搜索引擎（不是角色本人），调用 browser_result 工具，'
                        f'为这次搜索生成 4-6 条具体、劲爆、吸睛的搜索结果；只调用工具，不要输出对话或旁白。')
        threading.Thread(target=_trigger_runtime_turn, args=(runtime_text,),
                         daemon=True, name="phone-browser-trigger").start()
    except Exception:
        pass
    return {"ok": True}


def _settings() -> dict[str, Any]:
    prefs = _read_json(_base() / "phone_settings.json", {}) or {}
    sd = _richest("phone_session.json")
    sess = _read_json((sd / "phone_session.json") if sd else None, {}) or {}
    fc = _read_json(_freq_path(), {}) or {}
    if not fc.get("_enabled", True):
        level = 0
    else:
        scale = float(fc.get("_scale", 1.0) or 1.0)
        level = 1 if scale <= 0.6 else 3 if scale >= 1.8 else 2
    return {
        "player": str(prefs.get("player_name") or _player_name()),
        "signature": str(prefs.get("signature", "") or ""),
        "theme": str(prefs.get("theme", "#FFFAFA") or "#FFFAFA"),
        "dnd": bool(sess.get("dnd", False)),
        "proactiveLevel": level,
        "hacked": [str(x) for x in (sess.get("hacked_characters") or [])],
    }


def _unknown() -> list[str]:
    """Active-session contacts marked known=false — shown as 未知联系人 (real name hidden)."""
    try:
        from plugins.shinsekai_chat_phone import phone_core
        return phone_core.unknown_names()
    except Exception:
        return []


def _avatars() -> dict[str, Any]:
    """Uploaded per-character avatars ({name: dataURI}), global across saves."""
    try:
        from plugins.shinsekai_chat_phone import phone_core
        return phone_core.get_web_avatars()
    except Exception:
        return {}


def _all() -> dict[str, Any]:
    """Everything the phone needs in one call, so navigation is client-side."""
    md = _richest("messages.json")
    raw: dict[str, list] = _read_json((md / "messages.json") if md else None, {}) or {}
    messages: dict[str, list[dict[str, Any]]] = {}
    for name, thread in raw.items():
        if _is_junk_name(str(name)):
            continue
        messages[name] = [
            {"text": str(m.get("text", "")), "isUser": bool(m.get("is_user", False)), "idx": int(m.get("idx", 0))}
            for m in thread
        ]
    return {
        "player": _player_name(),
        "threads": _threads(),
        "messages": messages,
        "contacts": _contacts(),
        "unknown": _unknown(),
        "avatars": _avatars(),
        "moments": _moments(),
        "groups": _groups(),
        "calls": _call_log(),
        "browser": _browser_history(),
        "settings": _settings(),
    }


def _write_prefs(update: dict[str, Any]) -> None:
    """Merge into the global phone_settings.json (theme / player profile)."""
    global _PLAYER_CACHE
    path = _base() / "phone_settings.json"
    data = _read_json(path, {}) or {}
    if not isinstance(data, dict):
        data = {}
    data.update(update)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        logger.debug("phone prefs write failed", exc_info=True)
    if "player_name" in update:
        _PLAYER_CACHE = None


def _write_session(update: dict[str, Any]) -> None:
    """Merge into the active session's phone_session.json (dnd, etc.)."""
    d = _richest("phone_session.json") or _richest("messages.json")
    if d is None:
        dirs = _session_dirs()
        d = dirs[0] if dirs else _base()
    path = d / "phone_session.json"
    data = _read_json(path, {}) or {}
    if not isinstance(data, dict):
        data = {}
    data.update(update)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        logger.debug("phone session write failed", exc_info=True)


def _freq_path() -> Path:
    return _base() / "freq_config.json"


def _set_freq(level: int) -> None:
    """Persist the global proactive-contact level into freq_config.json.

    level: 0=off, 1=low, 2=normal, 3=high. Stored as (_enabled, _scale) so the
    runtime proactive monitor — which re-reads this file each tick — applies it
    live; any per-character overrides already in the file are preserved.
    """
    path = _freq_path()
    data = _read_json(path, {}) or {}
    if not isinstance(data, dict):
        data = {}
    scale = {0: 0.0, 1: 0.5, 2: 1.0, 3: 2.0}.get(int(level), 1.0)
    data["_enabled"] = int(level) != 0
    data["_scale"] = scale
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        logger.debug("phone freq write failed", exc_info=True)


# ── Voice memos (录音) — merge the character's own TTS audio (Qt-free) ──

_AUDIO_CACHE = Path("cache") / "audio"
_AUDIO_EXTS = (".wav", ".mp3", ".ogg")


def _rec_dir() -> Path:
    return _base() / "recordings"


def _rec_memos_path() -> Path:
    return _rec_dir() / "memos.json"


def _rec_list() -> list[dict[str, Any]]:
    data = _read_json(_rec_memos_path(), [])
    return data if isinstance(data, list) else []


def _rec_save(memos: list) -> None:
    try:
        p = _rec_memos_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(memos[:100], ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        logger.debug("rec save failed", exc_info=True)


def _write_recording_flag(active: bool) -> None:
    """Tiny flag the runtime reads each turn so the character may notice recording."""
    try:
        p = _base() / "recording.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"active": bool(active), "since": time.time()}, ensure_ascii=False),
                     encoding="utf-8")
    except Exception:
        pass


def _merge_wavs(files: list, out_dir: Path):
    """Merge captured audio into one wav (pydub if present, else stdlib concat)."""
    files = [f for f in files if f]
    if not files:
        return None
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    out_path = out_dir / f"memo_{int(time.time())}.wav"
    try:
        from pydub import AudioSegment  # type: ignore
        combined = AudioSegment.empty()
        n = 0
        for fp in files:
            try:
                combined += AudioSegment.from_file(str(fp)); n += 1
            except Exception:
                pass
        if n and len(combined) > 0:
            combined.export(str(out_path), format="wav")
            return out_path
    except Exception:
        pass
    if len(files) == 1:
        try:
            import shutil
            shutil.copy2(str(files[0]), str(out_path))
            return out_path
        except Exception:
            return None
    try:
        import wave
        frames: list = []
        params = None
        for fp in files:
            try:
                with wave.open(str(fp), "rb") as wf:
                    if params is None:
                        params = wf.getparams()
                    frames.append(wf.readframes(wf.getnframes()))
            except Exception:
                pass
        if params and frames:
            with wave.open(str(out_path), "wb") as wf:
                wf.setparams(params)
                for frm in frames:
                    wf.writeframes(frm)
            return out_path
    except Exception:
        pass
    return None


class _Recorder:
    """Watches cache/audio for the character's TTS output and merges it (mirrors the
    old Qt voice_memo_app, Qt-free). Runs in the bridge, which shares the app cwd."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = False
        self.start_ts = 0.0
        self._known: set = set()
        self._staged: list = []
        self._thread = None
        self._stop_evt = None

    def _capture_new(self, stage: Path, shutil_mod) -> None:
        """Copy any cache/audio file we haven't seen yet (cache rotates every 100)."""
        if not _AUDIO_CACHE.is_dir():
            return
        try:
            entries = sorted(_AUDIO_CACHE.iterdir(), key=lambda p: p.stat().st_mtime)
        except Exception:
            return
        for p in entries:
            if p.suffix.lower() not in _AUDIO_EXTS:
                continue
            with self._lock:
                if p.name in self._known:
                    continue
                self._known.add(p.name)
            try:
                dst = stage / f"{int(time.time() * 1000)}_{p.name}"
                shutil_mod.copy2(str(p), str(dst))
                with self._lock:
                    self._staged.append(dst)
            except Exception:
                pass

    def _watch(self) -> None:
        import shutil
        stage = _rec_dir() / "_staging"
        try:
            stage.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        evt = self._stop_evt
        while evt is not None and not evt.wait(1.5):
            with self._lock:
                if not self.active:
                    break
            self._capture_new(stage, shutil)

    def start(self) -> dict:
        with self._lock:
            if self.active:
                return {"ok": True, "active": True}
            self.active = True
            self.start_ts = time.time()
            self._staged = []
            self._known = set()
            if _AUDIO_CACHE.is_dir():
                try:
                    for p in _AUDIO_CACHE.iterdir():
                        if p.suffix.lower() in _AUDIO_EXTS:
                            self._known.add(p.name)
                except Exception:
                    pass
            self._stop_evt = threading.Event()
            self._thread = threading.Thread(target=self._watch, daemon=True, name="phone-rec-watch")
            self._thread.start()
        _write_recording_flag(True)
        return {"ok": True, "active": True}

    def stop(self) -> dict:
        import shutil
        with self._lock:
            if not self.active:
                _write_recording_flag(False)
                return {"ok": False, "error": "not_recording"}
            self.active = False
            evt = self._stop_evt
            self._stop_evt = None
            dur = int(time.time() - self.start_ts)
        if evt:
            evt.set()
        th = self._thread
        if th:
            th.join(timeout=3)
        self._capture_new(_rec_dir() / "_staging", shutil)   # final catch
        with self._lock:
            staged = list(self._staged)
        merged = _merge_wavs(staged, _rec_dir())
        memo = {
            "id": int(time.time() * 1000),
            "title": time.strftime("%m/%d %H:%M"),
            "duration": dur,
            "ts": time.time(),
            "file_count": len(staged),
            "merged": (merged.name if merged else None),
        }
        memos = _rec_list()
        memos.insert(0, memo)
        _rec_save(memos)
        try:
            shutil.rmtree(str(_rec_dir() / "_staging"), ignore_errors=True)
        except Exception:
            pass
        _write_recording_flag(False)
        return {"ok": True, "memo": memo}

    def status(self) -> dict:
        with self._lock:
            return {
                "active": self.active,
                "elapsed": int(time.time() - self.start_ts) if self.active else 0,
                "captured": len(self._staged),
            }


_RECORDER = _Recorder()


def _rec_delete(mid) -> None:
    _rec_save([m for m in _rec_list() if str(m.get("id")) != str(mid)])


def _rec_audio(mid) -> dict:
    """Return the merged recording as a base64 data URI for in-webview playback."""
    import base64
    for m in _rec_list():
        if str(m.get("id")) == str(mid) and m.get("merged"):
            fp = _rec_dir() / str(m["merged"])
            try:
                raw = fp.read_bytes()
                if 0 < len(raw) <= 6_000_000:
                    return {"data": "data:audio/wav;base64," + base64.b64encode(raw).decode("ascii")}
            except Exception:
                pass
    return {"data": ""}


# ── RPC entry point ──────────────────────────────────────────────────

def rpc(values: Mapping[str, Any]) -> dict[str, Any]:
    """Single dispatch point for the phone iframe. Returns a JSON-safe dict."""
    cmd = str((values or {}).get("cmd") or "").strip()
    args = (values or {}).get("args") or {}
    try:
        if cmd == "debug":
            import os
            base = _base()
            return {
                "cwd": os.getcwd(),
                "baseAbs": str(base.resolve()),
                "baseExists": base.is_dir(),
                "sessions": [d.name for d in _session_dirs()],
                "messagesFrom": str(_richest("messages.json")),
                "momentsFrom": str(_richest("moments.json")),
            }
        if cmd == "all":
            return _all()
        if cmd == "snapshot":
            return {
                "player": _player_name(),
                "threads": _threads(),
                "contacts": _contacts(),
                "momentCount": len(_moments()),
            }
        if cmd == "threads":
            return {"threads": _threads()}
        if cmd == "thread":
            _tn = str(args.get("name", ""))
            return {"name": args.get("name", ""), "messages": _thread(_tn), "unknown": (_tn in _unknown())}
        if cmd == "contacts":
            return {"contacts": _contacts()}
        if cmd == "moments":
            return {"player": _player_name(), "posts": _moments()}
        if cmd == "post_moment":
            return _post_moment(str(args.get("text", "")), str(args.get("imageDesc", "")))
        if cmd == "moment_comment":
            return _moment_comment(args.get("post_id"), str(args.get("text", "")), str(args.get("reply_to", "")))
        if cmd == "moment_like":
            return _moment_like(args.get("post_id"))
        if cmd == "groups":
            return {"groups": _groups()}
        if cmd == "group":
            _nm = str(args.get("name", ""))
            return {"group": next((x for x in _groups() if x.get("name") == _nm), None)}
        if cmd == "create_group":
            from plugins.shinsekai_chat_phone import phone_core
            _gn = str(args.get("name", "")).strip()
            _mem = [str(m).strip() for m in (args.get("members") or []) if str(m).strip()]
            _gid = phone_core.group_create(_gn, _mem) if _gn else ""
            return {"ok": bool(_gid), "name": _gid}
        if cmd == "call_log":
            return {"calls": _call_log()}
        if cmd == "browser":
            return {"history": _browser_history()}
        if cmd == "browser_search":
            return _browser_search(str(args.get("query", "")))
        if cmd == "browser_results":
            return {"results": _browser_results()}
        if cmd == "music_status":
            from plugins.shinsekai_chat_phone import phone_core
            return {"path": phone_core.get_music_path()}
        if cmd == "music_set_path":
            from plugins.shinsekai_chat_phone import phone_core
            phone_core.set_music_path(str(args.get("path", "")))
            return {"ok": True}
        if cmd == "music_launch":
            from plugins.shinsekai_chat_phone import phone_core
            ok, msg = phone_core.launch_music()
            return {"ok": bool(ok), "error": ("" if ok else msg)}
        if cmd == "rec_start":
            return _RECORDER.start()
        if cmd == "rec_stop":
            return _RECORDER.stop()
        if cmd == "rec_status":
            return _RECORDER.status()
        if cmd == "rec_list":
            return {"memos": _rec_list()}
        if cmd == "rec_delete":
            _rec_delete(args.get("id"))
            return {"ok": True}
        if cmd == "rec_audio":
            return _rec_audio(args.get("id"))
        if cmd == "settings":
            return _settings()
        if cmd == "set_profile":
            _write_prefs({"player_name": (str(args.get("name", "")).strip() or "我"), "signature": str(args.get("signature", "") or "")})
            return {"ok": True}
        if cmd == "set_dnd":
            _write_session({"dnd": bool(args.get("on"))})
            return {"ok": True}
        if cmd == "set_theme":
            _write_prefs({"theme": str(args.get("theme", "") or "#FFFAFA")})
            return {"ok": True}
        if cmd == "set_freq":
            _set_freq(int(args.get("level", 2)))
            return {"ok": True}
        if cmd == "send_sms":
            return _send_sms(str(args.get("name", "")), str(args.get("text", "")))
        if cmd == "add_contact":
            from plugins.shinsekai_chat_phone import phone_core
            _cn = str(args.get("name", "")).strip()
            if not _cn:
                return {"ok": False, "error": "empty"}
            ok = phone_core.add_manual_contact(_cn, stranger=bool(args.get("stranger", True)))
            return {"ok": bool(ok), "name": _cn}
        if cmd == "send_group":
            return _send_group(str(args.get("name", "")), str(args.get("text", "")))
        if cmd == "mark_read":
            from plugins.shinsekai_chat_phone import phone_core
            return {"ok": bool(phone_core.mark_thread_read(str(args.get("name", ""))))}
        if cmd == "set_avatar":
            from plugins.shinsekai_chat_phone import phone_core
            return {"ok": bool(phone_core.set_web_avatar(str(args.get("name", "")), str(args.get("data", ""))))}
        if cmd == "call_answer":
            return _call_answer(str(args.get("name", "")), bool(args.get("video")))
        if cmd == "call_dial":
            return _call_dial(str(args.get("name", "")), bool(args.get("video")))
        if cmd == "call_hangup":
            return _call_hangup(str(args.get("name", "")), args.get("duration", 0), bool(args.get("incoming")), bool(args.get("video")))
        if cmd == "call_decline":
            return _call_decline(str(args.get("name", "")), bool(args.get("video")))
        return {"ok": False, "error": f"unknown cmd: {cmd}"}
    except Exception as exc:  # never 500 the iframe
        logger.exception("phone rpc failed: %s", cmd)
        return {"ok": False, "error": str(exc)}
