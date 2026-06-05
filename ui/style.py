"""Builds the application-wide QSS stylesheet from the colour palette."""

from ui import constants as c


def build_qss() -> str:
    """Return the full QSS string for the dark theme."""
    return f"""
    QWidget {{
        background-color: {c.CLR_BG_MAIN};
        color: {c.CLR_TEXT_PRIMARY};
        font-family: "{c.FONT_FAMILY}";
        font-size: {c.FONT_SIZE_MEDIUM}pt;
    }}
    QMainWindow, QDialog {{
        background-color: {c.CLR_BG_MAIN};
    }}

    /* ---- Sidebar ---- */
    #Sidebar {{
        background-color: {c.CLR_SIDEBAR};
        border-right: 1px solid {c.CLR_BORDER};
    }}
    #SidebarTitle {{
        font-size: {c.FONT_SIZE_LARGE}pt;
        font-weight: bold;
        color: {c.CLR_ACCENT};
        padding: 8px 4px;
    }}

    /* ---- Header bar ---- */
    #HeaderBar {{
        background-color: {c.CLR_BG_DARK};
        border-bottom: 1px solid {c.CLR_BORDER};
    }}
    #AppTitle {{
        font-size: {c.FONT_SIZE_LARGE}pt;
        font-weight: bold;
        color: {c.CLR_TEXT_PRIMARY};
    }}
    #ScannerStatus {{
        color: {c.CLR_SUCCESS};
        font-weight: bold;
    }}
    #LastReceipt {{
        color: {c.CLR_TEXT_SECONDARY};
        padding: 6px;
    }}

    /* ---- Buttons ---- */
    QPushButton {{
        background-color: {c.CLR_SIDEBAR_ACTIVE};
        color: {c.CLR_TEXT_PRIMARY};
        border: 1px solid {c.CLR_BORDER};
        border-radius: 4px;
        padding: 6px 12px;
    }}
    QPushButton:hover {{
        background-color: {c.CLR_SIDEBAR_HOVER};
    }}
    QPushButton:pressed {{
        background-color: {c.CLR_ACCENT_DARK};
    }}
    QPushButton:disabled {{
        background-color: {c.CLR_PANEL};
        color: {c.CLR_TEXT_MUTED};
    }}
    QPushButton#Primary {{
        background-color: {c.CLR_ACCENT};
        color: white;
        font-weight: bold;
        border: none;
    }}
    QPushButton#Primary:hover {{
        background-color: {c.CLR_ACCENT_DARK};
    }}
    QPushButton#Danger {{
        background-color: {c.CLR_ERROR};
        color: white;
        border: none;
    }}
    QPushButton#KofiButton {{
        background-color: transparent;
        border: none;
        border-radius: 6px;
        padding: 4px;
    }}
    QPushButton#KofiButton:hover {{
        background-color: #1e3a50;
    }}
    QPushButton#KofiButton:pressed {{
        background-color: #16293a;
    }}

    /* ---- Inputs ---- */
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QPlainTextEdit, QTextEdit {{
        background-color: {c.CLR_BG_DARK};
        color: {c.CLR_TEXT_PRIMARY};
        border: 1px solid {c.CLR_BORDER};
        border-radius: 4px;
        padding: 5px;
        selection-background-color: {c.CLR_ACCENT};
    }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QComboBox QAbstractItemView {{
        background-color: {c.CLR_BG_DARK};
        color: {c.CLR_TEXT_PRIMARY};
        selection-background-color: {c.CLR_ACCENT};
        border: 1px solid {c.CLR_BORDER};
    }}

    /* ---- Lists ---- */
    QListWidget {{
        background-color: {c.CLR_SIDEBAR};
        border: none;
        outline: 0;
    }}
    QListWidget::item {{
        padding: 8px 6px;
        border-radius: 4px;
    }}
    QListWidget::item:selected {{
        background-color: {c.CLR_SIDEBAR_ACTIVE};
        color: {c.CLR_ACCENT};
    }}
    QListWidget::item:hover {{
        background-color: {c.CLR_SIDEBAR_HOVER};
    }}

    /* ---- Tables ---- */
    QTableView {{
        background-color: {c.CLR_BG_MAIN};
        alternate-background-color: {c.CLR_ROW_ALT};
        gridline-color: {c.CLR_BORDER};
        selection-background-color: {c.CLR_SIDEBAR_ACTIVE};
        selection-color: {c.CLR_TEXT_PRIMARY};
        border: 1px solid {c.CLR_BORDER};
    }}
    QHeaderView::section {{
        background-color: {c.CLR_BG_DARK};
        color: {c.CLR_TEXT_PRIMARY};
        padding: 6px;
        border: none;
        border-right: 1px solid {c.CLR_BORDER};
        border-bottom: 1px solid {c.CLR_BORDER};
        font-weight: bold;
    }}
    QTableView::item {{ padding: 4px; }}

    /* ---- Tabs ---- */
    QTabWidget::pane {{
        border: 1px solid {c.CLR_BORDER};
        background-color: {c.CLR_BG_MAIN};
    }}
    QTabBar::tab {{
        background-color: {c.CLR_SIDEBAR};
        color: {c.CLR_TEXT_SECONDARY};
        padding: 8px 18px;
        border: 1px solid {c.CLR_BORDER};
        border-bottom: none;
        border-top-left-radius: 4px;
        border-top-right-radius: 4px;
    }}
    QTabBar::tab:selected {{
        background-color: {c.CLR_SIDEBAR_ACTIVE};
        color: {c.CLR_ACCENT};
        font-weight: bold;
    }}

    /* ---- Misc ---- */
    QLabel#SectionTitle {{
        font-size: {c.FONT_SIZE_LARGE}pt;
        font-weight: bold;
        color: {c.CLR_ACCENT};
    }}
    QScrollBar:vertical {{
        background: {c.CLR_BG_DARK};
        width: 12px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {c.CLR_BORDER};
        border-radius: 6px;
        min-height: 24px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QMenu {{
        background-color: {c.CLR_BG_DARK};
        border: 1px solid {c.CLR_BORDER};
    }}
    QMenu::item:selected {{
        background-color: {c.CLR_SIDEBAR_ACTIVE};
    }}
    QSplitter::handle {{ background-color: {c.CLR_BORDER}; }}
    """
