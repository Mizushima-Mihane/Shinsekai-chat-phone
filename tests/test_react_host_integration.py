from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_plugin_module():
    plugins_package = types.ModuleType("plugins")
    plugins_package.__path__ = []
    phone_package = types.ModuleType("plugins.shinsekai_chat_phone")
    phone_package.__path__ = [str(ROOT)]
    sys.modules["plugins"] = plugins_package
    sys.modules["plugins.shinsekai_chat_phone"] = phone_package

    spec = importlib.util.spec_from_file_location(
        "plugins.shinsekai_chat_phone.plugin",
        ROOT / "plugin.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FakeFrontendUI:
    def __init__(self) -> None:
        self.presented: list[tuple[str, dict[str, object]]] = []
        self.dismissed: list[str] = []

    def present_page(self, page_id: str, **kwargs: object) -> None:
        self.presented.append((page_id, kwargs))

    def dismiss_page(self, presentation_id: str) -> None:
        self.dismissed.append(presentation_id)


def test_incoming_call_uses_generic_author_page_presentation() -> None:
    module = _load_plugin_module()
    frontend_ui = _FakeFrontendUI()
    module.set_frontend_ui(frontend_ui)

    module._emit_call_event(
        {
            "type": "call.incoming",
            "name": "Alice",
            "callType": "video",
        }
    )
    module._emit_call_event({"type": "call.ended"})

    assert frontend_ui.presented == [
        (
            "chat_phone_app",
            {
                "presentation_id": "chat-phone.incoming-call",
                "payload": {
                    "view": "incoming-call",
                    "caller": "Alice",
                    "callType": "video",
                },
            },
        )
    ]
    assert frontend_ui.dismissed == ["chat-phone.incoming-call"]


def test_author_page_handles_generic_payload_and_gentle_vibration() -> None:
    page = (ROOT / "frontend" / "dist" / "index.html").read_text(encoding="utf-8")

    assert "VIEWS.messages" in page
    assert "VIEWS.contacts" in page
    assert "VIEWS.moments" in page
    assert 'd.__shinsekai==="plugin-page"' in page
    assert 'p.view==="incoming-call"' in page
    assert 'classList.toggle("incoming-ringing"' in page
    assert "animation:gentle-ring 1.8s ease-in-out infinite" in page
    assert "@media (prefers-reduced-motion:reduce)" in page
