"""UI constants — colour palette, fonts, sizes (ported from Scan_blocky).

Colour values are reused; applied as Qt QSS in ``style.py``.
"""

# ---- Colour palette ----
CLR_BG_DARK = "#0d0d1a"
CLR_BG_MAIN = "#1a1a2e"
CLR_SIDEBAR = "#16213e"
CLR_SIDEBAR_ACTIVE = "#0f3460"
CLR_SIDEBAR_HOVER = "#1a4a7a"
CLR_ACCENT = "#4a9eff"
CLR_ACCENT_DARK = "#2979d4"
CLR_SUCCESS = "#2ecc71"
CLR_WARNING = "#f39c12"
CLR_ERROR = "#e74c3c"
CLR_TEXT_PRIMARY = "#e0e0e0"
CLR_TEXT_SECONDARY = "#888888"
CLR_TEXT_MUTED = "#555566"
CLR_BORDER = "#333355"
CLR_ROW_ALT = "#1e1e35"
CLR_ROW_HOVER = "#252540"
CLR_TOTAL_ROW = "#0f3460"
CLR_PANEL = "#1e1e35"

# Cash / card accent colours for the summary rows
CLR_CASH = "#2ecc71"
CLR_CARD = "#9b59b6"

# ---- Fonts ----
FONT_FAMILY = "Segoe UI"
FONT_SIZE_LARGE = 16
FONT_SIZE_MEDIUM = 12
FONT_SIZE_SMALL = 10

# ---- Sizes ----
SIDEBAR_WIDTH = 220
MIN_WINDOW_WIDTH = 1280
MIN_WINDOW_HEIGHT = 720
LOGO_SIZE = 48

# Neutral chip colour for the "Nezaradené" (uncategorized) fallback
CLR_UNCATEGORIZED = "#555566"

# Slovak month names for dropdowns / reports
MONTHS_SK = [
    "Január", "Február", "Marec", "Apríl", "Máj", "Jún",
    "Júl", "August", "September", "Október", "November", "December",
]
