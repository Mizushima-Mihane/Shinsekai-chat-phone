"""WeChat-style chat view: message bubbles + input bar."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from plugins.shinsekai_chat_phone.message_store import MessageStore


class ChatView(QWidget):
    """Conversation view with a specific character."""

    on_back = Signal()
    on_call = Signal(str)  # character_name

    def __init__(
        self,
        message_store: MessageStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = message_store
        self._character: str = ""
        self._submit_cb: object = None  # set by PhoneWidget

        self._setup_ui()

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def set_character(self, name: str) -> None:
        """Switch to conversation with *name*, reloading history."""
        self._character = name
        self._header_name.setText(name)
        self._load_history()

    def set_submit_callback(self, cb: object) -> None:
        """Store the callback used to send user text."""
        self._submit_cb = cb

    def append_sent_message(self, text: str) -> None:
        self._add_bubble(text, is_user=True)
        self._scroll_to_bottom()

    def append_received_message(self, text: str) -> None:
        self._add_bubble(text, is_user=False)
        self._scroll_to_bottom()

    def active_character(self) -> str:
        return self._character

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # header
        header = QWidget()
        header.setObjectName("ChatHeader")
        header.setFixedHeight(44)

        self._back_btn = QPushButton("<")
        self._back_btn.setObjectName("ChatHeaderBtn")
        self._back_btn.setFixedSize(30, 30)
        self._back_btn.clicked.connect(self.on_back.emit)

        self._header_name = QLabel("")
        self._header_name.setObjectName("ChatHeaderName")

        self._call_btn = QPushButton("📞")
        self._call_btn.setObjectName("ChatHeaderBtn")
        self._call_btn.setFixedSize(30, 30)
        self._call_btn.setToolTip("打电话")
        self._call_btn.clicked.connect(self._on_call_clicked)

        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 0, 8, 0)
        header_layout.addWidget(self._back_btn)
        header_layout.addWidget(self._header_name, 1)
        header_layout.addWidget(self._call_btn)

        # scrollable message area
        self._scroll = QScrollArea()
        self._scroll.setObjectName("ChatScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._msg_container = QWidget()
        self._msg_container.setObjectName("MsgContainer")
        self._msg_layout = QVBoxLayout(self._msg_container)
        self._msg_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._msg_layout.setContentsMargins(8, 8, 8, 8)
        self._msg_layout.setSpacing(6)
        self._msg_layout.addStretch()
        self._scroll.setWidget(self._msg_container)

        # input bar
        input_bar = QWidget()
        input_bar.setObjectName("ChatInputBar")

        self._input = QLineEdit()
        self._input.setObjectName("ChatInput")
        self._input.setPlaceholderText("发消息...")
        self._input.returnPressed.connect(self._on_send)

        send_btn = QPushButton("发送")
        send_btn.setObjectName("SendButton")
        send_btn.clicked.connect(self._on_send)

        input_layout = QHBoxLayout(input_bar)
        input_layout.setContentsMargins(8, 6, 8, 6)
        input_layout.setSpacing(8)
        input_layout.addWidget(self._input, 1)
        input_layout.addWidget(send_btn)

        layout.addWidget(header)
        layout.addWidget(self._scroll, 1)
        layout.addWidget(input_bar)

    def _load_history(self) -> None:
        """Clear message area and rebuild from store."""
        # remove all existing bubbles (keep the stretch at end)
        while self._msg_layout.count() > 1:
            item = self._msg_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for msg in self._store.get_messages(self._character):
            self._add_bubble(msg["text"], is_user=msg["is_user"])
        self._scroll_to_bottom()

    def _add_bubble(self, text: str, *, is_user: bool) -> None:
        bubble = _MessageBubble(text, is_user=is_user)
        # insert before the trailing stretch
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, bubble)

    def _on_send(self) -> None:
        text = self._input.text().strip()
        if not text or not self._character:
            return
        self._store.add_message(self._character, text, is_user=True)
        self._input.clear()
        self._add_bubble(text, is_user=True)
        self._scroll_to_bottom()

        # forward to the chat flow
        wrapped = f"[短信 发给{self._character}] {text}"
        if self._submit_cb is not None:
            self._submit_cb(wrapped)  # type: ignore[operator]

    def _on_call_clicked(self) -> None:
        if self._character:
            self.on_call.emit(self._character)

    def _scroll_to_bottom(self) -> None:
        vbar = self._scroll.verticalScrollBar()
        vbar.setValue(vbar.maximum())


class _MessageBubble(QWidget):
    """Single chat bubble — green right-aligned for user, white left-aligned for other."""

    def __init__(
        self,
        text: str,
        *,
        is_user: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)

        label = QLabel(text)
        label.setWordWrap(True)
        label.setMaximumWidth(200)
        label.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Preferred,
        )
        label.setObjectName("BubbleUser" if is_user else "BubbleOther")

        if is_user:
            layout.addStretch()
            layout.addWidget(label)
        else:
            layout.addWidget(label)
            layout.addStretch()
