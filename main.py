"""Entry point for the Archiv_blockov application."""

import logging
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

# Distinguish frozen (PyInstaller) vs script mode for data/log paths.
if getattr(sys, "frozen", False):
    _ROOT = Path(sys.executable).parent
    _SRC_ROOT = Path(sys._MEIPASS)  # type: ignore[attr-defined]
else:
    _ROOT = Path(__file__).parent
    _SRC_ROOT = _ROOT

if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

_LOG_FILE = _ROOT / "archiv_blockov.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(_LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Initialise the DB and launch the main window."""
    from core.database import Database
    from ui.main_window import MainWindow
    from ui.style import build_qss

    db_path = _ROOT / "data" / "archiv_blockov.db"
    db = Database(db_path)
    try:
        db.connect()
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Kritická chyba pri otváraní databázy: {exc}", exc_info=True)
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setStyleSheet(build_qss())

    assets_dir = _SRC_ROOT / "assets"
    icon_path = assets_dir / "logo.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # Optional password gate — only shown if the user enabled protection.
    from core import auth
    if auth.is_protection_enabled(db):
        from PySide6.QtWidgets import QDialog
        from ui.login_dialog import LoginDialog

        if LoginDialog(db, assets_dir).exec() != QDialog.DialogCode.Accepted:
            logger.info("Prihlásenie zrušené — aplikácia sa ukončuje.")
            db.disconnect()
            sys.exit(0)

    window = MainWindow(db, assets_dir)
    window.scanner.install(app)
    window.show()

    exit_code = app.exec()
    db.disconnect()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
