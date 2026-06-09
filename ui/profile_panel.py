"""Left sidebar — list of profiles with add/edit/delete + uncategorized badge."""

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from models.models import Profile
from ui import constants as c


class ProfilePanel(QWidget):
    """Sidebar listing profiles; emits signals on selection / CRUD requests."""

    profile_selected = Signal(int)   # profile id
    add_requested = Signal()
    edit_requested = Signal(int)
    delete_requested = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(c.SIDEBAR_WIDTH)

        title = QLabel("PROFILY")
        title.setObjectName("SidebarTitle")

        self.list = QListWidget()
        # Long firm names are truncated with an ellipsis; the full name is shown
        # in a tooltip on hover (sidebar width is limited). The horizontal
        # scrollbar must be off — otherwise the item widens to the full text and
        # the ellipsis never appears.
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.list.currentItemChanged.connect(self._on_selection_changed)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._show_menu)
        self.list.itemDoubleClicked.connect(self._on_double_click)

        self.badge = QLabel("")
        self.badge.setStyleSheet(f"color:{c.CLR_WARNING}; padding:4px;")

        btn_add = QPushButton("+ Profil")
        btn_add.clicked.connect(self.add_requested.emit)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.badge)
        layout.addWidget(btn_add)

    def set_profiles(self, profiles: List[Profile], active_id: Optional[int]) -> None:
        """Populate the list and select the active profile."""
        self.list.blockSignals(True)
        self.list.clear()
        for p in profiles:
            item = QListWidgetItem(p.display_name())
            item.setData(Qt.ItemDataRole.UserRole, p.id)
            item.setToolTip(p.display_name())  # full name on hover (may be elided)
            self.list.addItem(item)
            if p.id == active_id:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        if self.list.currentItem() is None and self.list.count() > 0:
            self.list.setCurrentRow(0)
        # Signals were blocked during population — emit the active selection once.
        current_id = self.current_profile_id()
        if current_id is not None:
            self.profile_selected.emit(current_id)

    def set_uncategorized_count(self, count: int) -> None:
        """Update the uncategorized review badge."""
        self.badge.setText(f"Nezaradené položky: {count}" if count else "")

    def current_profile_id(self) -> Optional[int]:
        """Return the currently selected profile id."""
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_selection_changed(self, current: Optional[QListWidgetItem],
                              _previous: Optional[QListWidgetItem]) -> None:
        if current:
            self.profile_selected.emit(current.data(Qt.ItemDataRole.UserRole))

    def _on_double_click(self, item: QListWidgetItem) -> None:
        self.edit_requested.emit(item.data(Qt.ItemDataRole.UserRole))

    def _show_menu(self, pos) -> None:
        item = self.list.itemAt(pos)
        if not item:
            return
        profile_id = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        act_edit = menu.addAction("Upraviť")
        act_delete = menu.addAction("Vymazať")
        chosen = menu.exec(self.list.mapToGlobal(pos))
        if chosen == act_edit:
            self.edit_requested.emit(profile_id)
        elif chosen == act_delete:
            self.delete_requested.emit(profile_id)
