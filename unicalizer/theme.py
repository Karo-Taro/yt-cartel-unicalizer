"""Тёмная тема: палитра и таблица стилей Qt."""

from __future__ import annotations


class C:
    """Палитра. Тёмно-фиолетовая основа, один градиентный акцент."""

    bg = "#0b0d16"
    bg_deep = "#080a11"
    side_top = "#1a1030"
    side_bottom = "#0c0f1c"

    surface = "#141826"
    surface2 = "#1a1f30"
    surface3 = "#222839"
    border = "#272d40"
    border_soft = "#1e2333"
    track = "#2a3145"
    handle = "#10131f"

    text = "#e9ecf6"
    text2 = "#b6bfd4"
    muted = "#79839a"

    accent = "#8b5cf6"
    accent2 = "#38bdf8"
    accent3 = "#22d3ee"
    accent_dim = "#6d40e0"
    success = "#22c55e"
    warning = "#fbbf24"
    danger = "#f87171"


GRADIENT = (f"qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            f"stop:0 {C.accent}, stop:1 {C.accent3})")
GRADIENT_HOVER = (f"qlineargradient(x1:0, y1:0, x2:1, y2:0, "
                  f"stop:0 #9d75ff, stop:1 #4fe3f7)")

QSS = f"""
QWidget {{
    background: transparent;
    color: {C.text};
    font-family: "Segoe UI", "Inter", "SF Pro Display", sans-serif;
    font-size: 13px;
}}

QMainWindow, #root {{ background: {C.bg}; }}

#sidebar {{
    background: qlineargradient(x1:0, y1:0, x2:0.6, y2:1,
                                stop:0 {C.side_top}, stop:1 {C.side_bottom});
    border-right: 1px solid {C.border_soft};
}}

#topbar {{
    background: {C.bg};
    border-bottom: 1px solid {C.border_soft};
}}
#pageTitle {{ font-size: 17px; font-weight: 700; }}

#brandName {{ font-size: 15px; font-weight: 700; }}
#brandSub {{ color: {C.muted}; font-size: 11px; }}

#navItem {{
    background: transparent;
    border: none;
    border-radius: 10px;
    color: {C.text2};
    font-size: 13.5px;
    padding: 10px 12px;
    text-align: left;
}}
#navItem:hover {{ background: rgba(255,255,255,0.05); color: {C.text}; }}
#navItem:checked {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 #6366f1, stop:1 {C.accent});
    color: #ffffff;
    font-weight: 600;
}}
#navCount {{ color: {C.muted}; font-size: 12px; }}

#sideNote {{
    background: rgba(255,255,255,0.04);
    border: 1px solid {C.border_soft};
    border-radius: 10px;
    color: {C.text2};
    font-size: 11.5px;
    padding: 9px 11px;
}}
#sideLink {{ color: {C.muted}; font-size: 12px; }}
#sideLink:hover {{ color: {C.text}; }}

#heroTitle {{ font-size: 24px; font-weight: 700; }}
#heroSub {{ color: {C.muted}; font-size: 13px; }}

#card {{
    background: {C.surface};
    border: 1px solid {C.border};
    border-radius: 14px;
}}
#accordion {{
    background: {C.surface};
    border: 1px solid {C.border};
    border-radius: 12px;
}}
#accordionHead {{
    background: transparent;
    border: none;
    border-radius: 12px;
    padding: 14px 16px;
    text-align: left;
}}
#accordionHead:hover {{ background: rgba(255,255,255,0.035); }}
#accordionTitle {{ font-size: 13.5px; font-weight: 600; color: {C.text}; }}
#accordionSummary {{ color: {C.muted}; font-size: 12px; }}
#chevron {{ color: {C.muted}; font-size: 11px; }}

#sectionTitle {{
    color: {C.muted};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.1px;
}}
#fieldLabel {{ color: {C.text2}; font-size: 13px; }}
#hint {{ color: {C.muted}; font-size: 11.5px; }}
#valueBadge {{
    background: {C.surface3};
    border: 1px solid {C.border};
    border-radius: 7px;
    color: {C.text};
    font-size: 12px;
    font-weight: 600;
    padding: 4px 0px;
}}

QPushButton {{
    background: {C.surface2};
    border: 1px solid {C.border};
    border-radius: 9px;
    color: {C.text};
    padding: 9px 14px;
    font-size: 12.5px;
}}
QPushButton:hover {{ background: {C.surface3}; border-color: {C.accent_dim}; }}
QPushButton:pressed {{ background: {C.surface}; }}
QPushButton:disabled {{ color: {C.muted}; border-color: {C.border_soft}; }}

QPushButton#primary {{
    background: {GRADIENT};
    border: none;
    color: #ffffff;
    font-size: 14.5px;
    font-weight: 700;
    padding: 15px 18px;
    border-radius: 12px;
}}
QPushButton#primary:hover {{ background: {GRADIENT_HOVER}; }}
QPushButton#primary:disabled {{ background: {C.surface2}; color: {C.muted}; }}

QPushButton#danger {{
    background: transparent;
    border: 1px solid {C.danger};
    color: {C.danger};
}}
QPushButton#danger:hover {{ background: rgba(248,113,113,0.12); }}
QPushButton#danger:disabled {{ border-color: {C.border_soft}; color: {C.muted}; }}

QPushButton#ghost {{
    background: transparent;
    border: 1px dashed {C.border};
    color: {C.text2};
}}
QPushButton#ghost:hover {{ border-color: {C.accent}; color: {C.text}; }}

QLineEdit, QSpinBox, QDoubleSpinBox {{
    background: {C.surface2};
    border: 1px solid {C.border};
    border-radius: 9px;
    padding: 9px 12px;
    selection-background-color: {C.accent};
}}
QLineEdit:focus, QSpinBox:focus {{ border-color: {C.accent}; }}
QLineEdit::placeholder {{ color: {C.muted}; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; }}

QComboBox {{
    background: {C.surface2};
    border: 1px solid {C.border};
    border-radius: 9px;
    padding: 9px 12px;
}}
QComboBox:hover {{ border-color: {C.accent_dim}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {C.muted};
    margin-right: 9px;
}}
QComboBox QAbstractItemView {{
    background: {C.surface2};
    border: 1px solid {C.border};
    border-radius: 9px;
    padding: 4px;
    outline: none;
    selection-background-color: {C.accent};
}}

QListWidget {{
    background: {C.surface2};
    border: 1px solid {C.border};
    border-radius: 10px;
    padding: 4px;
    outline: none;
}}
QListWidget::item {{ border-radius: 7px; padding: 7px 9px; color: {C.text2}; }}
QListWidget::item:selected {{ background: {C.accent}; color: #ffffff; }}
QListWidget::item:hover:!selected {{ background: {C.surface3}; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: {C.surface3}; border-radius: 5px; min-height: 34px;
}}
QScrollBar::handle:vertical:hover {{ background: {C.border}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{
    background: {C.surface3}; border-radius: 5px; min-width: 34px;
}}

QPlainTextEdit, QTextBrowser {{
    background: {C.surface2};
    border: 1px solid {C.border};
    border-radius: 10px;
    color: {C.text2};
    padding: 10px;
}}
QPlainTextEdit {{
    font-family: "Cascadia Mono", "Consolas", "Menlo", monospace;
    font-size: 11px;
}}

QTableWidget {{
    background: {C.surface2};
    border: 1px solid {C.border};
    border-radius: 10px;
    gridline-color: {C.border_soft};
    outline: none;
}}
QHeaderView::section {{
    background: {C.surface};
    border: none;
    border-bottom: 1px solid {C.border};
    color: {C.muted};
    padding: 9px;
    font-size: 11px;
    font-weight: 600;
}}
QTableWidget::item {{ padding: 6px; border: none; }}
QTableWidget::item:selected {{ background: {C.surface3}; color: {C.text}; }}

QSplitter::handle {{ background: transparent; }}
QToolTip {{
    background: {C.surface3};
    border: 1px solid {C.border};
    border-radius: 6px;
    color: {C.text};
    padding: 6px 8px;
}}
QMessageBox {{ background: {C.surface}; }}
QMessageBox QLabel {{ color: {C.text}; }}
"""
