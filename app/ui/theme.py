"""Design tokens, fonts and the global Qt stylesheet for Amue KeyFlow."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase

from app.constants import ACCENTS, RESOURCE_DIR

_DARK = {
    "is_dark": True,
    "bg": "#070813",
    "bg2": "#0A0C1C",
    "bg3": "#0E1124",
    "panel": "#0D1020",
    "panel_alt": "#12162B",
    "white": "#FFFFFF",
    "sidebar_alpha": 12,
    "card_alpha": 16,
    "card_hover_alpha": 28,
    "border_alpha": 28,
    "border_strong_alpha": 56,
    "input_alpha": 20,
    "text": "#EDEFF9",
    "muted": "#8B93B0",
    "faint": "#5C6484",
    "accent_text": "#08090F",
    "success": "#3DDC97",
    "warning": "#F5B544",
    "danger": "#F87171",
    "info": "#60A5FA",
    "shadow_alpha": 150,
    "scroll_alpha": 46,
    "popup": "#121528",
    "popup_border_alpha": 60,
}

_LIGHT = {
    "is_dark": False,
    "bg": "#EEF0FA",
    "bg2": "#E7EAF7",
    "bg3": "#F7F8FE",
    "panel": "#FFFFFF",
    "panel_alt": "#F3F5FD",
    "white": "#0D1024",
    "sidebar_alpha": 26,
    "card_alpha": 255,
    "card_hover_alpha": 255,
    "border_alpha": 34,
    "border_strong_alpha": 64,
    "input_alpha": 22,
    "text": "#171B2E",
    "muted": "#5B6480",
    "faint": "#8B92A9",
    "accent_text": "#FFFFFF",
    "success": "#0E9F6E",
    "warning": "#B27400",
    "danger": "#DC4C4C",
    "info": "#2563EB",
    "shadow_alpha": 46,
    "scroll_alpha": 52,
    "popup": "#FFFFFF",
    "popup_border_alpha": 60,
}

_state: dict = {**_DARK, "accent": ACCENTS["violet"]}


def rgba(hex_color: str, alpha: float | int) -> str:
    """CSS ``rgba(...)`` string from a hex colour and 0-255 alpha."""
    color = QColor(hex_color)
    a = alpha if isinstance(alpha, float) and alpha <= 1 else float(alpha) / 255.0
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {a:.3f})"


def color(hex_color: str, alpha: float | int = 255) -> QColor:
    c = QColor(hex_color)
    a = int(round(alpha * 255)) if isinstance(alpha, float) and alpha <= 1 else int(alpha)
    c.setAlpha(max(0, min(255, a)))
    return c


def palette() -> dict:
    return _state


def accent() -> dict:
    return _state["accent"]


def apply_appearance(theme_name: str, accent_name: str, system_is_dark: bool = True) -> None:
    global _state
    use_dark = theme_name != "light" and (theme_name == "dark" or system_is_dark)
    base = dict(_DARK if use_dark else _LIGHT)
    base["accent"] = ACCENTS.get(accent_name, ACCENTS["violet"])
    base["theme_name"] = theme_name
    _state.clear()
    _state.update(base)


FONT_STACK = '"Inter", "Segoe UI Variable Display", "Segoe UI", "Noto Sans", sans-serif'


def load_fonts() -> str:
    """Register bundled fonts (if any) and return the UI font family."""
    font_dir = RESOURCE_DIR / "fonts"
    loaded: list[str] = []
    if font_dir.exists():
        for path in font_dir.glob("*.ttf"):
            font_id = QFontDatabase.addApplicationFont(str(path))
            if font_id >= 0:
                families = QFontDatabase.applicationFontFamilies(font_id)
                loaded.extend(families)
    for candidate in ("Inter", *loaded, "Segoe UI Variable Display", "Segoe UI"):
        if candidate in QFontDatabase.families():
            return candidate
    return QFont().family()


def base_font(family: str, size: int = 10, weight: QFont.Weight = QFont.Normal) -> QFont:
    font = QFont(family)
    font.setPointSize(size)
    font.setWeight(weight)
    return font


def stylesheet() -> str:
    p = _state
    accent_color = p["accent"]["primary"]
    accent2 = p["accent"]["secondary"]
    text = p["text"]
    muted = p["muted"]
    border = rgba(p["white"], p["border_alpha"])
    border_strong = rgba(p["white"], p["border_strong_alpha"])
    card = rgba(p["white"], p["card_alpha"]) if p["is_dark"] else p["panel"]
    input_bg = rgba(p["white"], p["input_alpha"])
    popup = p["popup"]
    return f"""
