"""Qt-free phone core: session resolution + store writes usable in ANY process.

The legacy phone kept live state in a Qt widget (``_phone_widget``). In the React
desktop app there is no widget, so the LLM tools (runtime process) and the web
phone (bridge process) both go through this module instead.

Session binding: the runtime process knows the active chat session from its
``--history`` argument and stamps an ``_active_session`` marker; the bridge (no
``--history``) reads that marker. Both then read/write the same session dir, so an
SMS the character sends via a tool shows up in the player's phone immediately.

Persistence format matches the legacy phone:
    <session>/messages.json  {name: [{text, is_user, idx, read}]}
    <session>/contacts.json  {contacts: {name: {added_at, known}}}
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

_BASE = Path("data/plugins/com.shinsekai.chat_phone")
_MARKER = "_active_session"
_RESERVED = {"旁白", "NARR", "CALL", "COT", "CHOICE", "STAT", "PHONE", "bgm", "CG"}
_lock = threading.Lock()


def _is_junk_name(name: str) -> bool:
    """Reject pseudo-speaker markers + monitoring-intel headers that must never become a
    contact/thread (hacked/监控 mode once leaked '【监控情报】…' in as a contact)."""
    n = (name or "").strip()
    return (not n) or n in _RESERVED or n.startswith("【") or "监控情报" in n or "浏览器搜索记录" in n


def _base() -> Path:
    return _BASE


def _read_json(path: Path | None, default):
    try:
        if path is not None and path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _write_json(path: Path, data) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def _session_from_history() -> str | None:
    """The runtime's current session hash, from the ``--history`` launch arg."""
    for arg in sys.argv:
        if arg.startswith("--history="):
            raw = arg.split("=", 1)[1].strip().strip('"').strip("'")
            if raw:
                p = Path(raw)
                name = (p if p.suffix.lower() != ".json" else p.parent).name
                return name or None
            break
    return None


def _richest(name: str) -> Path | None:
    base = _base()
    best: Path | None = None
    best_size = -1
    if base.is_dir():
        for d in base.iterdir():
            if not d.is_dir():
                continue
            fp = d / name
            try:
                size = fp.stat().st_size if fp.is_file() else -1
            except OSError:
                size = -1
            if size > best_size:
                best_size = size
                best = d
    return best


def session_dir(write_marker: bool = True) -> Path:
    """Resolve the active session dir.

    Runtime: from ``--history`` (and stamp the marker so the bridge agrees).
    Bridge: from the ``_active_session`` marker. Fallback: the richest session.
    """
    base = _base()
    name = _session_from_history()
    if name:
        if write_marker:
            try:
                base.mkdir(parents=True, exist_ok=True)
                (base / _MARKER).write_text(name, encoding="utf-8")
            except Exception:
                pass
        return base / name
    try:
        marker = base / _MARKER
        if marker.is_file():
            n = marker.read_text(encoding="utf-8").strip()
            if n and (base / n).is_dir():
                return base / n
    except Exception:
        pass
    return _richest("messages.json") or base


def _next_idx(messages: dict) -> int:
    mx = 0
    for arr in messages.values():
        for m in arr:
            try:
                mx = max(mx, int(m.get("idx", 0)))
            except (TypeError, ValueError):
                pass
    return mx + 1


def add_contact(name: str, known: bool = True) -> bool:
    """Add/upgrade a contact in the active session's contacts.json."""
    name = (name or "").strip()
    if _is_junk_name(name):
        return False
    with _lock:
        path = session_dir() / "contacts.json"
        data = _read_json(path, {}) or {}
        if not isinstance(data, dict):
            data = {}
        contacts = data.setdefault("contacts", {})
        if name in contacts:
            if known and not contacts[name].get("known", True):
                contacts[name]["known"] = True
            else:
                return False
        else:
            contacts[name] = {"added_at": time.time(), "known": bool(known)}
        _write_json(path, data)
        return True


def deliver_sms(name: str, text: str, known: bool = True) -> bool:
    """A character sends the player an SMS (adds the contact if new)."""
    name = (name or "").strip()
    text = (text or "").strip()
    if _is_junk_name(name) or not text:
        return False
    with _lock:
        d = session_dir()
        cpath = d / "contacts.json"
        cdata = _read_json(cpath, {}) or {}
        if not isinstance(cdata, dict):
            cdata = {}
        contacts = cdata.setdefault("contacts", {})
        if name not in contacts:
            contacts[name] = {"added_at": time.time(), "known": bool(known)}
            _write_json(cpath, cdata)
        mpath = d / "messages.json"
        mdata = _read_json(mpath, {}) or {}
        if not isinstance(mdata, dict):
            mdata = {}
        mdata.setdefault(name, []).append(
            {"text": text, "is_user": False, "idx": _next_idx(mdata), "read": False}
        )
        _write_json(mpath, mdata)
        return True


