"""Macaron colour palette — light & soft pastel tones."""

from __future__ import annotations

# ── Theme refresh system ───────────────────────────────────────────────
_theme_cbs: list = []
def on_theme_change(cb): _theme_cbs.append(cb)
def notify_theme_change(theme):
    for cb in _theme_cbs:
        try: cb(theme)
        except Exception: pass


# ── Macaron palette ────────────────────────────────────────────────────
def _theme():
    try:
        from plugins.shinsekai_chat_phone.settings_app import get_theme
        return get_theme()
    except Exception:
        return "#FFFAFA"


def _darken(hex_color: str, factor: float = 0.06) -> str:
    """Darken a hex colour by *factor* (0-1)."""
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    r = max(0, int(r * (1 - factor)))
    g = max(0, int(g * (1 - factor)))
    b = max(0, int(b * (1 - factor)))
    return f"#{r:02x}{g:02x}{b:02x}"


def _lighten(hex_color: str, factor: float = 0.08) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    r = min(255, int(r + (255 - r) * factor))
    g = min(255, int(g + (255 - g) * factor))
    b = min(255, int(b + (255 - b) * factor))
    return f"#{r:02x}{g:02x}{b:02x}"


def get_bg() -> str:
    """Main background — theme colour."""
    return _theme()


def get_surface() -> str:
    """Card/surface background — slightly lighter than theme."""
    return _lighten(_theme(), 0.05)


def get_content_bg() -> str:
    """Content area — even lighter."""
    return _lighten(_theme(), 0.10)


def get_accent() -> str:
    """Accent colour — slightly darker theme for buttons/tabs."""
    hex_color = _theme().lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    r = max(0, int(r * 0.85))
    g = max(0, int(g * 0.85))
    b = max(0, int(b * 0.85))
    return f"#{r:02x}{g:02x}{b:02x}"
SURFACE_CONTAINER = "#FFFFFF"
SURFACE_VARIANT = "#F5F0F0"
ON_SURFACE = "#3C2A2A"
ON_SURFACE_VARIANT = "#8A7A7A"
OUTLINE = "#E0D5D5"
OUTLINE_VARIANT = "#F0E8E8"
PRIMARY = "#FFB3BA"       # pastel pink
ON_PRIMARY = "#5C1A1A"
SECONDARY = "#B5EAD7"     # pastel mint
TERTIARY = "#C7CEEA"      # pastel lavender
ERROR = "#FF8A80"

# App accent colours (macaron)
ACCENT_PHONE = "#7AE582"     # light green
ACCENT_MESSAGES = "#B5EAD7"  # mint green
ACCENT_CONTACTS = "#C7CEEA"  # lavender
ACCENT_MEMOS = "#FFDAC1"     # peach
ACCENT_CAMERA = "#E2F0CB"    # light green
ACCENT_BROWSER = "#B5D8EB"   # baby blue

# Avatar palette (slightly more saturated for contrast)
AVATAR_COLORS = [
    "#FF9AA2", "#B5EAD7", "#C7CEEA", "#FFDAC1",
    "#E2F0CB", "#FFB7B2", "#B5D8EB", "#F8B4C8",
    "#B4E7CE", "#C4D7F2", "#FCE1A4", "#D4B8D9",
]

# ── QSS ───────────────────────────────────────────────────────────────

PHONE_QSS = """
/* Phone frame */
#PhoneFrame {
    background-color: #FFFAFA;
    border: 2px solid #E0D5D5;
    border-radius: 28px;
}

/* Badge */
QLabel#Badge {
    background: #FF8A80;
    color: white;
    border-radius: 10px;
    font-size: 10px;
    font-weight: bold;
    min-width: 20px;
    min-height: 20px;
}

QScrollArea {
    background: #FFFAFA;
    border: none;
}
QScrollArea > QWidget > QWidget {
    background: #FFFAFA;
}

/* Hide scrollbars phone-wide for the clean internal look — content still
   scrolls by wheel/drag. Matches the chat views' hidden-scrollbar style and
   covers list pages, settings, call log, memos, contacts, browser, etc. */
QScrollBar:vertical { width: 0px; background: transparent; }
QScrollBar:horizontal { height: 0px; background: transparent; }
QScrollBar::handle,
QScrollBar::add-line, QScrollBar::sub-line,
QScrollBar::add-page, QScrollBar::sub-page {
    width: 0px; height: 0px; background: transparent; border: none;
}
"""


def top_bar_style() -> str:
    return "QWidget { background: #FFFAFA; }"


def title_style() -> str:
    return "color: #3C2A2A; font-size: 18px; font-weight: 500;"


def nav_btn_style() -> str:
    return (
        "QPushButton {"
        "  background: transparent; color: #FFB3BA;"
        "  border: none; border-radius: 20px;"
        "  font-size: 14px; font-weight: 600;"
        "  padding: 6px 12px;"
        "}"
        "QPushButton:hover { background: rgba(255,179,186,0.10); }"
    )


def card_style() -> str:
    return (
        "QWidget {"
        "  background: #FFFFFF;"
        "  border: 1px solid #F0E8E8;"
        "  border-radius: 16px;"
        "}"
    )


def input_style() -> str:
    return (
        "QLineEdit {"
        "  background: #FFFFFF; color: #3C2A2A;"
        "  border: 1px solid #E0D5D5; border-radius: 24px;"
        "  padding: 10px 16px; font-size: 14px;"
        "}"
        "QLineEdit:focus { border-color: #FFB3BA; }"
    )


def fab_style(color: str = "#FFB3BA") -> str:
    return (
        f"QPushButton {{"
        f"  background: {color}; color: white;"
        f"  border: none; border-radius: 16px;"
        f"  font-size: 14px; font-weight: 600;"
        f"  padding: 10px 20px;"
        f"}}"
        f"QPushButton:hover {{ opacity: 0.9; }}"
    )


def chip_style(checked: bool = False) -> str:
    bg = get_accent() if checked else get_surface()
    fg = "white" if checked else "#3C2A2A"
    return (
        f"QPushButton {{"
        f"  background: {bg}; color: {fg};"
        f"  border: none; border-radius: 8px;"
        f"  font-size: 13px; padding: 6px 14px;"
        f"}}"
    )


def bubble_style(is_user: bool) -> str:
    if is_user:
        return (
            "QLabel {"
            "  background: #FFB3BA; color: #5C1A1A;"
            "  border-radius: 16px 4px 16px 16px;"
            "  padding: 10px 14px; font-size: 13px;"
            "}"
        )
    else:
        return (
            "QLabel {"
            "  background: #FFFFFF; color: #3C2A2A;"
            "  border: 1px solid #F0E8E8;"
            "  border-radius: 4px 16px 16px 16px;"
            "  padding: 10px 14px; font-size: 13px;"
            "}"
        )


def bottom_nav_style() -> str:
    return (
        "QWidget {"
        "  background: #FFFFFF;"
        "  border-top: 1px solid #F0E8E8;"
        "}"
    )


def bottom_nav_btn_style(active: bool = False) -> str:
    if active:
        return (
            "QPushButton {"
            "  background: rgba(255,179,186,0.12); color: #FFB3BA;"
            "  border: none; border-radius: 20px;"
            "  font-size: 10px; font-weight: 600;"
            "  padding: 6px 10px;"
            "}"
        )
    return (
        "QPushButton {"
        "  background: transparent; color: #8A7A7A;"
        "  border: none; border-radius: 20px;"
        "  font-size: 10px; font-weight: 400;"
        "  padding: 6px 10px;"
        "}"
    )