* {{
    font-family: {FONT_STACK};
    outline: none;
}}
QWidget {{
    color: {text};
    font-size: 13px;
}}
QMainWindow, QDialog, #WindowRoot {{
    background: {p["bg"]};
}}
#WindowRoot {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {p["bg"]}, stop:0.55 {p["bg2"]}, stop:1 {p["bg3"]});
}}
QToolTip {{
    background: {popup};
    color: {text};
    border: 1px solid {border_strong};
    border-radius: 8px;
    padding: 6px 8px;
}}
QLabel {{
    background: transparent;
}}
QLabel#PageTitle {{
    font-size: 22px;
    font-weight: 700;
    letter-spacing: 0.2px;
}}
QLabel#PageSubtitle, QLabel[muted="true"] {{
    color: {muted};
    font-size: 12px;
}}
QLabel#CardTitle {{
    font-size: 14px;
    font-weight: 600;
}}
QLabel#SectionTitle {{
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.6px;
    color: {muted};
}}
QLabel#StatValue {{
    font-size: 30px;
    font-weight: 700;
}}
QLabel#BrandName {{
    font-size: 15px;
    font-weight: 800;
    letter-spacing: 2.4px;
}}
QLabel#BrandSub {{
    font-size: 9px;
    letter-spacing: 2.6px;
    color: {muted};
}}
QLabel#EmptyTitle {{
    font-size: 16px;
    font-weight: 600;
}}
QLabel#FieldLabel {{
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.6px;
    color: {muted};
}}
QLabel#Hint {{
    color: {muted};
    font-size: 11px;
}}

QPushButton {{
    background: {input_bg};
    color: {text};
    border: 1px solid {border};
    border-radius: 10px;
    padding: 9px 16px;
    font-size: 12.5px;
    font-weight: 600;
}}
QPushButton:hover {{
    background: {rgba(p["white"], p["border_alpha"])};
    border: 1px solid {border_strong};
}}
QPushButton:pressed {{
    background: {rgba(p["white"], 40)};
}}
QPushButton:disabled {{
    color: {p["faint"]};
    background: {rgba(p["white"], 8)};
    border: 1px solid {rgba(p["white"], 16)};
}}
QPushButton[variant="primary"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {accent_color}, stop:1 {accent2});
    color: {p["accent_text"]};
    border: none;
    padding: 10px 18px;
}}
QPushButton[variant="primary"]:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {accent2}, stop:1 {accent_color});
}}
QPushButton[variant="primary"]:pressed {{
    background: {accent_color};
}}
QPushButton[variant="danger"] {{
    color: {p["danger"]};
    background: {rgba(p["danger"], 28)};
    border: 1px solid {rgba(p["danger"], 80)};
}}
QPushButton[variant="danger"]:hover {{
    background: {rgba(p["danger"], 48)};
}}
QPushButton[variant="ghost"] {{
    background: transparent;
    border: 1px solid {border};
    color: {muted};
}}
QPushButton[variant="ghost"]:hover {{
    color: {text};
    border: 1px solid {border_strong};
}}
QPushButton[variant="segment"] {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 9px;
    padding: 7px 14px;
    color: {muted};
    font-size: 12px;
}}
QPushButton[variant="segment"]:hover {{
    color: {text};
    background: {rgba(p["white"], 18)};
}}
QPushButton[variant="segment"]:checked {{
    color: {text};
    background: {rgba(accent_color, 55)};
    border: 1px solid {rgba(accent_color, 130)};
}}
QPushButton[variant="link"] {{
    background: transparent;
    border: none;
    color: {accent_color};
    padding: 4px 6px;
}}
QPushButton[variant="link"]:hover {{
    color: {accent2};
}}
QPushButton[variant="window"] {{
    background: transparent;
    border: none;
    border-radius: 7px;
    padding: 0px;
}}
QPushButton[variant="window"]:hover {{
    background: {rgba(p["white"], 32)};
}}
QPushButton[variant="close"]:hover {{
    background: {rgba(p["danger"], 200)};
}}

QLineEdit, QPlainTextEdit, QTextEdit {{
    background: {input_bg};
    border: 1px solid {border};
    border-radius: 10px;
    padding: 9px 12px;
    selection-background-color: {accent_color};
    selection-color: {p["accent_text"]};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border: 1px solid {accent_color};
}}
QLineEdit:disabled, QPlainTextEdit:disabled {{
    color: {p["faint"]};
}}
QComboBox {{
    background: {input_bg};
    border: 1px solid {border};
    border-radius: 10px;
    padding: 8px 12px;
    min-height: 18px;
}}
QComboBox:hover {{
    border: 1px solid {border_strong};
}}
QComboBox:focus {{
    border: 1px solid {accent_color};
}}
QComboBox::drop-down {{
    border: none;
    width: 26px;
}}
QComboBox::down-arrow {{
    image: none;
    width: 0px;
}}
QComboBox QAbstractItemView {{
    background: {popup};
    color: {text};
    border: 1px solid {rgba(p["white"], p["popup_border_alpha"])};
    border-radius: 10px;
    padding: 6px;
    selection-background-color: {rgba(accent_color, 70)};
    selection-color: {text};
    outline: none;
}}
QComboBox QAbstractItemView::item {{
    padding: 7px 10px;
    border-radius: 6px;
    min-height: 20px;
}}

