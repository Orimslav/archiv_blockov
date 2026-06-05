"""AliasManagerDialog — CRUD item aliases used to group report variants.

An alias maps a display name (e.g. „Chlieb") to one or more LIKE patterns
matched against ``receipt_items.name``. The item search can then select an
alias to sum all matching variants („Chlieb cel.", „CHLIEB 500g", …) together.
"""

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.database import Database

_ALIAS_ID_ROLE = int(Qt.ItemDataRole.UserRole)


class AliasManagerDialog(QDialog):
    """Manage (add/delete) item aliases for the active profile."""

    def __init__(self, db: Database, profile_id: int,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._db = db
        self._profile_id = profile_id
        self.setWindowTitle("Aliasy položiek")
        self.setMinimumSize(460, 460)

        intro = QLabel(
            "Alias zlúči rôzne názvy tej istej položky do jedného reportu.\n"
            "Vzor sa porovnáva s názvom položky (necitlivé na diakritiku a "
            "veľkosť písmen). Znak % zastupuje ľubovoľný text; bez neho sa "
            "vzor hľadá kdekoľvek v názve."
        )
        intro.setWordWrap(True)

        self.list = QListWidget()

        # Add form: display name + pattern.
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Zobrazený názov (napr. Chlieb)")
        self.pattern_edit = QLineEdit()
        self.pattern_edit.setPlaceholderText("Vzor (napr. chlieb)")
        self.pattern_edit.returnPressed.connect(self._add)
        btn_add = QPushButton("Pridať")
        btn_add.clicked.connect(self._add)

        form = QHBoxLayout()
        form.addWidget(self.name_edit, 1)
        form.addWidget(self.pattern_edit, 1)
        form.addWidget(btn_add)

        btn_delete = QPushButton("Vymazať vybraný")
        btn_delete.clicked.connect(self._delete)
        btn_close = QPushButton("Zavrieť")
        btn_close.clicked.connect(self.accept)
        btn_row = QHBoxLayout()
        btn_row.addWidget(btn_delete)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_close)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.list, 1)
        layout.addLayout(form)
        layout.addLayout(btn_row)

        self._reload()

    def _reload(self) -> None:
        self.list.clear()
        for alias in self._db.get_aliases(self._profile_id):
            item = QListWidgetItem(f"{alias.display_name}  ←  {alias.pattern}")
            item.setData(_ALIAS_ID_ROLE, alias.id)
            self.list.addItem(item)

    def _add(self) -> None:
        name = self.name_edit.text().strip()
        pattern = self.pattern_edit.text().strip()
        if not name or not pattern:
            QMessageBox.information(
                self, "Aliasy", "Vyplňte zobrazený názov aj vzor."
            )
            return
        try:
            self._db.add_alias(self._profile_id, name, pattern)
        except Exception as exc:  # noqa: BLE001 — surface DB errors (e.g. duplicate)
            QMessageBox.warning(
                self, "Chyba", f"Alias sa nepodarilo pridať: {exc}"
            )
            return
        self.name_edit.clear()
        self.pattern_edit.clear()
        self.name_edit.setFocus()
        self._reload()

    def _delete(self) -> None:
        item = self.list.currentItem()
        if not item:
            return
        reply = QMessageBox.question(
            self, "Vymazať alias", f"Naozaj vymazať „{item.text()}“?"
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._db.delete_alias(item.data(_ALIAS_ID_ROLE))
            self._reload()
