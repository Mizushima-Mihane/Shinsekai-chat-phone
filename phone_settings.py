"""Qt-free settings and per-save phone state for the React phone runtime."""

from __future__ import annotations

import json
from pathlib import Path

_CONFIG = Path("data/plugins/com.shinsekai.chat_phone/phone_settings.json")
_DEFAULT_SESSION = Path("data/plugins/com.shinsekai.chat_phone/_default")
_YANDERE_KEYWORDS = ["病娇", "yandere", "监禁", "偏执", "占有欲极强", "占有欲很强", "极端占有"]


def _session_file() -> Path:
    from plugins.shinsekai_chat_phone import phone_core

    return phone_core.session_dir() / "phone_session.json"


def _legacy_session_file() -> Path:
    return _DEFAULT_SESSION / "phone_session.json"


def _empty_session() -> dict:
    return {"dnd": False, "hacked_characters": [], "yandere_tampering": {}}


def _load_session() -> dict:
    for path in (_session_file(), _legacy_session_file()):
        try:
            if path.is_file():
                value = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(value, dict):
                    return value
        except Exception:
            continue
    return _empty_session()


def _save_session(data: dict) -> None:
    path = _session_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_settings() -> dict:
    try:
        if _CONFIG.is_file():
            value = json.loads(_CONFIG.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                return value
    except Exception:
        pass
    return {"theme": "#FFFAFA"}


def save_settings(data: dict) -> None:
    _CONFIG.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_theme() -> str:
    return str(load_settings().get("theme", "#FFFAFA") or "#FFFAFA")


def get_player_name() -> str:
    return str(load_settings().get("player_name", "") or "").strip()


def get_player_signature() -> str:
    settings = load_settings()
    return str(
        settings.get("player_signature", settings.get("signature", "")) or ""
    ).strip()


def is_dnd() -> bool:
    return bool(_load_session().get("dnd", False))


def get_hacked_characters() -> list[str]:
    return [str(name) for name in _load_session().get("hacked_characters", [])]


def add_hacked_character(name: str) -> bool:
    session = _load_session()
    hacked = session.setdefault("hacked_characters", [])
    if name in hacked:
        return False
    hacked.append(name)
    _save_session(session)
    return True


def is_yandere() -> bool:
    return bool(load_settings().get("yandere", False))


def _get_character_setting(name: str) -> str:
    try:
        from config.config_manager import ConfigManager

        for character in ConfigManager().config.characters:
            if character.name == name:
                return str(character.character_setting or "").lower()
    except Exception:
        pass
    return ""


def is_character_yandere(name: str) -> bool:
    return is_yandere() and any(keyword in _get_character_setting(name) for keyword in _YANDERE_KEYWORDS)


def get_yandere_characters() -> list[str]:
    if not is_yandere():
        return []
    try:
        from config.config_manager import ConfigManager

        return [
            character.name
            for character in ConfigManager().config.characters
            if is_character_yandere(character.name)
        ]
    except Exception:
        return []


def record_yandere_tampering(name: str) -> bool:
    session = _load_session()
    tampering = session.setdefault("yandere_tampering", {})
    if tampering.get(name):
        return False
    tampering[name] = True
    _save_session(session)
    return True


def is_yandere_tampering_active(name: str) -> bool:
    return is_character_yandere(name) and bool(_load_session().get("yandere_tampering", {}).get(name, False))
