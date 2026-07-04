"""Avatar manager — loads from character sprites, supports overrides."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtGui import QPixmap

_AVATAR_DIR = Path("data/plugins/com.shinsekai.chat_phone/avatars")
_AVATAR_CONFIG = _AVATAR_DIR / "avatar_config.json"


def avatar_config_path() -> Path:
    _AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    return _AVATAR_CONFIG


def load_avatar_overrides() -> dict[str, str]:
    """Return {character_name: avatar_path} from config."""
    p = avatar_config_path()
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_avatar_override(name: str, path: str) -> None:
    overrides = load_avatar_overrides()
    overrides[name] = path
    p = avatar_config_path()
    p.write_text(json.dumps(overrides, ensure_ascii=False, indent=2), encoding="utf-8")


def get_avatar_for_character(name: str) -> QPixmap | None:
    """Get avatar pixmap for a character, or None to use default initial."""
    # Check override first
    overrides = load_avatar_overrides()
    if name in overrides:
        raw = overrides[name].strip().strip('"').strip("'")
        override_path = Path(raw)
        if override_path.is_file():
            return QPixmap(str(override_path))

    # Try first sprite from character config
    try:
        from config.config_manager import ConfigManager
        cm = ConfigManager()
        for ch in cm.config.characters:
            if ch.name == name and ch.sprites:
                first = ch.sprites[0]
                if isinstance(first, dict):
                    path = first.get("path", "")
                else:
                    path = getattr(first, "path", "")
                if path and Path(path).is_file():
                    return QPixmap(path)
    except Exception:
        pass
    return None


def get_all_character_names() -> list[str]:
    """Get all character names from config."""
    try:
        from config.config_manager import ConfigManager
        return [c.name for c in ConfigManager().config.characters]
    except Exception:
        return []
