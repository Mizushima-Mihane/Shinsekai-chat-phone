"""WeChat-style contact list — only shows characters that have exchanged contacts."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from plugins.chat_phone.styles import AVATAR_COLORS, TEXT_PRIMARY, TEXT_SECONDARY


class ContactListView(QWidget):
    """Scrollable list of contacts with search bar at top."""

    on_character_selected = Signal(str)   # emitted when user clicks a contact

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ContactListView")

        # search bar
        self._search_bar = QLineEdit()
        self._search_bar.setPlaceholderText("搜索联系人...")
        self._search_bar.setClearButtonEnabled(True)
        self._search_bar.setStyleSheet(
            "QLineEdit { border: 1px solid #D1D1D6; border-radius: 10px;"
            " padding: 6px 12px; font-size: 13px; background: #E5E5EA; }"
            "QLineEdit:focus { background: white; }"
        )

        # list
        self._list = QListWidget()
        self._list.setObjectName("ContactList")
        self._list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setStyleSheet(
            "QListWidget { border: none; background: white; }"
            "QListWidget::item { padding: 0; border: none; }"
        )

        # empty hint
        self._empty_hint = QLabel("还没有联系人\n在聊天中交换联系方式吧~")
        self._empty_hint.setObjectName("EmptyHint")
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_hint.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._search_bar)
        layout.addWidget(self._list)
        layout.addWidget(self._empty_hint)

        # wire
        self._list.itemClicked.connect(self._on_item_clicked)
        self._search_bar.textChanged.connect(self._on_search_changed)
        self._all_names: list[str] = []
        self._unread_map: dict[str, int] = {}
        self._preview_map: dict[str, str] = {}

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def load_contacts(
        self,
        names: list[str],
        unread: dict[str, int] | None = None,
        previews: dict[str, str] | None = None,
    ) -> None:
        """Rebuild the contact list from *names* (already filtered to contacts only)."""
        self._all_names = list(names)
        self._unread_map = dict(unread or {})
        self._preview_map = dict(previews or {})
        self._rebuild_list()
        self._update_empty_state()

    def refresh_unread(
        self,
        unread: dict[str, int],
        previews: dict[str, str] | None = None,
    ) -> None:
        """Update badge dots and previews without full rebuild."""
        self._unread_map = dict(unread)
        if previews is not None:
            self._preview_map = dict(previews)
        for i in range(self._list.count()):
            item = self._list.item(i)
            w = self._list.itemWidget(item)
            if isinstance(w, _ContactRow):
                w.set_unread(self._unread_map.get(w._name, 0))
                w.set_preview(self._preview_map.get(w._name, ""))

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _rebuild_list(self, filter_text: str = "") -> None:
        self._list.clear()
        filt = filter_text.strip().lower()
        for name in self._all_names:
            if filt and filt not in name.lower():
                continue
            row = _ContactRow(name)
            row.set_unread(self._unread_map.get(name, 0))
            row.set_preview(self._preview_map.get(name, ""))
            item = QListWidgetItem()
            item.setSizeHint(row.sizeHint())
            self._list.addItem(item)
            self._list.setItemWidget(item, row)

    def _update_empty_state(self) -> None:
        has_items = self._list.count() > 0
        self._empty_hint.setVisible(not has_items)
        self._list.setVisible(has_items)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        w = self._list.itemWidget(item)
        if isinstance(w, _ContactRow):
            self.on_character_selected.emit(w._name)

    def _on_search_changed(self, text: str) -> None:
        self._rebuild_list(text)
        self._update_empty_state()


class _ContactRow(QWidget):
    """Single row: coloured circle + name + preview + time + unread dot."""

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._name = name
        self.setObjectName("ContactItem")
        self.setFixedHeight(64)

        colour = AVATAR_COLORS[hash(name) % len(AVATAR_COLORS)]

        # avatar circle
        self._avatar = QLabel(name[0] if name else "?")
        self._avatar.setObjectName("AvatarCircle")
        self._avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._avatar.setStyleSheet(
            f"#AvatarCircle {{ background-color: {colour}; }}"
        )

        # name + preview
        self._name_label = QLabel(name)
        self._name_label.setObjectName("ContactName")

        self._preview_label = QLabel("")
        self._preview_label.setObjectName("ContactPreview")

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.addWidget(self._name_label)
        text_col.addWidget(self._preview_label)

        # unread badge dot
        self._badge = QLabel("")
        self._badge.setObjectName("Badge")
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setFixedSize(18, 18)
        self._badge.hide()

        right_col = QVBoxLayout()
        right_col.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        right_col.addWidget(self._badge)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)
        layout.addWidget(self._avatar)
        layout.addLayout(text_col, 1)
        layout.addLayout(right_col)

    def set_unread(self, count: int) -> None:
        if count > 0:
            txt = str(count) if count <= 99 else "99+"
            self._badge.setText(txt)
            self._badge.show()
        else:
            self._badge.hide()

    def set_preview(self, text: str) -> None:
        self._preview_label.setText(text)