QSpinBox {{
    background: {input_bg};
    border: 1px solid {border};
    border-radius: 10px;
    padding: 8px 10px;
    min-height: 18px;
}}
QSpinBox:focus {{
    border: 1px solid {accent_color};
}}
QSpinBox::up-button, QSpinBox::down-button {{
    width: 16px;
    border: none;
    background: transparent;
}}
QSpinBox::up-arrow, QSpinBox::down-arrow {{
    image: none;
    width: 0px;
}}

QCheckBox {{
    spacing: 9px;
    color: {text};
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 6px;
    border: 1px solid {border_strong};
    background: {input_bg};
}}
QCheckBox::indicator:hover {{
    border: 1px solid {accent_color};
}}
QCheckBox::indicator:checked {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {accent_color}, stop:1 {accent2});
    border: 1px solid {accent_color};
}}

QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px 0px 2px 0px;
}}
QScrollBar::handle:vertical {{
    background: {rgba(p["white"], p["scroll_alpha"])};
    min-height: 32px;
    border-radius: 4px;
    margin: 2px;
}}
QScrollBar::handle:vertical:hover {{
    background: {rgba(p["white"], p["scroll_alpha"] + 30)};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
    height: 0px;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
}}
QScrollBar::handle:horizontal {{
    background: {rgba(p["white"], p["scroll_alpha"])};
    min-width: 32px;
    border-radius: 4px;
    margin: 2px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
    width: 0px;
}}

QMenu {{
    background: {popup};
    color: {text};
    border: 1px solid {rgba(p["white"], p["popup_border_alpha"])};
    border-radius: 10px;
    padding: 6px;
}}
QMenu::item {{
    padding: 8px 26px 8px 14px;
    border-radius: 7px;
}}
QMenu::item:selected {{
    background: {rgba(accent_color, 70)};
}}
QMenu::separator {{
    height: 1px;
    background: {border};
    margin: 6px 8px;
}}

QTabWidget::pane {{
    border: none;
    background: transparent;
}}
QTabBar::tab {{
    background: transparent;
    color: {muted};
    padding: 8px 14px;
    border-radius: 8px;
}}
QTabBar::tab:selected {{
    color: {text};
    background: {rgba(p["white"], 26)};
}}

QListWidget {{
    background: transparent;
    border: none;
    outline: none;
}}
QListWidget::item {{
    padding: 8px 10px;
    border-radius: 8px;
}}
QListWidget::item:selected {{
    background: {rgba(accent_color, 60)};
    color: {text};
}}
QListWidget::item:hover {{
    background: {rgba(p["white"], 18)};
}}

QFrame#Separator {{
    background: {border};
    max-height: 1px;
    border: none;
}}
QFrame#VSeparator {{
    background: {border};
    max-width: 1px;
    border: none;
}}
#Toast {{
    background: {popup};
    border: 1px solid {rgba(p["white"], 46)};
    border-radius: 12px;
}}
#ErrorBanner {{
    background: {rgba(p["danger"], 26)};
    border: 1px solid {rgba(p["danger"], 70)};
    border-radius: 12px;
}}
#WarnBanner {{
    background: {rgba(p["warning"], 24)};
    border: 1px solid {rgba(p["warning"], 70)};
    border-radius: 12px;
}}
#InfoBanner {{
    background: {rgba(accent_color, 24)};
    border: 1px solid {rgba(accent_color, 70)};
    border-radius: 12px;
}}
#RecordingPanel {{
    background: {rgba(accent_color, 26)};
    border: 1px solid {rgba(accent_color, 120)};
    border-radius: 14px;
}}
#DialogSheet {{
    background: {p["bg2"]};
    border: 1px solid {rgba(p["white"], 40)};
    border-radius: 18px;
}}
QProgressBar {{
    background: {rgba(p["white"], 20)};
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    border-radius: 4px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {accent_color}, stop:1 {accent2});
}}
"""


def key_popup_stylesheet() -> str:
    """Stylesheet for the searchable key picker's completion list.

    ``QCompleter`` shows a top-level ``QListView`` that is not matched by the
    ``QComboBox QAbstractItemView`` rules, so without this it falls back to the
    system palette and looks dark (with a near-invisible selection) even in the
    light theme.
    """
    p = _state
    accent_color = p["accent"]["primary"]
    return f"""
QListView {{
    background: {p["popup"]};
    color: {p["text"]};
    border: 1px solid {rgba(p["white"], p["popup_border_alpha"])};
    border-radius: 10px;
    padding: 6px;
    outline: none;
    selection-background-color: {rgba(accent_color, 90)};
    selection-color: {p["text"]};
}}
QListView::item {{
    padding: 7px 10px;
    border-radius: 6px;
    min-height: 20px;
}}
QListView::item:hover {{
    background: {rgba(p["white"], 22)};
}}
QListView::item:selected {{
    background: {rgba(accent_color, 90)};
    color: {p["text"]};
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: {rgba(p["white"], p["scroll_alpha"])};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
"""
