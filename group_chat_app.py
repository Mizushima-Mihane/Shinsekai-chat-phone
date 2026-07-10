"""Group chat app — group list, multi-party chat bubbles, create-group view."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from plugins.shinsekai_chat_phone.group_store import GroupStore
from plugins.shinsekai_chat_phone.styles import (
    AVATAR_COLORS, ON_SURFACE, ON_SURFACE_VARIANT, OUTLINE_VARIANT, get_surface,
)


class GroupChatApp(QWidget):
    on_back = Signal()
    _signal_received = Signal(str, str, str)  # (group, sender, text)

    def __init__(self, store: GroupStore, parent=None):
        super().__init__(parent)
        self._store = store
        self._group = ""                 # currently open group name
        self._view = "list"              # "list" | "chat" | "create" | "manage"
        self._submit_cb: object = None
        self._save_cb: object = None
        self._sent_cb: object = None
        self._manage_cb: object = None
        self._contacts: list[str] = []
        self._msg_layout: QVBoxLayout | None = None
        self._scroll: QScrollArea | None = None
        self._signal_received.connect(self._on_received_signal)
        self._setup_ui()
        self._show_list()

    def set_submit_callback(self, cb): self._submit_cb = cb
    def set_save_callback(self, cb): self._save_cb = cb
    def set_sent_callback(self, cb): self._sent_cb = cb
    def set_manage_callback(self, cb): self._manage_cb = cb

    def set_contacts(self, names):
        self._contacts = list(names)

    # ------------------------------------------------------------------
    # incoming (thread-safe via signal)
    # ------------------------------------------------------------------

    def add_received_message(self, group: str, sender: str, text: str):
        self._signal_received.emit(group, sender, text)

    def _on_received_signal(self, group: str, sender: str, text: str):
        self._store.add_message(group, sender, text, is_user=False)
        if self._save_cb is not None:
            self._save_cb()
        if self._view == "chat" and group == self._group and self._msg_layout is not None:
            self._add_bubble(sender, text, False)
            self._scroll_down()

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
        self._msg_layout = None; self._scroll = None
        while self._stack.count():
            w = self._stack.takeAt(0).widget()
            if w: w.deleteLater()

    def _on_back(self):
        if self._view == "manage":
            self._show_chat(self._group)
        elif self._view in ("chat", "create"):
            self._show_list()
        else:
            self.on_back.emit()

    # ------------------------------------------------------------------
    # group list
    # ------------------------------------------------------------------

    def _show_list(self):
        self._view = "list"; self._group = ""
        self._top["title"].setText("群聊")
        self._top["back"].show()
        self._top["action"].setText("＋")
        self._reconnect(self._top["action"], self._show_create)
        self._clear()
        names = self._store.get_group_names()
        if not names:
            hint = QLabel("还没有群聊\n点右上角＋建一个吧~")
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hint.setStyleSheet(f"color: {ON_SURFACE_VARIANT}; font-size: 13px;")
            self._stack.addWidget(hint, 1)
            return
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        c = QWidget(); c.setStyleSheet(f"background: {get_surface()};")
        cl = QVBoxLayout(c); cl.setContentsMargins(0, 0, 0, 0); cl.setSpacing(0)
        for name in names:
            members = self._store.get_members(name)
            row = QWidget(); row.setFixedHeight(64)
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row.mousePressEvent = self._make_open(name)
            rl = QHBoxLayout(row); rl.setContentsMargins(16, 10, 16, 10); rl.setSpacing(12)
            rl.addWidget(self._group_icon(name, 44))
            tv = QVBoxLayout(); tv.setSpacing(2)
            title = QLabel(f"{name}（{len(members)}）")
            title.setStyleSheet(f"color: {ON_SURFACE}; font-size: 14px; font-weight: 500;")
            preview = QLabel(self._store.last_preview(name))
            preview.setStyleSheet(f"color: {ON_SURFACE_VARIANT}; font-size: 12px;")
            preview.setMaximumWidth(180)
            tv.addWidget(title); tv.addWidget(preview); rl.addLayout(tv, 1)
            cl.addWidget(row)
        cl.addStretch(); scroll.setWidget(c); self._stack.addWidget(scroll, 1)

    def _make_open(self, name):
        def handler(event):
            self._show_chat(name)
        return handler

    def refresh_list(self):
        """Re-render the group list if it is the active view.

        Called on the GUI thread after a group is created by the LLM/story, so a
        newly-added group shows up without needing to navigate away and back.
        """
        if self._view == "list":
            self._show_list()

    # ------------------------------------------------------------------
    # public API for phone_widget (membership / rename / removal events)
    # ------------------------------------------------------------------

    def on_group_changed(self, group: str):
        """A membership event happened — re-render if we're viewing that group."""
        if group == self._group and self._view == "chat":
            self._show_chat(group)
        elif group == self._group and self._view == "manage":
            self._show_manage()

    def on_group_renamed(self, old: str, new: str):
        if old == self._group:
            self._group = new
            if self._view == "chat":
                self._show_chat(new)
            elif self._view == "manage":
                self._show_manage()

    def on_group_gone(self, group: str):
        """Group removed from the phone (player left / dissolved) — bail to the list."""
        if group == self._group:
            self._show_list()

    # ------------------------------------------------------------------
    # create group
    # ------------------------------------------------------------------

    def _show_create(self):
        self._view = "create"
        self._top["title"].setText("新建群聊")
        self._top["back"].show(); self._top["action"].setText("")
        self._clear()
        wrap = QWidget(); wrap.setStyleSheet(f"background: {get_surface()};")
        wl = QVBoxLayout(wrap); wl.setContentsMargins(16, 12, 16, 12); wl.setSpacing(10)
        name_inp = QLineEdit(); name_inp.setPlaceholderText("群名称")
        name_inp.setStyleSheet(
            f"QLineEdit {{ background: {OUTLINE_VARIANT}; color: {ON_SURFACE}; border: none;"
            " border-radius: 10px; padding: 8px 12px; font-size: 13px; }"
            "QLineEdit:focus { border: 1px solid #FFB3BA; }")
        wl.addWidget(name_inp)
        wl.addWidget(QLabel("选择成员："))
        member_scroll = QScrollArea(); member_scroll.setWidgetResizable(True)
        mc = QWidget(); mc.setStyleSheet(f"background: {get_surface()};")
        ml = QVBoxLayout(mc); ml.setContentsMargins(0, 0, 0, 0); ml.setSpacing(2)
        checks: list[QCheckBox] = []
        for name in self._contacts:
            cb = QCheckBox(name)
            cb.setStyleSheet(f"QCheckBox {{ color: {ON_SURFACE}; font-size: 13px; padding: 4px; }}")
            checks.append(cb); ml.addWidget(cb)
        ml.addStretch(); member_scroll.setWidget(mc); wl.addWidget(member_scroll, 1)
        create_btn = QPushButton("创建群聊")
        from plugins.shinsekai_chat_phone.styles import get_accent
        create_btn.setStyleSheet(
            f"QPushButton {{ background: {get_accent()}; color: white; border-radius: 12px;"
            " padding: 8px; font-size: 14px; font-weight: 600; border: none; }")
        create_btn.clicked.connect(lambda: self._do_create(name_inp.text(), checks))
        wl.addWidget(create_btn)
        self._stack.addWidget(wrap, 1)

    def _do_create(self, name: str, checks: list[QCheckBox]):
        members = [cb.text() for cb in checks if cb.isChecked()]
        name = (name or "").strip()
        if not name or not members:
            return
        gid = self._store.create_group(name, members)
        if self._save_cb is not None:
            self._save_cb()
        if gid:
            self._show_chat(gid)

    # ------------------------------------------------------------------
    # manage group (rename / add / remove members / leave / dissolve)
    # ------------------------------------------------------------------

    def _show_manage(self):
        if not self._group or not self._store.has_group(self._group):
            self._show_list(); return
        self._view = "manage"
        name = self._group
        members = self._store.get_members(name)
        self._top["title"].setText("群设置")
        self._top["back"].show(); self._top["action"].setText("")
        self._clear()
        from plugins.shinsekai_chat_phone.styles import get_accent
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")
        wrap = QWidget(); wrap.setStyleSheet(f"background: {get_surface()};")
        wl = QVBoxLayout(wrap); wl.setContentsMargins(16, 12, 16, 12); wl.setSpacing(8)

        # -- group name (editable) --
        wl.addWidget(_manage_label("群名称"))
        name_row = QHBoxLayout(); name_row.setSpacing(6)
        name_inp = QLineEdit(name)
        name_inp.setStyleSheet(
            f"QLineEdit {{ background: {OUTLINE_VARIANT}; color: {ON_SURFACE}; border: none;"
            " border-radius: 10px; padding: 7px 12px; font-size: 13px; }"
            "QLineEdit:focus { border: 1px solid #FFB3BA; }")
        save_btn = QPushButton("保存")
        save_btn.setStyleSheet(
            f"QPushButton {{ background: {get_accent()}; color: white; border-radius: 10px;"
            " padding: 7px 14px; font-size: 13px; font-weight: 600; border: none; }")
        save_btn.clicked.connect(lambda: self._do_rename(name_inp.text()))
        name_row.addWidget(name_inp, 1); name_row.addWidget(save_btn)
        wl.addLayout(name_row)

        # -- members --
        wl.addWidget(_manage_label(f"成员（{len(members)}）"))
        for m in members:
            mrow = QHBoxLayout(); mrow.setSpacing(8)
            mrow.addWidget(self._bubble_avatar(m, False, 28))
            nm = QLabel(m); nm.setStyleSheet(f"color: {ON_SURFACE}; font-size: 13px;")
            mrow.addWidget(nm, 1)
            rm = QPushButton("移出")
            rm.setStyleSheet(
                "QPushButton { background: transparent; color: #FF6B6B; border: 1px solid #FF6B6B;"
                " border-radius: 10px; padding: 3px 10px; font-size: 11px; }"
                "QPushButton:pressed { background: #FFECEC; }")
            rm.clicked.connect(lambda _=False, mem=m: self._do_remove_member(mem))
            mrow.addWidget(rm)
            wl.addLayout(mrow)

        # -- add members (contacts not already in the group) --
        addable = [c for c in self._contacts if c not in members]
        if addable:
            wl.addWidget(_manage_label("添加成员"))
            add_checks: list[QCheckBox] = []
            for c in addable:
                cb = QCheckBox(c)
                cb.setStyleSheet(f"QCheckBox {{ color: {ON_SURFACE}; font-size: 13px; padding: 3px; }}")
                add_checks.append(cb); wl.addWidget(cb)
            add_btn = QPushButton("＋ 添加所选")
            add_btn.setStyleSheet(
                f"QPushButton {{ background: {get_accent()}; color: white; border-radius: 10px;"
                " padding: 7px; font-size: 13px; font-weight: 600; border: none; }")
            add_btn.clicked.connect(lambda: self._do_add_members(add_checks))
            wl.addWidget(add_btn)

        wl.addSpacing(10)
        # -- leave / dissolve --
        leave_btn = QPushButton("退出群聊")
        leave_btn.setStyleSheet(
            "QPushButton { background: #FFE8D6; color: #C77D3C; border: none; border-radius: 12px;"
            " padding: 9px; font-size: 13px; font-weight: 600; }"
            "QPushButton:pressed { background: #FFD9BC; }")
        leave_btn.clicked.connect(self._do_leave)
        wl.addWidget(leave_btn)
        dissolve_btn = QPushButton("解散群聊")
        dissolve_btn.setStyleSheet(
            "QPushButton { background: #FF6B6B; color: white; border: none; border-radius: 12px;"
            " padding: 9px; font-size: 13px; font-weight: 600; }"
            "QPushButton:pressed { background: #E04B4B; }")
        dissolve_btn.clicked.connect(self._do_dissolve)
        wl.addWidget(dissolve_btn)
        wl.addStretch()
        scroll.setWidget(wrap); self._stack.addWidget(scroll, 1)

    def _do_rename(self, new: str):
        new = (new or "").strip()
        if not new or not self._group or new == self._group:
            return
        if self._manage_cb is not None:
            self._manage_cb("rename", self._group, new)

    def _do_remove_member(self, member: str):
        if self._manage_cb is not None and self._group:
            self._manage_cb("remove", self._group, member)

    def _do_add_members(self, checks: list[QCheckBox]):
        chosen = [cb.text() for cb in checks if cb.isChecked()]  # collect before any re-render
        if not chosen or not self._group:
            return
        for m in chosen:
            if self._manage_cb is not None:
                self._manage_cb("add", self._group, m)

    def _do_leave(self):
        if self._manage_cb is not None and self._group:
            self._manage_cb("leave", self._group, "")

    def _do_dissolve(self):
        if self._manage_cb is not None and self._group:
            self._manage_cb("dissolve", self._group, "")

    # ------------------------------------------------------------------
    # chat view
    # ------------------------------------------------------------------

    def _show_chat(self, name: str):
        self._view = "chat"; self._group = name
        members = self._store.get_members(name)
        self._top["title"].setText(f"{name}（{len(members)}）")
        self._top["back"].show(); self._top["action"].setText("⋯")
        self._reconnect(self._top["action"], self._show_manage)
        self._clear()
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"QScrollArea {{ background: {get_surface()}; border: none; border-radius: 20px; }}")
        mc = QWidget(); mc.setStyleSheet(f"background: {get_surface()};")
        self._msg_layout = QVBoxLayout(mc)
        self._msg_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._msg_layout.setContentsMargins(4, 6, 4, 6); self._msg_layout.setSpacing(6)
        for m in self._store.get_messages(name):
            if m.get("is_system"):
                self._add_system_bubble(m.get("text", ""))
            else:
                self._add_bubble(m.get("sender", ""), m.get("text", ""), m.get("is_user", False))
        self._msg_layout.addStretch(); scroll.setWidget(mc)
        self._scroll = scroll; QTimer.singleShot(400, self._scroll_down)

        ibar = QWidget()
        ibar.setStyleSheet(f"background: {get_surface()}; border-top: 1px solid {OUTLINE_VARIANT};")
        ibar.setFixedHeight(46)
        il = QHBoxLayout(ibar); il.setContentsMargins(8, 5, 8, 5); il.setSpacing(6)
        inp = QLineEdit(); inp.setPlaceholderText("发消息...")
        inp.setMinimumHeight(34); inp.setFixedHeight(34); inp.setMinimumWidth(160)
        inp.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        inp.setStyleSheet(
            f"QLineEdit {{ background: {OUTLINE_VARIANT}; color: {ON_SURFACE}; border: none;"
            " border-radius: 17px; padding: 6px 12px; font-size: 13px; }"
            "QLineEdit:focus { border: 1px solid #FFB3BA; }")
        inp.returnPressed.connect(lambda: self._send(inp))
        from plugins.shinsekai_chat_phone.styles import get_accent
        send = QPushButton("发送"); send.setMinimumWidth(44); send.setMinimumHeight(34)
        send.setStyleSheet(
            f"QPushButton {{ background: {get_accent()}; color: white; border-radius: 17px;"
            " font-size: 12px; font-weight: bold; border: none; }")
        send.clicked.connect(lambda: self._send(inp))
        il.addWidget(inp, 1); il.addWidget(send)
        self._stack.addWidget(scroll, 1); self._stack.addWidget(ibar)

    def _send(self, inp: QLineEdit):
        text = inp.text().strip()
        if not text or not self._group:
            return
        self._store.add_message(self._group, "", text, is_user=True)
        if self._save_cb is not None:
            self._save_cb()
        inp.clear(); self._add_bubble("", text, True); self._scroll_down()
        members = self._store.get_members(self._group)
        if self._sent_cb is not None:
            self._sent_cb()  # signal a fresh reply batch (reset delivery stagger)
        if self._submit_cb is not None:
            mstr = "、".join(members)
            self._submit_cb(
                f"[群聊] 群「{self._group}」（成员：{mstr}）里，玩家发了一条消息：\"{text}\"。"
                f"请由群里相关角色用 send_group_sms 工具回复（可多个角色、多条，"
                f"角色之间也可以互相接话；不相关的角色可以不回）。不要输出对话。"
            )

    # ------------------------------------------------------------------
    # bubbles
    # ------------------------------------------------------------------

    def _add_bubble(self, sender: str, text: str, is_user: bool):
        if self._msg_layout is None:
            return
        bubble = QLabel(text)
        bf = QFont(); bf.setPixelSize(13); bubble.setFont(bf)
        longest = max((QFontMetrics(bf).horizontalAdvance(ln) for ln in text.split("\n")), default=0)
        if longest + 28 <= 200 and "\n" not in text:
            bubble.setWordWrap(False); bubble.setFixedWidth(longest + 28)
        else:
            bubble.setWordWrap(True); bubble.setFixedWidth(200)
        if is_user:
            bubble.setStyleSheet("background: #B5EAD7; color: #2C5A3A; border-radius: 16px 4px 16px 16px; padding: 6px 10px;")
        else:
            bubble.setStyleSheet("background: #FFFFFF; color: #3C2A2A; border: 1px solid #F0E8E8; border-radius: 4px 16px 16px 16px; padding: 6px 10px;")
        av = self._bubble_avatar(sender, is_user, 30)
        top = Qt.AlignmentFlag.AlignTop
        wrapper = QWidget(); wl = QHBoxLayout(wrapper)
        wl.setContentsMargins(4, 1, 4, 1); wl.setSpacing(6)
        if is_user:
            wl.addStretch(1)
            wl.addWidget(bubble, 0, top)
            wl.addWidget(av, 0, top)
        else:
            # character side: avatar + (name label above bubble)
            col = QVBoxLayout(); col.setSpacing(1); col.setContentsMargins(0, 0, 0, 0)
            nlb = QLabel(sender)
            nlb.setStyleSheet(f"color: {ON_SURFACE_VARIANT}; font-size: 10px;")
            col.addWidget(nlb)
            col.addWidget(bubble)
            wl.addWidget(av, 0, top)
            wl.addLayout(col, 0)
            wl.addStretch(1)
        self._msg_layout.addWidget(wrapper)

    def _add_system_bubble(self, text: str):
        """Centered grey system notice (join / leave / rename / kick)."""
        if self._msg_layout is None:
            return
        lbl = QLabel(text); lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setMaximumWidth(220)
        lbl.setStyleSheet(f"color: {ON_SURFACE_VARIANT}; font-size: 10px; padding: 3px 8px;")
        self._msg_layout.addWidget(lbl, 0, Qt.AlignmentFlag.AlignHCenter)

    def _bubble_avatar(self, sender: str, is_user: bool, size: int = 30):
        from plugins.shinsekai_chat_phone.avatar_manager import get_avatar_for_character
        key = "__player__" if is_user else sender
        pix = get_avatar_for_character(key)
        if pix and not pix.isNull():
            return self._rounded_pixmap_label(pix, size)
        # fallback color chip
        from plugins.shinsekai_chat_phone.styles import get_accent
        av = QLabel("我" if is_user else (sender[0] if sender else "?"))
        av.setFixedSize(size, size); av.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bg = get_accent() if is_user else AVATAR_COLORS[hash(sender) % len(AVATAR_COLORS)]
        av.setStyleSheet(f"background: {bg}; border-radius: {size // 4}px; color: white; font-size: {size // 2}px; font-weight: bold;")
        return av

    def _rounded_pixmap_label(self, pix, size):
        from PySide6.QtGui import QPixmap, QPainter, QBrush
        av = QLabel(); av.setFixedSize(size, size); av.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rounded = QPixmap(size, size); rounded.fill(Qt.GlobalColor.transparent)
        p = QPainter(rounded); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(pix.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)))
        p.setPen(Qt.PenStyle.NoPen); p.drawRoundedRect(0, 0, size, size, size // 4, size // 4); p.end()
        av.setPixmap(rounded)
        return av

    def _scroll_down(self):
        if self._scroll:
            QTimer.singleShot(30, lambda: self._scroll.verticalScrollBar().setValue(
                self._scroll.verticalScrollBar().maximum()))

    @staticmethod
    def _reconnect(btn, slot):
        try:
            btn.clicked.disconnect()
        except Exception:
            pass
        btn.clicked.connect(slot)

    def _group_icon(self, name: str, size: int):
        from plugins.shinsekai_chat_phone.styles import get_accent
        av = QLabel("群"); av.setFixedSize(size, size); av.setAlignment(Qt.AlignmentFlag.AlignCenter)
        av.setStyleSheet(f"background: {get_accent()}; border-radius: {size // 4}px; color: white; font-size: {size // 2}px; font-weight: bold;")
        return av


def _manage_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {ON_SURFACE_VARIANT}; font-size: 11px; font-weight: 600; padding-top: 4px;")
    return lbl


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
