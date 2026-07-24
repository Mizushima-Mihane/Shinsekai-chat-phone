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
    names: list[str] = list(dict.fromkeys([*msgs.keys(), *contacts]))
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


def _contacts() -> list[str]:
    """Union of contacts across the global file and every session dir."""
    names: list[str] = []
    paths = [_base() / "contacts.json"] + [d / "contacts.json" for d in _session_dirs()]
    for path in paths:
        data = _read_json(path, {}) or {}
        for name in (data.get("contacts") or {}).keys():
            if name and name.strip() and name not in names:
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
                {"author": disp(str(c.get("author", ""))), "text": str(c.get("text", ""))}
                for c in (p.get("comments") or [])
            ],
            "ts": p.get("ts"),
        })
    return out


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


def _trigger_runtime_turn(text: str) -> bool:
    """Push a user turn to the live chat runtime so the LLM responds (route C inc.2/3).

    Mirrors the main chat input's ``send-message`` command, but calls the stream
    service directly (bypassing the snapshot patch) so the private [短信]/[群聊]
    trigger text does NOT flash as a user bubble on the main stage. The character's
    reply comes back through the normal loop via the send_sms / send_group_sms
    tools. Best-effort: if no chat runtime is connected it simply no-ops.
    """
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
        return bool(cs.send_command(sid, {
            "type": "send-message",
            "payload": {"text": text, "attachments": []},
            "cmdId": uuid.uuid4().hex,
        }))
    except Exception:
        logger.debug("phone runtime trigger failed", exc_info=True)
        return False


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


def _settings() -> dict[str, Any]:
    prefs = _read_json(_base() / "phone_settings.json", {}) or {}
    sd = _richest("phone_session.json")
    sess = _read_json((sd / "phone_session.json") if sd else None, {}) or {}
    return {
        "player": str(prefs.get("player_name") or _player_name()),
        "signature": str(prefs.get("signature", "") or ""),
        "theme": str(prefs.get("theme", "#FFFAFA") or "#FFFAFA"),
        "dnd": bool(sess.get("dnd", False)),
        "hacked": [str(x) for x in (sess.get("hacked_characters") or [])],
    }


def _all() -> dict[str, Any]:
    """Everything the phone needs in one call, so navigation is client-side."""
    md = _richest("messages.json")
    raw: dict[str, list] = _read_json((md / "messages.json") if md else None, {}) or {}
    messages: dict[str, list[dict[str, Any]]] = {}
    for name, thread in raw.items():
        messages[name] = [
            {"text": str(m.get("text", "")), "isUser": bool(m.get("is_user", False)), "idx": int(m.get("idx", 0))}
            for m in thread
        ]
    return {
        "player": _player_name(),
        "threads": _threads(),
        "messages": messages,
        "contacts": _contacts(),
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
            return {"name": args.get("name", ""), "messages": _thread(str(args.get("name", "")))}
        if cmd == "contacts":
            return {"contacts": _contacts()}
        if cmd == "moments":
            return {"player": _player_name(), "posts": _moments()}
        if cmd == "groups":
            return {"groups": _groups()}
        if cmd == "group":
            _nm = str(args.get("name", ""))
            return {"group": next((x for x in _groups() if x.get("name") == _nm), None)}
        if cmd == "call_log":
            return {"calls": _call_log()}
        if cmd == "browser":
            return {"history": _browser_history()}
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
        if cmd == "send_sms":
            return _send_sms(str(args.get("name", "")), str(args.get("text", "")))
        if cmd == "send_group":
            return _send_group(str(args.get("name", "")), str(args.get("text", "")))
        return {"ok": False, "error": f"unknown cmd: {cmd}"}
    except Exception as exc:  # never 500 the iframe
        logger.exception("phone rpc failed: %s", cmd)
        return {"ok": False, "error": str(exc)}