def send_player_sms(name: str, text: str) -> bool:
    """The player sends an SMS from the web phone (is_user=True)."""
    name = (name or "").strip()
    text = (text or "").strip()
    if not name or not text:
        return False
    with _lock:
        mpath = session_dir() / "messages.json"
        mdata = _read_json(mpath, {}) or {}
        if not isinstance(mdata, dict):
            mdata = {}
        mdata.setdefault(name, []).append(
            {"text": text, "is_user": True, "idx": _next_idx(mdata), "read": True}
        )
        _write_json(mpath, mdata)
        return True


# ── Groups (群聊) — byte-compatible with group_store.GroupStore ─────────
#
# groups.json = {"groups": {name: {name, members[], messages[], unread}},
#                "msg_idx": int}
# message     = {sender, text, is_user, is_system, idx}   (player: sender="", is_user=True)

def _groups_path() -> Path:
    return session_dir() / "groups.json"


def _load_groups() -> dict:
    data = _read_json(_groups_path(), {}) or {}
    if not isinstance(data, dict):
        data = {}
    if not isinstance(data.get("groups"), dict):
        data["groups"] = {}
    try:
        data["msg_idx"] = int(data.get("msg_idx", 0))
    except (TypeError, ValueError):
        data["msg_idx"] = 0
    return data


def group_create(name: str, members) -> str:
    """Create a group; returns the final (de-duplicated) name, or '' on failure."""
    name = (name or "").strip()
    if not name:
        return ""
    with _lock:
        data = _load_groups()
        groups = data["groups"]
        base, i = name, 2
        while name in groups:
            name = f"{base}{i}"
            i += 1
        groups[name] = {
            "name": name,
            "members": [m for m in dict.fromkeys(members or []) if m],
            "messages": [],
            "unread": 0,
        }
        _write_json(_groups_path(), data)
    return name


def _group_append(data: dict, name: str, sender: str, text: str,
                  is_user: bool, is_system: bool) -> bool:
    g = data["groups"].get(name)
    if not g:
        return False
    data["msg_idx"] = int(data.get("msg_idx", 0)) + 1
    g.setdefault("messages", []).append({
        "sender": sender,
        "text": text,
        "is_user": bool(is_user),
        "is_system": bool(is_system),
        "idx": data["msg_idx"],
    })
    return True


def group_route_reply(name: str, sender: str, text: str) -> bool:
    """A character posts to a group (LLM tool). Appends + bumps unread."""
    with _lock:
        data = _load_groups()
        g = data["groups"].get(name)
        if not g:
            return False
        _group_append(data, name, sender, text, is_user=False, is_system=False)
        g["unread"] = int(g.get("unread", 0)) + 1
        _write_json(_groups_path(), data)
    return True


def group_send_player(name: str, text: str) -> bool:
    """The player posts to a group from the web phone (is_user=True, sender='')."""
    text = (text or "").strip()
    if not text:
        return False
    with _lock:
        data = _load_groups()
        if name not in data["groups"]:
            return False
        _group_append(data, name, "", text, is_user=True, is_system=False)
        _write_json(_groups_path(), data)
    return True


def group_add_system_message(name: str, text: str) -> bool:
    with _lock:
        data = _load_groups()
        ok = _group_append(data, name, "", text, is_user=False, is_system=True)
        if ok:
            _write_json(_groups_path(), data)
    return ok


def group_names() -> list:
    return list(_load_groups()["groups"].keys())


def group_members(name: str) -> list:
    g = _load_groups()["groups"].get(name)
    return list(g["members"]) if g else []


def group_join(name: str, member: str, operator: str = "") -> bool:
    """Add a character to a group + system notice (LLM tool: add_group_member)."""
    member = (member or "").strip()
    added = False
    with _lock:
        data = _load_groups()
        g = data["groups"].get(name)
        if g and member and member not in g["members"]:
            g["members"].append(member)
            _write_json(_groups_path(), data)
            added = True
    if added:
        op = (operator or "").strip()
        group_add_system_message(name, f"{op}把{member}拉进了群聊" if op else f"{member}加入了群聊")
    return added


