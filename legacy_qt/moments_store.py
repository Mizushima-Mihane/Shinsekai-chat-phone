"""Moments (朋友圈) store — a feed of posts with likes and comments.

Persisted to a per-session JSON file so the feed follows the chat session
(same isolation model as groups / single-SMS / contacts).
"""

from __future__ import annotations

import copy
import json
import threading
import time
from pathlib import Path


class MomentsStore:
    """Thread-safe store of Moments posts.

    Each post is a dict::

        {"id": int, "author": str, "text": str,
         "image": str | None, "image_desc": str | None,
         "likes": list[str], "comments": list[dict],
         "ts": float, "unread": bool, "notify": int}

    ``author`` is the character name; the player is ``"__player__"``.
    ``image`` is a real player-picked picture (relative path under the session
    dir); ``image_desc`` is a character's ``[图:...]`` text placeholder (phase
    one has no real character images — the two fields are the clean seam for the
    later vision / text-to-image phases). Each comment::

        {"id": int, "author": str, "text": str, "is_user": bool}

    ``unread`` flags a fresh post by someone other than the player; ``notify``
    counts likes/comments landing on the *player's own* posts.  The single badge
    number is ``Σ unread + Σ notify``.
    """

    PLAYER = "__player__"
    MAX_POSTS = 200

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._posts: list[dict] = []
        self._post_idx = 0
        self._comment_idx = 0
        self._load()

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        try:
            if self._path.is_file():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._posts = data.get("posts", [])
                    self._post_idx = int(data.get("post_idx", 0))
                    self._comment_idx = int(data.get("comment_idx", 0))
        except Exception:
            self._posts = []
            self._post_idx = 0
            self._comment_idx = 0

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps({"posts": self._posts, "post_idx": self._post_idx,
                            "comment_idx": self._comment_idx},
                           ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception:
            pass

    def _find(self, post_id: int) -> dict | None:
        """Locate a post by id — caller must hold the lock."""
        for p in self._posts:
            if p.get("id") == post_id:
                return p
        return None

    # ------------------------------------------------------------------
    # posts
    # ------------------------------------------------------------------

    def add_post(self, author: str, text: str, *, image: str | None = None,
                 image_desc: str | None = None, is_user: bool = False) -> int:
        """Append a post; returns its stable id."""
        author = (author or "").strip()
        with self._lock:
            self._post_idx += 1
            self._posts.append({
                "id": self._post_idx,
                "author": author,
                "text": text or "",
                "image": image,
                "image_desc": image_desc,
                "likes": [],
                "comments": [],
                "ts": time.time(),
                "unread": not is_user,   # someone else's post starts unread
                "notify": 0,
            })
            if len(self._posts) > self.MAX_POSTS:
                self._posts = self._posts[-self.MAX_POSTS:]
            self._save()
            return self._post_idx

    def get_posts(self) -> list[dict]:
        """Deep copy of all posts (insertion order == oldest first)."""
        with self._lock:
            return copy.deepcopy(self._posts)

    def get_post(self, post_id: int) -> dict | None:
        with self._lock:
            p = self._find(post_id)
            return copy.deepcopy(p) if p else None

    def latest_post_id(self) -> int:
        with self._lock:
            return self._posts[-1]["id"] if self._posts else 0

    # ------------------------------------------------------------------
    # likes / comments
    # ------------------------------------------------------------------

    def add_like(self, post_id: int, liker: str, *, is_user: bool = False) -> bool:
        """Add a like (deduped / idempotent). Returns False if already liked."""
        liker = (liker or "").strip()
        with self._lock:
            p = self._find(post_id)
            if not p or not liker or liker in p["likes"]:
                return False
            p["likes"].append(liker)
            if p["author"] == self.PLAYER and not is_user:
                p["notify"] = int(p.get("notify", 0)) + 1
            self._save()
            return True

    def remove_like(self, post_id: int, liker: str) -> bool:
        """Un-like — player toggle only."""
        with self._lock:
            p = self._find(post_id)
            if p and liker in p["likes"]:
                p["likes"].remove(liker)
                self._save()
                return True
        return False

    def add_comment(self, post_id: int, author: str, text: str, *,
                    is_user: bool = False, reply_to: str = "") -> int | None:
        """Append a comment (``reply_to`` names the comment author being replied to); returns its id."""
        author = (author or "").strip()
        with self._lock:
            p = self._find(post_id)
            if not p:
                return None
            self._comment_idx += 1
            p["comments"].append({
                "id": self._comment_idx,
                "author": author,
                "text": text or "",
                "is_user": is_user,
                "reply_to": (reply_to or "").strip(),
            })
            if p["author"] == self.PLAYER and not is_user:
                p["notify"] = int(p.get("notify", 0)) + 1
            self._save()
            return self._comment_idx

    # ------------------------------------------------------------------
    # unread
    # ------------------------------------------------------------------

    def mark_feed_read(self) -> int:
        """Clear every post's unread flag + notify counter. Returns count changed."""
        changed = 0
        with self._lock:
            for p in self._posts:
                if p.get("unread") or int(p.get("notify", 0)):
                    p["unread"] = False
                    p["notify"] = 0
                    changed += 1
            if changed:
                self._save()
        return changed

    def total_unread(self) -> int:
        with self._lock:
            return (sum(1 for p in self._posts if p.get("unread"))
                    + sum(int(p.get("notify", 0)) for p in self._posts))
