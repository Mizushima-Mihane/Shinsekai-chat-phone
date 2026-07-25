from __future__ import annotations

import json
from pathlib import Path

import frontend_integration as integration

ROOT = Path(__file__).resolve().parents[1]


class _FakeController:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def present_page(self, page_id: str, **kwargs: object) -> None:
        self.calls.append((page_id, kwargs))


def teardown_function() -> None:
    integration.clear_frontend_ui()


def test_extracts_explicit_voice_and_video_calls() -> None:
    voice = json.dumps(
        {"dialog": [{"character_name": "CALL", "speech": "Alice"}]},
        ensure_ascii=False,
    )
    video = json.dumps(
        {"dialog": [{"character_name": "CALL", "speech": "Alice:视频"}]},
        ensure_ascii=False,
    )

    assert integration.extract_incoming_call(voice, ["Alice"]) == ("Alice", "voice")
    assert integration.extract_incoming_call(video, ["Alice"]) == ("Alice", "video")


def test_ignores_unknown_callers() -> None:
    content = {"dialog": [{"character_name": "CALL", "speech": "Mallory"}]}

    assert integration.extract_incoming_call(content, ["Alice"]) is None


def test_presents_generic_registered_page_payload() -> None:
    controller = _FakeController()
    integration.bind_frontend_ui(controller)

    assert integration.present_incoming_call("Alice", "video") is True
    assert controller.calls == [
        (
            integration.PAGE_ID,
            {
                "payload": {
                    "view": "incoming-call",
                    "caller": "Alice",
                    "callType": "video",
                },
                "presentation_id": integration.INCOMING_CALL_PRESENTATION_ID,
            },
        )
    ]


def test_strips_call_marker_but_keeps_other_dialog() -> None:
    content = (
        "prefix:"
        + json.dumps(
            {
                "dialog": [
                    {"character_name": "CALL", "speech": "Alice"},
                    {"character_name": "NARR", "speech": "The phone rings."},
                ]
            },
            ensure_ascii=False,
        )
    )

    stripped = integration.strip_incoming_call_markers(content)

    assert stripped is not None
    assert stripped.startswith("prefix:")
    payload = json.loads(stripped.removeprefix("prefix:"))
    assert payload["dialog"] == [
        {"character_name": "NARR", "speech": "The phone rings."}
    ]


def test_incoming_call_view_enables_gentle_reduced_motion_safe_shake() -> None:
    script = (ROOT / "frontend" / "dist" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "dist" / "styles.css").read_text(encoding="utf-8")

    assert 'name === "incoming-call"' in script
    assert 'classList.toggle("phone-shell--ringing"' in script
    assert ".phone-shell--ringing" in styles
    assert "animation: gentle-ring 1.8s ease-in-out infinite" in styles
    reduced_motion = styles.split("@media (prefers-reduced-motion: reduce)", 1)[1]
    assert ".phone-shell--ringing" in reduced_motion
    assert "animation: none" in reduced_motion