def group_kick(name: str, member: str, operator: str = "") -> bool:
    """Remove a character from a group + system notice."""
    member = (member or "").strip()
    removed = False
    with _lock:
        data = _load_groups()
        g = data["groups"].get(name)
        if g and member in g.get("members", []):
            g["members"].remove(member)
            _write_json(_groups_path(), data)
            removed = True
    if removed:
        op = (operator or "").strip()
        group_add_system_message(name, f"{op}把{member}移出了群聊" if op else f"{member}被移出群聊")
    return removed


def group_leave(name: str, member: str) -> bool:
    """A character leaves a group on their own + system notice."""
    member = (member or "").strip()
    left = False
    with _lock:
        data = _load_groups()
        g = data["groups"].get(name)
        if g and member in g.get("members", []):
            g["members"].remove(member)
            _write_json(_groups_path(), data)
            left = True
    if left:
        group_add_system_message(name, f"{member}退出了群聊")
    return left


def group_rename(old: str, new: str, operator: str = "") -> str:
    """Rename a group (re-keys). Returns the final new name, or '' on failure."""
    new = (new or "").strip()
    if not new:
        return ""
    final = ""
    with _lock:
        data = _load_groups()
        groups = data["groups"]
        if old not in groups:
            return ""
        if new == old:
            return old
        base, i = new, 2
        while new in groups:
            new = f"{base}{i}"
            i += 1
        g = groups.pop(old)
        g["name"] = new
        groups[new] = g
        _write_json(_groups_path(), data)
        final = new
    if final:
        op = (operator or "").strip()
        group_add_system_message(final, f"{op}把群名改为「{final}」" if op else f"群名改为「{final}」")
    return final


# ── Moments (朋友圈) — byte-compatible with moments_store.MomentsStore ──
#
# moments.json = {"posts": [...], "post_idx": int, "comment_idx": int}
# post    = {id, author, text, image, image_desc, likes[], comments[], ts, unread, notify}
# comment = {id, author, text, is_user, reply_to}      (player author = "__player__")

_PLAYER = "__player__"
_MAX_POSTS = 200


def _moments_path() -> Path:
    return session_dir() / "moments.json"


def _load_moments() -> dict:
    data = _read_json(_moments_path(), {}) or {}
    if not isinstance(data, dict):
        data = {}
    if not isinstance(data.get("posts"), list):
        data["posts"] = []
    for k in ("post_idx", "comment_idx"):
        try:
            data[k] = int(data.get(k, 0))
        except (TypeError, ValueError):
            data[k] = 0
    return data


def _moment_find(posts: list, post_id: int):
    for p in posts:
        if isinstance(p, dict) and p.get("id") == post_id:
            return p
    return None


def moment_add_post(author: str, text: str, image_desc: str = "", is_user: bool = False) -> int:
    """Append a moments post; returns its id (0 on failure)."""
    author = (author or "").strip()
    with _lock:
        data = _load_moments()
        data["post_idx"] = int(data.get("post_idx", 0)) + 1
        pid = data["post_idx"]
        data["posts"].append({
            "id": pid,
            "author": author,
            "text": text or "",
            "image": None,
            "image_desc": (image_desc or None),
            "likes": [],
            "comments": [],
            "ts": time.time(),
            "unread": not is_user,
            "notify": 0,
        })
        if len(data["posts"]) > _MAX_POSTS:
            data["posts"] = data["posts"][-_MAX_POSTS:]
        _write_json(_moments_path(), data)
        return pid


def moment_add_comment(post_id: int, author: str, text: str,
                       is_user: bool = False, reply_to: str = "") -> int | None:
    """Append a comment (reply_to = the comment author being replied to); returns its id."""
    author = (author or "").strip()
    reply_to = (reply_to or "").strip()
    if reply_to in ("玩家", "我"):
        reply_to = _PLAYER
    with _lock:
        data = _load_moments()
        p = _moment_find(data["posts"], post_id)
        if not p:
            return None
        data["comment_idx"] = int(data.get("comment_idx", 0)) + 1
        cid = data["comment_idx"]
        p.setdefault("comments", []).append({
            "id": cid,
            "author": author,
            "text": text or "",
            "is_user": bool(is_user),
            "reply_to": reply_to,
        })
        if p.get("author") == _PLAYER and not is_user:
            p["notify"] = int(p.get("notify", 0)) + 1
        _write_json(_moments_path(), data)
        return cid


def moment_add_like(post_id: int, liker: str, is_user: bool = False) -> bool:
    """Add a like (idempotent). Returns False if already liked / no such post."""
    liker = (liker or "").strip()
    with _lock:
        data = _load_moments()
        p = _moment_find(data["posts"], post_id)
        if not p or not liker or liker in p.get("likes", []):
            return False
        p.setdefault("likes", []).append(liker)
        if p.get("author") == _PLAYER and not is_user:
            p["notify"] = int(p.get("notify", 0)) + 1
        _write_json(_moments_path(), data)
        return True


