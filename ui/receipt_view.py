"""Receipt list view — QAbstractTableModel + QSortFilterProxyModel + summary."""

from typing import List, Optional

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QStyledItemDelegate,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from models.models import Receipt
from ui import constants as c

# Column spec: (key, header, firm_only, vat_group)
# vat_group gates visibility: shown only if any receipt has non-zero value
# (0% base is always shown in firm mode).
_COLUMNS = [
    ("datum", "Dátum", False, None),
    ("vendor", "Predajca", False, None),
    ("category", "Kategória", False, None),
    ("base_0", "0% Základ", True, "always"),
    ("base_5", "5% Z", True, "5"),
    ("tax_5", "5% D", True, "5"),
    ("base_19", "19% Z", True, "19"),
    ("tax_19", "19% D", True, "19"),
    ("base_23", "23% Z", True, "23"),
    ("tax_23", "23% D", True, "23"),
    ("zaokruhlenie", "Zaokr.", True, "round"),
    ("celkom", "Celkom", False, None),
    ("platba", "Platba", False, None),
    ("popis", "Popis", False, None),
]


class ReceiptTableModel(QAbstractTableModel):
    """Table model over a list of Receipt objects with VAT-aware columns."""

    platba_changed = Signal(int, str)   # receipt id, new platba
    popis_changed = Signal(int, str)    # receipt id, new popis

    def __init__(self) -> None:
        super().__init__()
        self._rows: List[Receipt] = []
        self._vat_enabled = False
        self._columns: List[tuple] = []

    def set_data(self, receipts: List[Receipt], vat_enabled: bool) -> None:
        """Replace the model data and recompute visible columns."""
        self.beginResetModel()
        self._rows = receipts
        self._vat_enabled = vat_enabled
        self._columns = self._compute_columns()
        self.endResetModel()

    def _compute_columns(self) -> List[tuple]:
        """Determine which columns are visible given the data + VAT mode."""
        if not self._vat_enabled:
            return [col for col in _COLUMNS if not col[2]]
        active_groups = {"always", "round"}
        for r in self._rows:
            if r.base_5 or r.tax_5:
                active_groups.add("5")
            if r.base_19 or r.tax_19:
                active_groups.add("19")
            if r.base_23 or r.tax_23:
                active_groups.add("23")
        return [
            col for col in _COLUMNS
            if col[3] is None or col[3] in active_groups
        ]

    def receipt_at(self, row: int) -> Optional[Receipt]:
        """Return the Receipt at a given source row."""
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def platba_column(self) -> int:
        """Return the visible column index of the payment column, or -1."""
        for i, col in enumerate(self._columns):
            if col[0] == "platba":
                return i
        return -1

    def column_key(self, column: int) -> str:
        """Return the data key of a visible column."""
        if 0 <= column < len(self._columns):
            return self._columns[column][0]
        return ""

    def vat_columns(self) -> List[tuple]:
        """Return visible VAT-breakdown columns as (key, header) pairs.

        Firm-only columns (``col[2]``) are exactly the VAT breakdown set
        (base/tax per rate + rounding); empty in household mode.
        """
        return [(col[0], col[1]) for col in self._columns if col[2]]

    # -- Qt model interface ------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._columns)

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self._columns[section][1]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        receipt = self._rows[index.row()]
        key = self._columns[index.column()][0]

        if role == Qt.ItemDataRole.DisplayRole:
            return self._display_value(receipt, key)
        if role == Qt.ItemDataRole.ForegroundRole and key == "category":
            if receipt.category_color:
                return QColor(receipt.category_color)
            return QColor(c.CLR_UNCATEGORIZED)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if key in ("celkom", "base_0", "base_5", "tax_5", "base_19",
                       "tax_19", "base_23", "tax_23", "zaokruhlenie"):
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if key in ("datum", "platba"):
                return int(Qt.AlignmentFlag.AlignCenter)
        if role == Qt.ItemDataRole.UserRole:
            return receipt.id
        if role == Qt.ItemDataRole.EditRole and key == "platba":
            return receipt.platba
        if role == Qt.ItemDataRole.EditRole and key == "popis":
            return receipt.popis
        if role == Qt.ItemDataRole.ToolTipRole and not receipt.data_complete:
            return "Neúplný bloček — položky ešte neboli načítané z eKasa."
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        base = super().flags(index)
        if index.isValid() and self._columns[index.column()][0] in ("platba", "popis"):
            return base | Qt.ItemFlag.ItemIsEditable
        return base

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        key = self._columns[index.column()][0]
        receipt = self._rows[index.row()]
        if key == "platba":
            if value not in ("hotovost", "karta") or receipt.platba == value:
                return False
            receipt.platba = value
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])
            self.platba_changed.emit(receipt.id, value)
            return True
        if key == "popis":
            text = str(value).strip()
            if receipt.popis == text:
                return False
            receipt.popis = text
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])
            self.popis_changed.emit(receipt.id, text)
            return True
        return False

    def _display_value(self, r: Receipt, key: str) -> str:
        if key == "datum":
            mark = " ⚠" if not r.data_complete else ""
            return r.datum_display() + mark
        if key == "vendor":
            return r.vendor_name or "—"
        if key == "category":
            if r.category_count and r.category_count > 1:
                return f"zmiešané ({r.category_count})"
            return r.category_name or "Nezaradené"
        if key == "platba":
            return "Karta" if r.platba == "karta" else "Hotovosť"
        if key == "popis":
            return r.popis or ""
        value = getattr(r, key, 0.0) or 0.0
        if key == "celkom":
            return f"{value:.2f} €"
        return f"{value:.2f}" if value else ""


