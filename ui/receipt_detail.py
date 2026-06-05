"""ReceiptDetailDialog — render a stored receipt as a faithful, printable
document (full vendor header, items, VAT summary, OKP/PKP, UID), with
per-item category editing. Rendered from stored ``api_data`` when present,
falling back to DB column values.
"""

import json
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.database import Database
from models.models import Category, Receipt, ReceiptItem


class ReceiptDetailDialog(QDialog):
    """Show the complete receipt document with editable item categories."""

    def __init__(self, db: Database, receipt: Receipt,
                 vat_enabled: bool, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._db = db
        self._receipt = receipt
        self._vat_enabled = vat_enabled
        self._categories: List[Category] = db.get_categories(receipt.profile_id)
        self._items: List[ReceiptItem] = db.get_items(receipt.id)
        self._api: dict = self._load_api_data(receipt)

        self.setWindowTitle(f"Doklad — {receipt.vendor_name or 'bloček'}")
        self.setMinimumSize(760, 680)

        layout = QVBoxLayout(self)

        # Scrollable document area so the whole receipt is reachable.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        doc = QVBoxLayout(content)
        doc.addWidget(self._build_vendor_section())
        doc.addWidget(self._separator())
        doc.addWidget(self._build_receipt_section())
        doc.addWidget(self._separator())
        doc.addWidget(QLabel("<b>Položky</b>"))
        self.table = self._build_items_table()
        doc.addWidget(self.table)
        vat_section = self._build_vat_section()
        if vat_section is not None:
            doc.addWidget(self._separator())
            doc.addWidget(vat_section)
        doc.addWidget(self._separator())
        doc.addWidget(self._build_identifiers_section())
        doc.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        layout.addLayout(self._build_actions())

    # ------------------------------------------------------------ data helpers

    @staticmethod
    def _load_api_data(receipt: Receipt) -> dict:
        """Parse stored api_data JSON; return {} if absent or invalid."""
        if not receipt.api_data:
            return {}
        try:
            data = json.loads(receipt.api_data)
            return data if isinstance(data, dict) else {}
        except (ValueError, TypeError):
            return {}

    def _g(self, *keys: str) -> Optional[str]:
        """Return the first present, non-empty top-level api_data value."""
        for key in keys:
            value = self._api.get(key)
            if value not in (None, "", [], {}):
                return str(value)
        return None

    def _org(self) -> dict:
        """Return the organization sub-object from api_data."""
        return self._api.get("organization") or {}

    @staticmethod
    def _separator() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line

    @staticmethod
    def _section_label(html: str) -> QLabel:
        label = QLabel(html)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    @staticmethod
    def _rows_html(title: str, rows: List[tuple]) -> str:
        """Build a '<b>Title</b>' block from (label, value) rows present."""
        parts = [f"<b>{title}</b>"]
        for label, value in rows:
            if value:
                parts.append(f"{label}: {value}")
        return "<br>".join(parts)

    # ------------------------------------------------------------ vendor

    def _build_vendor_section(self) -> QWidget:
        org = self._org()
        name = org.get("name") or self._receipt.vendor_name or "—"
        address = self._build_address(org)
        rows = [
            ("Názov", name),
            ("Adresa", address),
            ("IČO", org.get("ico")),
            ("DIČ", org.get("dic")),
            ("IČ DPH", org.get("icDph") or org.get("vatId")),
        ]
        return self._section_label(self._rows_html("PREDAJCA", rows))

    @staticmethod
    def _build_address(org: dict) -> str:
        street = " ".join(filter(None, [
            org.get("streetName") or "",
            str(org.get("buildingNumber")
                or org.get("propertyRegistrationNumber") or ""),
        ])).strip()
        city = " ".join(filter(None, [
            str(org.get("postalCode") or ""),
            org.get("municipality") or "",
        ])).strip()
        return ", ".join(p for p in (street, city, org.get("country") or "") if p)

    # ------------------------------------------------------------ receipt meta

    def _build_receipt_section(self) -> QWidget:
        r = self._receipt
        datetime_str = self._g("issueDate", "createDate") or r.datum_display()
        rows = [
            ("Číslo dokladu", self._g("receiptNumber", "invoiceNumber")),
            ("Dátum a čas", datetime_str),
            ("Pokladnica (kód)", self._g("cashRegisterCode")),
            ("Typ dokladu", self._g("type", "receiptType")),
            ("Platba", "Karta" if r.platba == "karta" else "Hotovosť"),
            ("Celkom", f"{r.celkom:.2f} €"),
        ]
        widget = QWidget()
        box = QVBoxLayout(widget)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self._section_label(self._rows_html("DOKLAD", rows)))
        if not r.data_complete:
            warn = self._section_label(
                "<span style='color:#f39c12'>⚠ Neúplný doklad — dáta ešte "
                "neboli načítané z eKasa (skúste „Aktualizovať neúplné“).</span>"
            )
            box.addWidget(warn)
        return widget

    # ------------------------------------------------------------ items

    def _build_items_table(self) -> QTableWidget:
        headers = ["Názov", "Množstvo", "Jedn. cena", "Cena", "DPH %", "Kategória"]
        table = QTableWidget(len(self._items), len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 5):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(5, 180)
        table.verticalHeader().setDefaultSectionSize(34)
        # Cap height so the table doesn't dominate the scroll area.
        table.setMinimumHeight(140)

        for row, item in enumerate(self._items):
            table.setItem(row, 0, self._ro_item(item.name))
            table.setItem(row, 1, self._ro_item(f"{item.quantity:g}"))
            table.setItem(row, 2, self._ro_item(f"{item.unit_price:.2f}"))
            table.setItem(row, 3, self._ro_item(f"{item.price:.2f}"))
            table.setItem(row, 4, self._ro_item(f"{item.vat_rate:g}"))

            combo = QComboBox()
            combo.addItem("Nezaradené", None)
            for cat in self._categories:
                combo.addItem(cat.name, cat.id)
            idx = combo.findData(item.category_id)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.currentIndexChanged.connect(
                lambda _idx, it=item, cb=combo: self._on_item_category_changed(it, cb)
            )
            table.setCellWidget(row, 5, combo)
        return table

    @staticmethod
    def _ro_item(text: str) -> QTableWidgetItem:
        cell = QTableWidgetItem(text)
        cell.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        return cell

    def _on_item_category_changed(self, item: ReceiptItem, combo: QComboBox) -> None:
        category_id = combo.currentData()
        self._db.set_item_category(item.id, category_id)
        item.category_id = category_id

    # ------------------------------------------------------------ VAT summary

    def _build_vat_section(self) -> Optional[QWidget]:
        """Render the VAT recap as it appears on the paper receipt.

        Shown whenever the receipt carries any VAT data, regardless of the
        profile's simplified-display mode — the detail is a faithful copy.
        """
        r = self._receipt
        rate_rows = [
            ("0 %", r.base_0, 0.0),
            ("5 %", r.base_5, r.tax_5),
            ("19 %", r.base_19, r.tax_19),
            ("23 %", r.base_23, r.tax_23),
        ]
        present = [row for row in rate_rows if row[1] or row[2]]
        if not present and not r.zaokruhlenie:
            return None
        lines = ["<b>DPH SÚHRN</b>"]
        for label, base, tax in present:
            lines.append(f"Sadzba {label}: základ {base:.2f} € · daň {tax:.2f} €")
        if r.zaokruhlenie:
            lines.append(f"Zaokrúhlenie: {r.zaokruhlenie:.2f} €")
        lines.append(f"<b>Spolu: {r.celkom:.2f} €</b>")
        return self._section_label("<br>".join(lines))

    # ------------------------------------------------------------ identifiers

    def _build_identifiers_section(self) -> QWidget:
        r = self._receipt
        rows = [
            ("UID / receiptId", self._g("receiptId") or r.qr_raw),
            ("OKP", self._g("okp")),
            ("PKP", self._g("pkp")),
            ("QR (na doklade)", r.qr_raw),
        ]
        return self._section_label(self._rows_html("IDENTIFIKÁTORY", rows))

    # ------------------------------------------------------------ actions

    def _build_actions(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.bulk_combo = QComboBox()
        self.bulk_combo.addItem("Nezaradené", None)
        for cat in self._categories:
            self.bulk_combo.addItem(cat.name, cat.id)
        btn_bulk = QPushButton("Celý bloček → kategória")
        btn_bulk.clicked.connect(self._apply_bulk_category)
        btn_pdf = QPushButton("Exportovať doklad (PDF)")
        btn_pdf.clicked.connect(self._export_pdf)
        btn_close = QPushButton("Zavrieť")
        btn_close.clicked.connect(self.accept)

        row.addWidget(QLabel("Hromadne:"))
        row.addWidget(self.bulk_combo)
        row.addWidget(btn_bulk)
        row.addStretch(1)
        row.addWidget(btn_pdf)
        row.addWidget(btn_close)
        return row

    def _apply_bulk_category(self) -> None:
        category_id = self.bulk_combo.currentData()
        self._db.set_receipt_category(self._receipt.id, category_id)
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, 5)
            if isinstance(combo, QComboBox):
                idx = combo.findData(category_id)
                combo.blockSignals(True)
                combo.setCurrentIndex(idx if idx >= 0 else 0)
                combo.blockSignals(False)
        QMessageBox.information(
            self, "Hotovo", "Kategória bola nastavená pre celý bloček."
        )

    def _export_pdf(self) -> None:
        """Let the user choose a location, export the receipt as PDF, open it."""
        from pathlib import Path

        from PySide6.QtWidgets import QFileDialog

        from core import pdf_export
        from ui.platform_utils import open_path

        r = self._receipt
        suggested = f"doklad_{r.datum.isoformat() if r.datum else r.id}.pdf"
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Uložiť doklad ako PDF", suggested, "PDF (*.pdf)"
        )
        if not path_str:
            return
        if not path_str.lower().endswith(".pdf"):
            path_str += ".pdf"

        try:
            path = pdf_export.export_receipt_detail_pdf(
                receipt=r,
                items=self._items,
                organization=self._org(),
                identifiers={
                    "receiptId": self._g("receiptId") or r.qr_raw,
                    "okp": self._g("okp"),
                    "pkp": self._g("pkp"),
                    "cashRegisterCode": self._g("cashRegisterCode"),
                    "receiptNumber": self._g("receiptNumber", "invoiceNumber"),
                    "issueDate": self._g("issueDate", "createDate"),
                    "qr_raw": r.qr_raw,
                },
                dest=Path(path_str),
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Chyba exportu", str(exc))
            return
        open_path(Path(path))
        QMessageBox.information(self, "Export", f"Doklad uložený:\n{path}")
