"""Macaron colour palette — light & soft pastel tones."""

from __future__ import annotations

# ── Macaron palette ────────────────────────────────────────────────────
SURFACE = "#FFFAFA"
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
ACCENT_PHONE = "#34C759"     # green
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
    bg = "#FFB3BA" if checked else "#F5F0F0"
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
