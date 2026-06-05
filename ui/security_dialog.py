"""Security dialogs — opt-in password protection management.

``SecurityDialog`` lets the user turn password protection on, change the
password, or turn it off — entirely their choice. ``AdminResetDialog`` is the
recovery path used from the login screen when the password is forgotten.
"""

import logging
from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import auth
from core.database import Database

logger = logging.getLogger(__name__)


def _password_field() -> QLineEdit:
    edit = QLineEdit()
    edit.setEchoMode(QLineEdit.EchoMode.Password)
    edit.setPlaceholderText("heslo…")
    return edit


class SecurityDialog(QDialog):
    """Enable, change or disable the optional app password."""

    def __init__(self, db: Database, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._db = db
        self._enabled = auth.is_protection_enabled(db)
        self.setWindowTitle("Zabezpečenie heslom")
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)

        status = QLabel(
            "Ochrana heslom je <b>zapnutá</b>." if self._enabled
            else "Ochrana heslom je <b>vypnutá</b>. Aplikácia sa spúšťa bez hesla."
        )
        status.setWordWrap(True)
        layout.addWidget(status)

        form = QFormLayout()
        self.current_edit = _password_field()
        self.new_edit = _password_field()
        self.confirm_edit = _password_field()
        if self._enabled:
            form.addRow("Súčasné heslo:", self.current_edit)
        form.addRow("Nové heslo:", self.new_edit)
        form.addRow("Potvrďte heslo:", self.confirm_edit)
        layout.addLayout(form)

        hint = QLabel(f"Heslo musí mať aspoň {auth.MIN_PASSWORD_LENGTH} znaky.")
        hint.setStyleSheet("color:#888888;")
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        primary = QPushButton("Zmeniť heslo" if self._enabled else "Zapnúť ochranu heslom")
        primary.clicked.connect(self._apply)
        buttons.addWidget(primary)
        if self._enabled:
            disable = QPushButton("Vypnúť ochranu")
            disable.clicked.connect(self._disable)
            buttons.addWidget(disable)
        cancel = QPushButton("Zrušiť")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def _check_current(self) -> bool:
        """Verify the current password when protection is already on."""
        if not self._enabled:
            return True
        if not auth.verify_password(
            self.current_edit.text().strip(), auth.get_password_hash(self._db)
        ):
            QMessageBox.warning(self, "Chyba", "Súčasné heslo je nesprávne.")
            return False
        return True

    def _validate_new(self) -> Optional[str]:
        """Return a validated new password, or None on error (already reported)."""
        new = self.new_edit.text().strip()
        confirm = self.confirm_edit.text().strip()
        if len(new) < auth.MIN_PASSWORD_LENGTH:
            QMessageBox.warning(
                self, "Chyba",
                f"Heslo musí mať aspoň {auth.MIN_PASSWORD_LENGTH} znaky.",
            )
            return None
        if new != confirm:
            QMessageBox.warning(self, "Chyba", "Heslá sa nezhodujú.")
            return None
        return new

    def _apply(self) -> None:
        if not self._check_current():
            return
        new = self._validate_new()
        if new is None:
            return
        auth.set_password(self._db, new)
        QMessageBox.information(
            self, "Hotovo",
            "Heslo bolo zmenené." if self._enabled
            else "Ochrana heslom je zapnutá. Heslo sa vyžiada pri ďalšom spustení.",
        )
        self.accept()

    def _disable(self) -> None:
        if not self._check_current():
            return
        reply = QMessageBox.question(
            self, "Vypnúť ochranu",
            "Naozaj vypnúť ochranu heslom? Aplikácia sa bude spúšťať bez hesla.",
        )
        if reply == QMessageBox.StandardButton.Yes:
            auth.clear_password(self._db)
            QMessageBox.information(self, "Hotovo", "Ochrana heslom bola vypnutá.")
            self.accept()


class AdminResetDialog(QDialog):
    """Two-step admin recovery: verify admin password, then set a new one."""

    def __init__(self, db: Database, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._db = db
        self.setWindowTitle("Reset hesla (admin)")
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Zadajte admin heslo a nové heslo aplikácie:"))

        form = QFormLayout()
        self.admin_edit = _password_field()
        self.admin_edit.setPlaceholderText("admin heslo…")
        self.new_edit = _password_field()
        self.confirm_edit = _password_field()
        form.addRow("Admin heslo:", self.admin_edit)
        form.addRow("Nové heslo:", self.new_edit)
        form.addRow("Potvrďte heslo:", self.confirm_edit)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        ok = QPushButton("Uložiť nové heslo")
        ok.clicked.connect(self._apply)
        cancel = QPushButton("Zrušiť")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def _apply(self) -> None:
        if not auth.verify_admin(self.admin_edit.text().strip()):
            QMessageBox.warning(self, "Chyba", "Nesprávne admin heslo.")
            self.admin_edit.clear()
            return
        new = self.new_edit.text().strip()
        confirm = self.confirm_edit.text().strip()
        if len(new) < auth.MIN_PASSWORD_LENGTH:
            QMessageBox.warning(
                self, "Chyba",
                f"Heslo musí mať aspoň {auth.MIN_PASSWORD_LENGTH} znaky.",
            )
            return
        if new != confirm:
            QMessageBox.warning(self, "Chyba", "Heslá sa nezhodujú.")
            return
        auth.set_password(self._db, new)
        logger.info("Heslo resetované administrátorom.")
        self.accept()
