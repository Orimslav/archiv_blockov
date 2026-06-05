"""Cross-platform helpers for the UI layer.

Keeps OS-specific behaviour in one place so the app runs on Windows and Linux
alike. ``open_path`` opens a produced file (PDF/XLSX/CSV) with the desktop's
default handler via Qt, which works on Windows, Linux and macOS — unlike
``os.startfile`` which exists on Windows only.
"""

import logging
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

logger = logging.getLogger(__name__)


def open_path(path: Path) -> None:
    """Open ``path`` with the OS default handler (cross-platform)."""
    url = QUrl.fromLocalFile(str(path))
    if not QDesktopServices.openUrl(url):
        logger.warning(f"Súbor sa nepodarilo otvoriť: {path}")


def open_url(url: str) -> None:
    """Open a web ``url`` in the default browser (cross-platform)."""
    if not QDesktopServices.openUrl(QUrl(url)):
        logger.warning(f"Odkaz sa nepodarilo otvoriť: {url}")
