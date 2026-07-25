"""Moments (朋友圈) app — a photo/text feed with likes and comments.

The player can post (text + a locally-picked real image) and like/comment on any
post; characters post / comment / like via LLM tools routed through the phone
widget.  The app is a pure renderer: the store is the single source of truth and
every delivery re-renders the feed wholesale (``refresh_feed``), so there are no
dangling per-card widget references.
"""

from __future__ import annotations

import html
import shutil
import time
import uuid
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
)

from plugins.shinsekai_chat_phone.moments_store import MomentsStore
from plugins.shinsekai_chat_phone.styles import (
    AVATAR_COLORS, ON_SURFACE, ON_SURFACE_VARIANT, OUTLINE_VARIANT, get_surface,
)

_PLAYER = "__player__"


class MomentsApp(QWidget):
    on_back = Signal()

    def __init__(self, store: MomentsStore, images_dir: Path, parent=None):
        super().__init__(parent)
        self._store = store
        self._images_dir = Path(images_dir)
        self._view = "feed"                 # "feed" | "compose"
        self._submit_cb: object = None
        self._sent_cb: object = None
        self._read_cb: object = None
        self._pending_image: str | None = None   # relative path chosen in compose
        self._feed_layout: QVBoxLayout | None = None
        self._scroll: QScrollArea | None = None
        self._setup_ui()
        self._show_feed()

    def set_submit_callback(self, cb): self._submit_cb = cb
    def set_sent_callback(self, cb): self._sent_cb = cb
    def set_read_callback(self, cb): self._read_cb = cb

    # ------------------------------------------------------------------
    # UI scaffolding
    # ------------------------------------------------------------------

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)
        self._top = _top_bar()
        self._top["back"].clicked.connect(self._on_back)
        layout.addWidget(self._top["widget"])
        self._stack = QVBoxLayout()
        self._stack.setContentsMargins(0, 0, 0, 0); self._stack.setSpacing(0)
        layout.addLayout(self._stack, 1)

    def _clear(self):
        self._feed_layout = None; self._scroll = None
        while self._stack.count():
            w = self._stack.takeAt(0).widget()
            if w: w.deleteLater()

    def _on_back(self):
        if self._view == "compose":
            self._show_feed()
        else:
            self.on_back.emit()

    def refresh_feed(self):
        """Re-render the feed if it is the active view (store is the source of truth)."""
        if self._view == "feed":
            self._show_feed()

    # ------------------------------------------------------------------
    # feed
    # ------------------------------------------------------------------

    def _show_feed(self):
        self._view = "feed"
        self._store.mark_feed_read()      # opening the feed clears the badge
        if self._read_cb is not None:
            self._read_cb()
        self._top["title"].setText("朋友圈")
        self._top["back"].show()
        self._top["action"].setText("＋")
        self._reconnect(self._top["action"], self._show_compose)
        self._clear()
        posts = self._store.get_posts()
        if not posts:
            hint = QLabel("还没有朋友圈动态\n点右上角＋发一条吧~")
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hint.setStyleSheet(f"color: {ON_SURFACE_VARIANT}; font-size: 13px;")
            self._stack.addWidget(hint, 1)
            return
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"QScrollArea {{ background: {get_surface()}; border: none; }}")
        c = QWidget(); c.setStyleSheet(f"background: {get_surface()};")
        self._feed_layout = QVBoxLayout(c)
        self._feed_layout.setContentsMargins(8, 8, 8, 8); self._feed_layout.setSpacing(8)
        for post in reversed(posts[-50:]):   # newest first, cap render at 50
            self._feed_layout.addWidget(self._make_card(post))
        self._feed_layout.addStretch()
        scroll.setWidget(c); self._scroll = scroll
        self._stack.addWidget(scroll, 1)

    def _make_card(self, post: dict) -> QWidget:
        author = post.get("author", "")
        is_user = author == _PLAYER
        disp = "我" if is_user else author
        card = QWidget()
        card.setStyleSheet("background: #FFFFFF; border-radius: 14px;")
        cl = QVBoxLayout(card); cl.setContentsMargins(12, 10, 12, 10); cl.setSpacing(6)

        # -- head: avatar + name + relative time --
        head = QHBoxLayout(); head.setSpacing(8)
        head.addWidget(self._avatar(author, 40), 0, Qt.AlignmentFlag.AlignTop)
        nt = QVBoxLayout(); nt.setSpacing(1)
        nlb = QLabel(disp); nlb.setStyleSheet(f"color: {ON_SURFACE}; font-size: 13px; font-weight: 600;")
        tlb = QLabel(self._rel_time(post.get("ts", 0.0)))
        tlb.setStyleSheet(f"color: {ON_SURFACE_VARIANT}; font-size: 10px;")
        nt.addWidget(nlb); nt.addWidget(tlb)
        head.addLayout(nt, 1)
        cl.addLayout(head)

        # -- text --
        text = post.get("text", "")
        if text:
            tl = QLabel(text); tl.setWordWrap(True); tl.setMaximumWidth(232)
            tl.setStyleSheet(f"color: {ON_SURFACE}; font-size: 13px;")
            cl.addWidget(tl)

        # -- image: player's real picture, else character [图:描述] placeholder --
        if post.get("image"):
            cl.addWidget(self._image_label(post["image"]), 0, Qt.AlignmentFlag.AlignLeft)
        elif post.get("image_desc"):
            ph = QLabel(f"[图：{post['image_desc']}]"); ph.setWordWrap(True); ph.setMaximumWidth(232)
            ph.setStyleSheet(
                "color: #9A8F8F; font-size: 12px; font-style: italic;"
                " border: 1px dashed #D8CECE; border-radius: 8px; padding: 10px;")
            cl.addWidget(ph)

        # -- likes --
        likes = post.get("likes", [])
        if likes:
            names = "、".join("我" if x == _PLAYER else x for x in likes)
            lkrow = QWidget(); lkl = QHBoxLayout(lkrow)
            lkl.setContentsMargins(0, 2, 0, 2); lkl.setSpacing(6)
            dot = QLabel(); dot.setFixedSize(6, 6)
            dot.setStyleSheet("background: #E58AA0; border-radius: 3px;")
            lknames = QLabel(names); lknames.setWordWrap(True); lknames.setMaximumWidth(216)
            lknames.setStyleSheet("color: #E58AA0; font-size: 11px;")
            lkl.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop); lkl.addWidget(lknames, 1)
            cl.addWidget(lkrow)

        # -- inline comment input (created early so comment rows can target it) --
        pid = post.get("id", 0)
        cin = QLineEdit(); cin.setPlaceholderText("说点什么...")
        cin.setStyleSheet(
            f"QLineEdit {{ background: {OUTLINE_VARIANT}; color: {ON_SURFACE}; border: none;"
            " border-radius: 12px; padding: 5px 10px; font-size: 12px; }}"
            "QLineEdit:focus { border: 1px solid #FFB3BA; }")
        cin.setVisible(False)
        cin.returnPressed.connect(lambda p=pid, le=cin: self._submit_comment(p, le))

        # -- comments (最近 5 条; 点某条角色评论即可回复它) --
        comments = post.get("comments", [])
        if comments:
            cbox = QWidget(); cbox.setStyleSheet("background: #F5F1F1; border-radius: 8px;")
            cbl = QVBoxLayout(cbox); cbl.setContentsMargins(8, 6, 8, 6); cbl.setSpacing(3)
            if len(comments) > 5:
                more = QLabel(f"共 {len(comments)} 条评论")
                more.setStyleSheet(f"color: {ON_SURFACE_VARIANT}; font-size: 10px;")
                cbl.addWidget(more)
            for cm in comments[-5:]:
                is_u = bool(cm.get("is_user"))
                author = cm.get("author", "")
                who = "我" if is_u else author
                who_c = self._name_color(author, is_u)
                text_esc = html.escape(cm.get("text", ""))
                rt = cm.get("reply_to", "")
                row = QLabel()
                if rt:
                    rt_is_u = rt == _PLAYER
                    rtd = "我" if rt_is_u else rt
                    rt_c = self._name_color(rt, rt_is_u)
                    row.setText(
                        f'<span style="color:{who_c};font-weight:600">{html.escape(who)}</span>'
                        f'<span style="color:{ON_SURFACE_VARIANT}"> 回复 </span>'
                        f'<span style="color:{rt_c};font-weight:600">{html.escape(rtd)}</span>'
                        f'<span style="color:{ON_SURFACE}">：{text_esc}</span>')
                else:
                    row.setText(
                        f'<span style="color:{who_c};font-weight:600">{html.escape(who)}</span>'
                        f'<span style="color:{ON_SURFACE}">：{text_esc}</span>')
                row.setTextFormat(Qt.TextFormat.RichText)
                row.setWordWrap(True); row.setMaximumWidth(216)
                row.setStyleSheet("font-size: 12px;")
                if not is_u:  # tap a character's comment to reply to them
                    row.setCursor(Qt.CursorShape.PointingHandCursor)
                    row.mousePressEvent = (
                        lambda e, le=cin, tgt=author, td=who: self._begin_reply(le, tgt, td))
                cbl.addWidget(row)
            cl.addWidget(cbox)

        # -- action row: like (toggle) + comment (reply to the whole post) --
        liked = _PLAYER in likes
        act = QHBoxLayout(); act.setSpacing(6); act.addStretch(1)
        like_btn = QPushButton("已赞" if liked else "赞")
        like_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        like_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {'#E5638A' if liked else ON_SURFACE_VARIANT};"
            " border: none; font-size: 12px; padding: 2px 8px; }}")
        like_btn.clicked.connect(lambda _=False, p=pid: self._toggle_like(p))
        cmt_btn = QPushButton("评论")
        cmt_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cmt_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {ON_SURFACE_VARIANT};"
            " border: none; font-size: 12px; padding: 2px 8px; }}")
        cmt_btn.clicked.connect(lambda _=False, le=cin: self._begin_reply(le, "", ""))
        act.addWidget(like_btn); act.addWidget(cmt_btn)
        cl.addLayout(act)
        cl.addWidget(cin)
        return card

    # ------------------------------------------------------------------
    # player interactions
    # ------------------------------------------------------------------

    def _toggle_like(self, pid: int):
        # add_like returns False when already liked → treat as un-like (toggle).
        if not self._store.add_like(pid, _PLAYER, is_user=True):
            self._store.remove_like(pid, _PLAYER)
        self.refresh_feed()   # player likes never poke the LLM

    def _begin_reply(self, line: QLineEdit, target: str, target_disp: str):
        """Aim the card's comment input at a specific comment author (or the whole post if target='')."""
        line.setProperty("reply_to", target)
        line.setPlaceholderText(f"回复 {target_disp}：" if target else "说点什么...")
        line.setVisible(True); line.setFocus()

    def _submit_comment(self, pid: int, line: QLineEdit):
        text = (line.text() or "").strip()
        if not text:
            return
        reply_to = line.property("reply_to") or ""
        post = self._store.get_post(pid)
        author = post.get("author", "") if post else ""
        disp = "我" if author == _PLAYER else author
        preview = (post.get("text", "")[:16] if post else "")
        self._store.add_comment(pid, _PLAYER, text, is_user=True, reply_to=reply_to)
        if self._sent_cb is not None:
            self._sent_cb(pid)
        self.refresh_feed()
        if self._submit_cb is not None:
            where = "自己的动态" if author == _PLAYER else f"{disp}的动态"
            if reply_to:
                rd = "我" if reply_to == _PLAYER else reply_to
                self._submit_cb(
                    f"[朋友圈] 玩家在{where} #{pid}「{preview}」下回复了 {rd} 的评论：\"{text}\"。"
                    f"请由 {rd} 或相关角色用 comment_moment 接话回应——编号务必填 #{pid}"
                    f"（就评论到这条动态、别投到别的动态）、reply_to 填被回复者；可选、可互评。不要输出对话。")
            else:
                self._submit_cb(
                    f"[朋友圈] 玩家在{where} #{pid}「{preview}」下评论：\"{text}\"。"
                    f"请由相关角色用 comment_moment 接话回应——编号务必填 #{pid}"
                    f"（就评论到这条动态、别投到别的动态）；可选、可互评，不必强求。不要输出对话。")

    # ------------------------------------------------------------------
    # compose
    # ------------------------------------------------------------------

    def _show_compose(self):
        self._view = "compose"
        self._pending_image = None
        self._top["title"].setText("发朋友圈")
        self._top["back"].show(); self._top["action"].setText("")
        self._reconnect(self._top["action"], lambda: None)
        self._clear()
        from plugins.shinsekai_chat_phone.styles import get_accent
        wrap = QWidget(); wrap.setStyleSheet(f"background: {get_surface()};")
        wl = QVBoxLayout(wrap); wl.setContentsMargins(14, 12, 14, 12); wl.setSpacing(10)
        editor = QTextEdit(); editor.setPlaceholderText("这一刻的想法...")
        editor.setFixedHeight(120)
        editor.setStyleSheet(
            f"QTextEdit {{ background: {OUTLINE_VARIANT}; color: {ON_SURFACE}; border: none;"
            " border-radius: 10px; padding: 8px; font-size: 14px; }}")
        wl.addWidget(editor)
        # image row: pick button + preview
        self._preview_holder = QLabel("未选择图片")
        self._preview_holder.setStyleSheet(f"color: {ON_SURFACE_VARIANT}; font-size: 12px;")
        pick = QPushButton("＋ 选图")
        pick.setStyleSheet(
            f"QPushButton {{ background: {OUTLINE_VARIANT}; color: {ON_SURFACE}; border: none;"
            " border-radius: 10px; padding: 7px 14px; font-size: 13px; }}")
        pick.clicked.connect(self._pick_image)
        prow = QHBoxLayout(); prow.setSpacing(8)
        prow.addWidget(pick); prow.addWidget(self._preview_holder, 1)
        wl.addLayout(prow)
        wl.addStretch()
        publish = QPushButton("发布")
        publish.setStyleSheet(
            f"QPushButton {{ background: {get_accent()}; color: white; border-radius: 12px;"
            " padding: 9px; font-size: 14px; font-weight: 600; border: none; }")
        publish.clicked.connect(lambda: self._publish(editor))
        wl.addWidget(publish)
        self._stack.addWidget(wrap, 1)

    def _pick_image(self):
        # A modal dialog runs a nested event loop; the phone's 500ms _raise_timer
        # would raise the phone over the dialog — pause it while the dialog is open.
        timer = None
        try:
            from plugins.shinsekai_chat_phone.plugin import get_phone_widget
            w = get_phone_widget()
            timer = getattr(w, "_raise_timer", None) if w is not None else None
        except Exception:
            timer = None
        try:
            if timer is not None:
                timer.stop()
            from PySide6.QtWidgets import QFileDialog
            src, _ = QFileDialog.getOpenFileName(
                self, "选择图片", "", "图片 (*.png *.jpg *.jpeg *.webp *.bmp *.gif)")
        finally:
            if timer is not None:
                timer.start()
        if not src:
            return
        try:
            self._pending_image = self._import_image(src)
            self._preview_holder.setText(f"已选：{Path(self._pending_image).name}")
        except Exception:
            self._pending_image = None
            self._preview_holder.setText("图片导入失败")

    def _import_image(self, src: str) -> str:
        """Copy an external image into the per-session images dir; return relative path.

        Split out from the file dialog so it is unit-testable offscreen.
        """
        self._images_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(src).suffix.lower() or ".png"
        dst = self._images_dir / f"{uuid.uuid4().hex[:8]}{suffix}"
        shutil.copy2(src, dst)
        return f"moments_images/{dst.name}"

    def _publish(self, editor: QTextEdit):
        text = (editor.toPlainText() or "").strip()
        if not text and not self._pending_image:
            return
        img = self._pending_image
        new_pid = self._store.add_post(_PLAYER, text, image=img, is_user=True)
        self._pending_image = None
        self._show_feed()
        if self._sent_cb is not None:
            self._sent_cb(new_pid)
        if self._submit_cb is not None:
            tail = "（附图）" if img else ""
            self._submit_cb(
                f"[朋友圈] 玩家发布了一条朋友圈动态 #{new_pid}：\"{text}\"{tail}。"
                f"请由相关角色用 like_moment(#{new_pid}, 角色) / comment_moment(#{new_pid}, 角色, 内容) "
                f"自主互动（可多个角色、角色间也可以互相接话；不感兴趣的可不理）。不要输出对话。")

    # ------------------------------------------------------------------
    # rendering helpers
    # ------------------------------------------------------------------

    def _image_label(self, rel_path: str) -> QLabel:
        from PySide6.QtGui import QPixmap, QPainter, QPainterPath
        p = self._images_dir / Path(rel_path).name
        pix = QPixmap(str(p))
        if pix.isNull():
            ph = QLabel("[图片已失效]")
            ph.setFixedSize(120, 80); ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ph.setStyleSheet(
                f"background: {OUTLINE_VARIANT}; color: {ON_SURFACE_VARIANT};"
                " border-radius: 8px; font-size: 11px;")
            return ph
        scaled = pix.scaled(200, 260, Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
        w, h = scaled.width(), scaled.height()
        rounded = QPixmap(w, h); rounded.fill(Qt.GlobalColor.transparent)
        painter = QPainter(rounded); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath(); path.addRoundedRect(0, 0, w, h, 10, 10)
        painter.setClipPath(path); painter.drawPixmap(0, 0, scaled); painter.end()
        lbl = QLabel(); lbl.setPixmap(rounded); lbl.setFixedSize(w, h)
        return lbl

    def _avatar(self, name: str, size: int) -> QLabel:
        from plugins.shinsekai_chat_phone.avatar_manager import get_avatar_for_character
        is_user = name == _PLAYER
        pix = get_avatar_for_character(name)
        if pix and not pix.isNull():
            return self._rounded_pixmap_label(pix, size)
        from plugins.shinsekai_chat_phone.styles import get_accent
        av = QLabel("我" if is_user else (name[0] if name else "?"))
        av.setFixedSize(size, size); av.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bg = get_accent() if is_user else AVATAR_COLORS[hash(name) % len(AVATAR_COLORS)]
        av.setStyleSheet(f"background: {bg}; border-radius: {size // 4}px; color: white;"
                         f" font-size: {size // 2}px; font-weight: bold;")
        return av

    def _rounded_pixmap_label(self, pix, size):
        from PySide6.QtGui import QPixmap, QPainter, QBrush
        av = QLabel(); av.setFixedSize(size, size); av.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rounded = QPixmap(size, size); rounded.fill(Qt.GlobalColor.transparent)
        p = QPainter(rounded); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(pix.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                     Qt.TransformationMode.SmoothTransformation)))
        p.setPen(Qt.PenStyle.NoPen); p.drawRoundedRect(0, 0, size, size, size // 4, size // 4); p.end()
        av.setPixmap(rounded)
        return av

    @staticmethod
    def _name_color(name: str, is_user: bool) -> str:
        """Per-character name tint (same palette as the avatar chips); player uses the accent."""
        if is_user:
            from plugins.shinsekai_chat_phone.styles import get_accent
            return get_accent()
        return AVATAR_COLORS[hash(name) % len(AVATAR_COLORS)]

    @staticmethod
    def _rel_time(ts: float) -> str:
        d = time.time() - (ts or 0.0)
        if d < 60:
            return "刚刚"
        if d < 3600:
            return f"{int(d // 60)}分钟前"
        if d < 86400:
            return f"{int(d // 3600)}小时前"
        return f"{int(d // 86400)}天前"

    @staticmethod
    def _reconnect(btn, slot):
        try:
            btn.clicked.disconnect()
        except Exception:
            pass
        btn.clicked.connect(slot)


def _top_bar() -> dict:
    w = QWidget(); w.setFixedHeight(48); w.setStyleSheet(f"background: {get_surface()};")
    l = QHBoxLayout(w); l.setContentsMargins(4, 0, 12, 0)
    back = QPushButton("←")
    back.setStyleSheet("QPushButton { background: transparent; color: #FFB3BA; border: none; font-size: 18px; padding: 6px 10px; font-weight: 600; }")
    title = QLabel(""); title.setStyleSheet(f"color: {ON_SURFACE}; font-size: 17px; font-weight: 500;")
    action = QPushButton("")
    action.setStyleSheet("QPushButton { background: transparent; color: #FFB3BA; border: none; font-size: 20px; padding: 6px 10px; font-weight: 600; }")
    l.addWidget(back); l.addWidget(title, 1); l.addWidget(action)
    return {"widget": w, "back": back, "title": title, "action": action}
