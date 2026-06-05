"""Reusable dialogs: ProfileDialog, SaveReceiptDialog, ManualReceiptDialog."""

from datetime import date
from typing import List, Optional

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from models.models import Category, Profile
from models.models import ParsedReceipt


class ProfileDialog(QDialog):
    """Create or edit an archiving profile."""

    def __init__(self, parent: Optional[QWidget] = None,
                 profile: Optional[Profile] = None) -> None:
        super().__init__(parent)
        self._profile = profile
        self.setWindowTitle("Upraviť profil" if profile else "Nový profil")
        self.setMinimumWidth(380)

        self.name_edit = QLineEdit(profile.name if profile else "")
        self.kind_combo = QComboBox()
        self.kind_combo.addItem("Domácnosť", "household")
        self.kind_combo.addItem("Firma", "firm")
        self.vat_combo = QComboBox()
        self.vat_combo.addItem("Bez DPH (jednoduché)", False)
        self.vat_combo.addItem("S rozpisom DPH", True)
        self.ico_edit = QLineEdit(profile.ico if profile else "")
        self.dic_edit = QLineEdit(profile.dic if profile else "")

        if profile:
            idx = self.kind_combo.findData(profile.kind)
            self.kind_combo.setCurrentIndex(max(0, idx))
            self.vat_combo.setCurrentIndex(1 if profile.vat_enabled else 0)

        self.kind_combo.currentIndexChanged.connect(self._on_kind_changed)

        form = QFormLayout()
        form.addRow("Názov:", self.name_edit)
        form.addRow("Typ:", self.kind_combo)
        form.addRow("Režim DPH:", self.vat_combo)
        form.addRow("IČO (voliteľné):", self.ico_edit)
        form.addRow("DIČ (voliteľné):", self.dic_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        if not profile:
            self._on_kind_changed()

    def _on_kind_changed(self) -> None:
        """Default VAT mode by kind (firm → with VAT)."""
        is_firm = self.kind_combo.currentData() == "firm"
        self.vat_combo.setCurrentIndex(1 if is_firm else 0)

    def _on_accept(self) -> None:
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Chýba názov", "Zadajte názov profilu.")
            return
        self.accept()

    def result_profile(self) -> Profile:
        """Return the edited/created Profile (id preserved if editing)."""
        return Profile(
            id=self._profile.id if self._profile else None,
            name=self.name_edit.text().strip(),
            kind=self.kind_combo.currentData(),
            vat_enabled=bool(self.vat_combo.currentData()),
            ico=self.ico_edit.text().strip(),
            dic=self.dic_edit.text().strip(),
        )


class _CategoryPickerMixin:
    """Builds a category combo with number-key quick assignment."""

    def _build_category_combo(self, categories: List[Category],
                              preselect_id: Optional[int]) -> QComboBox:
        combo = QComboBox()
        combo.addItem("Nezaradené", None)
        for cat in categories:
            combo.addItem(cat.name, cat.id)
        if preselect_id is not None:
            idx = combo.findData(preselect_id)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        return combo


class SaveReceiptDialog(QDialog, _CategoryPickerMixin):
    """Quick confirmation dialog after a scan."""

    def __init__(self, parsed: ParsedReceipt, categories: List[Category],
                 preselect_category_id: Optional[int],
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._categories = categories
        self.setWindowTitle("Uložiť bloček")
        self.setMinimumWidth(420)

        vendor = parsed.nazov or (parsed.ico and f"IČO {parsed.ico}") or "Neznámy predajca"
        total = parsed.vat.celkom or 0.0

        info = QLabel(
            f"<b>{vendor}</b><br>"
            f"Dátum: {parsed.datum.strftime('%d.%m.%Y') if parsed.datum else '—'}<br>"
            f"Celkom: <b>{total:.2f} €</b><br>"
            f"Platba: {parsed.platba}<br>"
            f"Položky: {len(parsed.items) if parsed.items else '0 (neúplný)'}"
        )
        info.setTextFormat(Qt.TextFormat.RichText)

        self.category_combo = self._build_category_combo(categories, preselect_category_id)
        self.popis_edit = QLineEdit()

        hint = QLabel("Tip: klávesy 1–9 priradia kategóriu, Enter uloží.")
        hint.setStyleSheet("color:#888;")

        form = QFormLayout()
        form.addRow("Kategória:", self.category_combo)
        form.addRow("Popis:", self.popis_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Uložiť")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Zrušiť")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(info)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(buttons)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Number keys 1–9 select the first N categories."""
        key = event.key()
        if Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
            index = key - Qt.Key.Key_1 + 1  # skip the "Nezaradené" entry at 0
            if index < self.category_combo.count():
                self.category_combo.setCurrentIndex(index)
            return
        super().keyPressEvent(event)

    def selected_category_id(self) -> Optional[int]:
        """Return the chosen category id (None = Nezaradené)."""
        return self.category_combo.currentData()

    def popis(self) -> str:
        """Return the entered description."""
        return self.popis_edit.text().strip()


class ManualReceiptDialog(QDialog, _CategoryPickerMixin):
    """Manual receipt entry for unreadable receipts."""

    def __init__(self, categories: List[Category], vat_enabled: bool,
                 vendor_names: List[str], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._vat_enabled = vat_enabled
        self.setWindowTitle("Pridať bloček ručne")
        self.setMinimumWidth(420)

        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd.MM.yyyy")

        self.vendor_combo = QComboBox()
        self.vendor_combo.setEditable(True)
        self.vendor_combo.addItem("")
        self.vendor_combo.addItems(vendor_names)

        self.category_combo = self._build_category_combo(categories, None)

        self.total_spin = QDoubleSpinBox()
        self.total_spin.setMaximum(999999.0)
        self.total_spin.setDecimals(2)
        self.total_spin.setSuffix(" €")

        self.platba_combo = QComboBox()
        self.platba_combo.addItem("Hotovosť", "hotovost")
        self.platba_combo.addItem("Karta", "karta")

        self.popis_edit = QLineEdit()

        form = QFormLayout()
        form.addRow("Dátum:", self.date_edit)
        form.addRow("Predajca:", self.vendor_combo)
        form.addRow("Kategória:", self.category_combo)
        form.addRow("Celkom:", self.total_spin)
        form.addRow("Platba:", self.platba_combo)
        form.addRow("Popis:", self.popis_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Uložiť")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Zrušiť")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        if not self.vendor_combo.currentText().strip():
            QMessageBox.warning(self, "Chýba predajca", "Zadajte predajcu.")
            return
        if self.total_spin.value() <= 0:
            QMessageBox.warning(self, "Chýba suma", "Zadajte sumu väčšiu ako 0.")
            return
        self.accept()

    def values(self) -> dict:
        """Return the entered values as a dict."""
        qd = self.date_edit.date()
        return {
            "datum": date(qd.year(), qd.month(), qd.day()),
            "vendor_name": self.vendor_combo.currentText().strip(),
            "category_id": self.category_combo.currentData(),
            "celkom": round(self.total_spin.value(), 2),
            "platba": self.platba_combo.currentData(),
            "popis": self.popis_edit.text().strip(),
        }
