"""CategoryManagerDialog — CRUD categories for the active profile."""

from typing import Optional

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.database import Database
from ui import constants as c


class CategoryManagerDialog(QDialog):
    """Manage (add/edit/delete/recolour) categories for a profile."""

    def __init__(self, db: Database, profile_id: int,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._db = db
        self._profile_id = profile_id
        self.setWindowTitle("Správa kategórií")
        self.setMinimumSize(380, 420)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self._rename)

        btn_add = QPushButton("Pridať")
        btn_rename = QPushButton("Premenovať")
        btn_color = QPushButton("Farba")
        btn_delete = QPushButton("Vymazať")
        btn_close = QPushButton("Zavrieť")
        btn_add.clicked.connect(self._add)
        btn_rename.clicked.connect(lambda: self._rename(self.list.currentItem()))
        btn_color.clicked.connect(self._recolor)
        btn_delete.clicked.connect(self._delete)
        btn_close.clicked.connect(self.accept)

        btn_row = QHBoxLayout()
        for b in (btn_add, btn_rename, btn_color, btn_delete):
            btn_row.addWidget(b)

        layout = QVBoxLayout(self)
        layout.addWidget(self.list)
        layout.addLayout(btn_row)
        layout.addWidget(btn_close)

        self._reload()

    def _reload(self) -> None:
        self.list.clear()
        # Built-in "Nezaradené" fallback (category_id IS NULL) — always shown,
        # neutral grey, not editable/deletable.
        builtin = QListWidgetItem("Nezaradené")
        builtin.setData(0x0100, None)               # Qt.UserRole — no real id
        builtin.setData(0x0101, c.CLR_UNCATEGORIZED)  # Qt.UserRole+1
        builtin.setForeground(QColor(c.CLR_UNCATEGORIZED))
        builtin.setToolTip("Vstavaná kategória – nedá sa upraviť ani vymazať.")
        self.list.addItem(builtin)
        for cat in self._db.get_categories(self._profile_id):
            item = QListWidgetItem(cat.name)
            item.setData(0x0100, cat.id)        # Qt.UserRole
            item.setData(0x0101, cat.color)     # Qt.UserRole+1
            item.setForeground(QColor(cat.color))
            self.list.addItem(item)

    @staticmethod
    def _is_builtin(item: Optional[QListWidgetItem]) -> bool:
        """True for the virtual 'Nezaradené' fallback row (no real category id)."""
        return item is not None and item.data(0x0100) is None

    def _add(self) -> None:
        name, ok = QInputDialog.getText(self, "Nová kategória", "Názov:")
        if ok and name.strip():
            try:
                self._db.add_category(self._profile_id, name.strip())
            except Exception as exc:  # noqa: BLE001 — surface DB errors to user
                QMessageBox.warning(self, "Chyba", f"Nepodarilo sa pridať: {exc}")
            self._reload()

    def _rename(self, item: Optional[QListWidgetItem]) -> None:
        if not item:
            return
        if self._is_builtin(item):
            QMessageBox.information(
                self, "Nezaradené",
                "Vstavaná kategória „Nezaradené“ sa nedá upraviť.",
            )
            return
        name, ok = QInputDialog.getText(
            self, "Premenovať", "Názov:", text=item.text()
        )
        if ok and name.strip():
            self._db.update_category(item.data(0x0100), name.strip(), item.data(0x0101))
            self._reload()

    def _recolor(self) -> None:
        item = self.list.currentItem()
        if not item:
            return
        if self._is_builtin(item):
            QMessageBox.information(
                self, "Nezaradené",
                "Vstavaná kategória „Nezaradené“ sa nedá upraviť.",
            )
            return
        color = QColorDialog.getColor(QColor(item.data(0x0101)), self, "Vyberte farbu")
        if color.isValid():
            self._db.update_category(item.data(0x0100), item.text(), color.name())
            self._reload()

    def _delete(self) -> None:
        item = self.list.currentItem()
        if not item:
            return
        if self._is_builtin(item):
            QMessageBox.information(
                self, "Nezaradené",
                "Vstavaná kategória „Nezaradené“ sa nedá vymazať.",
            )
            return
        reply = QMessageBox.question(
            self, "Vymazať kategóriu",
            f"Naozaj vymazať „{item.text()}“? Položky ostanú nezaradené.",
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._db.delete_category(item.data(0x0100))
            self._reload()