class PlatbaDelegate(QStyledItemDelegate):
    """Inline Hotovosť/Karta combo editor for the payment column."""

    def createEditor(self, parent, option, index):  # noqa: N802
        combo = QComboBox(parent)
        combo.addItem("Hotovosť", "hotovost")
        combo.addItem("Karta", "karta")
        return combo

    def setEditorData(self, editor, index):  # noqa: N802
        value = index.data(Qt.ItemDataRole.EditRole)
        pos = editor.findData(value)
        editor.setCurrentIndex(pos if pos >= 0 else 0)

    def setModelData(self, editor, model, index):  # noqa: N802
        model.setData(index, editor.currentData(), Qt.ItemDataRole.EditRole)


class PopisDelegate(QStyledItemDelegate):
    """Inline text editor for the description column with compact padding."""

    def createEditor(self, parent, option, index):  # noqa: N802
        editor = QLineEdit(parent)
        editor.setStyleSheet("padding:1px; margin:0;")
        return editor

    def setEditorData(self, editor, index):  # noqa: N802
        editor.setText(index.data(Qt.ItemDataRole.EditRole) or "")

    def setModelData(self, editor, model, index):  # noqa: N802
        model.setData(index, editor.text(), Qt.ItemDataRole.EditRole)


class ReceiptView(QWidget):
    """Table + summary bar widget for the receipt list."""

    receipt_activated = Signal(int)   # receipt id (double-click / Enter)
    delete_requested = Signal(int)    # receipt id
    platba_changed = Signal(int, str)  # receipt id, new platba
    popis_changed = Signal(int, str)   # receipt id, new popis

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._popis_history: List[str] = []
        self._vat_enabled = False
        self.model = ReceiptTableModel()
        self.proxy = QSortFilterProxyModel()
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(Qt.ItemDataRole.DisplayRole)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # Only the payment column is editable (delegate); double/selected-click
        # opens its combo. Other columns stay read-only.
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(self._on_activated)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

        self._platba_delegate = PlatbaDelegate(self.table)
        self._popis_delegate = PopisDelegate(self.table)
        self.model.platba_changed.connect(self._on_platba_changed)
        self.model.popis_changed.connect(self.popis_changed)

        self.summary = QLabel()
        self.summary.setObjectName("LastReceipt")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        layout.addWidget(self.summary)

    def set_data(self, receipts: List[Receipt], vat_enabled: bool) -> None:
        """Populate the table and refresh the summary bar."""
        self._vat_enabled = vat_enabled
        self.model.set_data(receipts, vat_enabled)
        self._resize_columns()
        self._assign_platba_delegate()
        self._update_summary(receipts)

    def set_popis_history(self, history: List[str]) -> None:
        """Provide the per-profile description history for the right-click menu."""
        self._popis_history = [h for h in history if h]

    def _show_context_menu(self, pos) -> None:
        """Right-click on the description column → reuse a previous description."""
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        source = self.proxy.mapToSource(index)
        if self.model.column_key(source.column()) != "popis":
            return

        menu = QMenu(self)
        if self._popis_history:
            menu.addAction("Vložiť predošlý popis:").setEnabled(False)
            menu.addSeparator()
            for popis in self._popis_history:
                menu.addAction(popis, lambda checked=False, text=popis:
                               self.model.setData(source, text, Qt.ItemDataRole.EditRole))
            menu.addSeparator()
            menu.addAction("Vymazať popis", lambda:
                           self.model.setData(source, "", Qt.ItemDataRole.EditRole))
        else:
            menu.addAction("Žiadne uložené popisy").setEnabled(False)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _assign_platba_delegate(self) -> None:
        """Attach inline editors to the payment and description columns."""
        for i in range(self.model.columnCount()):
            key = self.model.column_key(i)
            if key == "platba":
                self.table.setItemDelegateForColumn(i, self._platba_delegate)
            elif key == "popis":
                self.table.setItemDelegateForColumn(i, self._popis_delegate)

    def _on_platba_changed(self, receipt_id: int, platba: str) -> None:
        """Re-emit the change for persistence and refresh the summary."""
        self.platba_changed.emit(receipt_id, platba)
        self._update_summary([self.model.receipt_at(r) for r in range(self.model.rowCount())])

    def _resize_columns(self) -> None:
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)

    def _update_summary(self, receipts: List[Receipt]) -> None:
        receipts = [r for r in receipts if r]
        total = round(sum(r.celkom or 0 for r in receipts), 2)
        cash = round(sum(r.celkom or 0 for r in receipts if r.platba != "karta"), 2)
        card = round(sum(r.celkom or 0 for r in receipts if r.platba == "karta"), 2)
        text = (
            f"<b>SPOLU:</b> <span style='color:{c.CLR_ACCENT}'>{total:.2f} €</span>"
            f" &nbsp;|&nbsp; <b>Hotovosť:</b> "
            f"<span style='color:{c.CLR_CASH}'>{cash:.2f} €</span>"
            f" &nbsp;|&nbsp; <b>Karta:</b> "
            f"<span style='color:{c.CLR_CARD}'>{card:.2f} €</span>"
            f" &nbsp;|&nbsp; Počet: {len(receipts)}"
        )
        # Firm mode: add a per-column DPH breakdown sum line (base/tax per rate
        # + rounding), matching the visible VAT columns of the table.
        if self._vat_enabled:
            parts = []
            for key, header in self.model.vat_columns():
                s = round(sum(getattr(r, key, 0) or 0 for r in receipts), 2)
                parts.append(f"{header}: {s:.2f} €")
            if parts:
                text += (
                    f"<br><b>DPH rozklad:</b> "
                    + " &nbsp;|&nbsp; ".join(parts)
                )
        self.summary.setText(text)

    def selected_receipt_id(self) -> Optional[int]:
        """Return the id of the currently selected receipt."""
        index = self.table.currentIndex()
        if not index.isValid():
            return None
        source = self.proxy.mapToSource(index)
        receipt = self.model.receipt_at(source.row())
        return receipt.id if receipt else None

    def select_receipt(self, receipt_id: int) -> None:
        """Select and scroll to a receipt by id."""
        for row in range(self.model.rowCount()):
            r = self.model.receipt_at(row)
            if r and r.id == receipt_id:
                proxy_index = self.proxy.mapFromSource(self.model.index(row, 0))
                self.table.selectRow(proxy_index.row())
                self.table.scrollTo(proxy_index)
                return

    def _on_activated(self, index: QModelIndex) -> None:
        source = self.proxy.mapToSource(index)
        # Double-clicking an editable cell opens its editor, not the detail.
        if self.model.column_key(source.column()) in ("platba", "popis"):
            return
        receipt = self.model.receipt_at(source.row())
        if receipt and receipt.id:
            self.receipt_activated.emit(receipt.id)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        rid = self.selected_receipt_id()
        if rid and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.receipt_activated.emit(rid)
        elif rid and key == Qt.Key.Key_Delete:
            self.delete_requested.emit(rid)
        else:
            super().keyPressEvent(event)
