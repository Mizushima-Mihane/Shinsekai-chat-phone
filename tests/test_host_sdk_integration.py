from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

sdk_types = pytest.importorskip("sdk.types")

if not hasattr(sdk_types, "FrontendChatUIContribution"):
    pytest.skip("host SDK does not provide frontend chat UI contributions", allow_module_level=True)
if not hasattr(sdk_types, "FrontendPageContribution"):
    pytest.skip("host SDK does not provide frontend page contributions", allow_module_level=True)

from sdk.register import PluginCapabilityRegistry
from sdk.frontend_ui import _bind_frontend_ui_dispatcher


ROOT = Path(__file__).resolve().parents[1]


def _load_plugin_module(monkeypatch: pytest.MonkeyPatch):
    plugins_package = types.ModuleType("plugins")
    plugins_package.__path__ = []
    phone_package = types.ModuleType("plugins.shinsekai_chat_phone")
    phone_package.__path__ = [str(ROOT)]
    monkeypatch.setitem(sys.modules, "plugins", plugins_package)
    monkeypatch.setitem(sys.modules, "plugins.shinsekai_chat_phone", phone_package)

    spec = importlib.util.spec_from_file_location(
        "plugins.shinsekai_chat_phone.plugin",
        ROOT / "plugin.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_registers_top_bar_button_and_static_phone_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_plugin_module(monkeypatch)
    plugin = module.ChatPhonePlugin()
    registry = PluginCapabilityRegistry()
    registry.set_settings_ui_plugin_context(plugin.plugin_id, plugin.plugin_version)

    plugin.initialize(registry, ROOT, object())

    pages = registry.frontend_page_contributions
    slots = registry.frontend_chat_ui_contributions
    assert len(pages) == 1
    assert pages[0].page_id == "chat-phone"
    assert Path(pages[0].entry).is_file()
    assert len(slots) == 1
    assert slots[0].slot == "chat-top-toolbar"
    assert slots[0].icon == "smartphone"
    assert slots[0].action == {
        "type": "open-plugin-page",
        "page_id": "chat-phone",
        "mode": "overlay",
    }

    plugin.shutdown()


def test_call_marker_presents_page_and_is_hidden_from_main_dialog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_plugin_module(monkeypatch)
    plugin = module.ChatPhonePlugin()
    registry = PluginCapabilityRegistry()
    registry.set_settings_ui_plugin_context(plugin.plugin_id, plugin.plugin_version)
    events: list[dict[str, object]] = []
    _bind_frontend_ui_dispatcher(events.append)
    try:
        plugin.initialize(registry, ROOT, object())
        message = {
            "content": json.dumps(
                {
                    "dialog": [
                        {"character_name": "CALL", "speech": "Alice:视频"},
                        {"character_name": "NARR", "speech": "The phone lights up."},
                    ]
                },
                ensure_ascii=False,
            )
        }
        context = SimpleNamespace(role="assistant", message=message)

        module._on_message_added(context, {"Alice": ""})

        assert events == [
            {
                "type": "plugin.page.present",
                "mode": "overlay",
                "pageId": "chat-phone",
                "payload": {
                    "view": "incoming-call",
                    "caller": "Alice",
                    "callType": "video",
                },
                "pluginId": "com.shinsekai.chat_phone",
                "presentationId": "chat-phone.incoming-call",
            }
        ]
        assert '"character_name": "CALL"' not in message["content"]
        assert "The phone lights up." in message["content"]
    finally:
        plugin.shutdown()
        _bind_frontend_ui_dispatcher(None)
