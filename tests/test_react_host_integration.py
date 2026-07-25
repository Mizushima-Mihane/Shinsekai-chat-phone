from __future__ import annotations

import importlib.util
import logging
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _install_sdk_stubs() -> None:
    sdk = types.ModuleType("sdk")
    sdk.__path__ = []
    sys.modules["sdk"] = sdk

    modules = {
        "sdk.chat_ui_context": {"ChatUIContext": object},
        "sdk.hooks": {"MessageAddedContext": object},
        "sdk.logging": {"get_logger": lambda *args, **kwargs: logging.getLogger(args[0])},
        "sdk.plugin": {"PluginBase": object},
        "sdk.plugin_host_context": {
            "PluginHostContext": object,
            "PluginSettingsUIContext": object,
        },
        "sdk.register": {"PluginCapabilityRegistry": object},
        "sdk.tool_registry": {
            "tool": lambda **kwargs: lambda function: function,
        },
        "sdk.types": {
            name: type(name, (), {})
            for name in (
                "ChatUIContribution",
                "FrontendConfigAction",
                "FrontendConfigContribution",
                "FrontendPageContribution",
                "ToolsTabContribution",
            )
        },
    }
    for module_name, attributes in modules.items():
        module = types.ModuleType(module_name)
        for name, value in attributes.items():
            setattr(module, name, value)
        sys.modules[module_name] = module


def _load_plugin_module():
    _install_sdk_stubs()
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


def _load_phone_module(name: str):
    _install_sdk_stubs()
    plugins_package = types.ModuleType("plugins")
    plugins_package.__path__ = []
    phone_package = types.ModuleType("plugins.shinsekai_chat_phone")
    phone_package.__path__ = [str(ROOT)]
    sys.modules["plugins"] = plugins_package
    sys.modules["plugins.shinsekai_chat_phone"] = phone_package

    module_name = f"plugins.shinsekai_chat_phone.{name}"
    spec = importlib.util.spec_from_file_location(module_name, ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
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


def test_runtime_turn_uses_the_host_user_input_trigger() -> None:
    webface = _load_phone_module("webface")
    sent: list[str] = []
    webface.bind_user_input_trigger(sent.append)

    assert webface._trigger_runtime_turn("[短信] 请角色回复") is True
    assert sent == ["[短信] 请角色回复"]


def test_profile_rpc_writes_the_signature_key_used_by_python(monkeypatch) -> None:
    webface = _load_phone_module("webface")
    writes: list[dict[str, object]] = []
    monkeypatch.setattr(webface, "_write_prefs", writes.append)

    assert webface.rpc(
        {
            "cmd": "set_profile",
            "args": {"name": "Player", "signature": "hello"},
        }
    ) == {"ok": True}
    assert writes == [
        {
            "player_name": "Player",
            "player_signature": "hello",
        }
    ]


def test_proactive_call_uses_the_generic_page_callback() -> None:
    proactive_core = _load_phone_module("proactive_core")
    events: list[dict[str, object]] = []
    core = proactive_core.ProactiveCore(on_incoming_call=events.append)

    assert core._emit_call("Alice", video=True) is True
    assert events == [
        {
            "type": "call.incoming",
            "name": "Alice",
            "callType": "video",
            "pluginId": "com.shinsekai.chat_phone",
            "pageId": "chat_phone_app",
        }
    ]
