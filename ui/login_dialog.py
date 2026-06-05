"""LoginDialog — startup password gate (only shown when protection is on).

Also hosts the admin-reset flow so a user who forgets their password can set a
new one with the admin password. Built with PySide6 to match the rest of the
app; the auth logic lives in ``core.auth``.
"""

import logging
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import auth
from core.database import Database
from ui import constants as c

logger = logging.getLogger(__name__)


class LoginDialog(QDialog):
    """Modal login dialog; ``exec()`` returns Accepted only on success."""

    def __init__(self, db: Database, assets_dir: Path,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._db = db
        self._assets_dir = assets_dir
        self._attempts = 0
        self._locked_until: Optional[float] = None

        self.setWindowTitle("Archív bločkov – Prihlásenie")
        self.setModal(True)
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(8)

        logo = QLabel()
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_path = assets_dir / "logo.png"
        if logo_path.exists():
            logo.setPixmap(QPixmap(str(logo_path)).scaledToHeight(
                72, Qt.TransformationMode.SmoothTransformation
            ))
        layout.addWidget(logo)

        title = QLabel("Archív bločkov")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"font-size:{c.FONT_SIZE_LARGE}pt; font-weight:bold; "
            f"color:{c.CLR_TEXT_PRIMARY};"
        )
        layout.addWidget(title)

        prompt = QLabel("Zadajte heslo:")
        prompt.setStyleSheet(f"color:{c.CLR_TEXT_SECONDARY};")
        layout.addSpacing(8)
        layout.addWidget(prompt)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("heslo…")
        self.password_edit.returnPressed.connect(self._submit)
        layout.addWidget(self.password_edit)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet(f"color:{c.CLR_ERROR};")
        layout.addWidget(self.error_label)

        btn_login = QPushButton("Prihlásiť sa")
        btn_login.clicked.connect(self._submit)
        layout.addWidget(btn_login)

        btn_reset = QPushButton("Zabudol som heslo (admin reset)")
        btn_reset.setFlat(True)
        btn_reset.setStyleSheet(
            f"color:{c.CLR_TEXT_MUTED}; border:none; text-align:left;"
        )
        btn_reset.clicked.connect(self._open_admin_reset)
        layout.addWidget(btn_reset)

        QTimer.singleShot(100, self.password_edit.setFocus)

    def _submit(self) -> None:
        if self._locked_until and time.time() < self._locked_until:
            remaining = int(self._locked_until - time.time())
            self.error_label.setText(f"Zablokované. Skúste o {remaining} s.")
            return
        password = self.password_edit.text().strip()
        if not password:
            self.error_label.setText("Zadajte heslo.")
            return
        if auth.verify_password(password, auth.get_password_hash(self._db)):
            logger.info("Prihlásenie úspešné.")
            self.accept()
            return
        self._attempts += 1
        self.password_edit.clear()
        if self._attempts >= auth.MAX_ATTEMPTS:
            self._locked_until = time.time() + auth.LOCKOUT_SECONDS
            self._tick_lockout()
        else:
            remaining = auth.MAX_ATTEMPTS - self._attempts
            self.error_label.setText(
                f"Nesprávne heslo. Zostáva pokusov: {remaining}"
            )

    def _tick_lockout(self) -> None:
        if self._locked_until and time.time() < self._locked_until:
            remaining = int(self._locked_until - time.time())
            self.error_label.setText(f"Príliš veľa pokusov. Skúste o {remaining} s.")
            QTimer.singleShot(1000, self._tick_lockout)
        else:
            self._locked_until = None
            self._attempts = 0
            self.error_label.setText("")

    def _open_admin_reset(self) -> None:
        from ui.security_dialog import AdminResetDialog

        if AdminResetDialog(self._db, self).exec() == QDialog.DialogCode.Accepted:
            self.error_label.setStyleSheet(f"color:{c.CLR_SUCCESS};")
            self.error_label.setText("Heslo zmenené. Prihláste sa novým heslom.")
            self.password_edit.setFocus()