def moment_get_posts() -> list:
    """All posts, oldest-first (for prompt injection)."""
    return list(_load_moments()["posts"])


# ── Readers + proactive queue (for the Qt-free proactive monitor) ──────

def contacts_list() -> list:
    """Contact names in the active session's contacts.json."""
    data = _read_json(session_dir() / "contacts.json", {}) or {}
    contacts = data.get("contacts") if isinstance(data, dict) else None
    if not isinstance(contacts, dict):
        return []
    return [n for n in contacts.keys() if n and str(n).strip()]


def messages_for(name: str) -> list:
    """One character's SMS thread (list of {text, is_user, idx, read})."""
    mdata = _read_json(session_dir() / "messages.json", {}) or {}
    arr = mdata.get(name) if isinstance(mdata, dict) else None
    return list(arr) if isinstance(arr, list) else []


def last_message(name: str):
    """The last message dict in a thread, or None."""
    arr = messages_for(name)
    return arr[-1] if arr else None


def log_call(name: str, duration: int, call_type: str = "outgoing") -> bool:
    """Append a call-log entry (byte-compatible with phone_app.log_call).

    call_log.json = [{name, duration, timestamp, type}], newest-first. ``type`` carries
    the voice/video source of truth via a ``_video`` suffix (outgoing/incoming/missed
    [+_video] / missed_dnd); webface reads voice + video from here.
    """
    name = (name or "").strip()
    if not name or _is_junk_name(name):
        return False
    with _lock:
        path = session_dir() / "call_log.json"
        data = _read_json(path, [])
        if not isinstance(data, list):
            data = []
        data.insert(0, {"name": name, "duration": int(duration or 0),
                        "timestamp": time.time(), "type": call_type})
        _write_json(path, data[:200])
    return True


def mark_thread_read(name: str) -> bool:
    """Mark all incoming messages in a thread as read (clears the unread badge)."""
    name = (name or "").strip()
    if not name:
        return False
    with _lock:
        mpath = session_dir() / "messages.json"
        mdata = _read_json(mpath, {}) or {}
        arr = mdata.get(name) if isinstance(mdata, dict) else None
        if not isinstance(arr, list):
            return False
        changed = False
        for m in arr:
            if isinstance(m, dict) and not m.get("is_user") and not m.get("read"):
                m["read"] = True
                changed = True
        if changed:
            _write_json(mpath, mdata)
    return changed


def unknown_names() -> list:
    """Active-session contacts explicitly marked known=false (show as 未知联系人)."""
    data = _read_json(session_dir() / "contacts.json", {}) or {}
    contacts = data.get("contacts") if isinstance(data, dict) else None
    out: list = []
    if isinstance(contacts, dict):
        for name, info in contacts.items():
            if isinstance(info, dict) and info.get("known", True) is False and not _is_junk_name(str(name)):
                out.append(str(name))
    return out


# ── Web-phone avatars (global {name: dataURI}) ─────────────────────────

def _avatars_path() -> Path:
    return _base() / "web_avatars.json"


def get_web_avatars() -> dict:
    data = _read_json(_avatars_path(), {}) or {}
    return data if isinstance(data, dict) else {}


def set_web_avatar(name: str, data_uri: str) -> bool:
    """Save (or clear, if data_uri empty) a character's uploaded avatar. Global,
    persists across saves. Rejects oversized payloads (~700 KB base64 cap)."""
    name = (name or "").strip()
    if not name or _is_junk_name(name):
        return False
    data_uri = data_uri or ""
    if data_uri and (not data_uri.startswith("data:image/") or len(data_uri) > 700_000):
        return False
    with _lock:
        avatars = get_web_avatars()
        if data_uri:
            avatars[name] = data_uri
        else:
            avatars.pop(name, None)
        return _write_json(_avatars_path(), avatars)


def record_pending_proactive(name: str, text: str, cap: int = 20) -> bool:
    """Queue a proactive SMS so the next main-story turn knows the character reached out.

    Matches phone_widget._record_pending_proactive: a capped list of {name, text},
    consumed (and cleared) by the before-chat hook.
    """
    name = (name or "").strip()
    text = (text or "").strip()
    if not name or not text:
        return False
    with _lock:
        path = session_dir() / "pending_proactive.json"
        data = _read_json(path, [])
        if not isinstance(data, list):
            data = []
        data.append({"name": name, "text": text})
        if len(data) > cap:
            data = data[-cap:]
        _write_json(path, data)
    return True
