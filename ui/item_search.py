"""ItemSearchView — search line items, summarise consumption, show price trend."""

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCharts import QChartView, QChart, QDateTimeAxis, QLineSeries, QValueAxis
from PySide6.QtCore import QDateTime, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core import excel_export, pdf_export
from core.database import Database
from ui import constants as c
from ui.alias_manager import AliasManagerDialog
from ui.platform_utils import open_path
from ui.receipt_detail import ReceiptDetailDialog

logger = logging.getLogger(__name__)


class ItemSearchView(QWidget):
    """Item search across receipt line items with totals and a price trend."""

    def __init__(self, db: Database, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._db = db
        self._profile_id: Optional[int] = None
        self._last_term: str = ""
        self._last_alias_id: Optional[int] = None
        self._last_label: str = ""

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Hľadať položku (napr. chlieb)…")
        self.search_edit.returnPressed.connect(self.run_search)

        self.alias_combo = QComboBox()
        self.alias_combo.setMinimumWidth(160)
        self.alias_combo.currentIndexChanged.connect(self._on_alias_changed)

        btn = QPushButton("Hľadať")
        btn.clicked.connect(self.run_search)
        btn_alias = QPushButton("Aliasy…")
        btn_alias.clicked.connect(self._open_alias_manager)

        self.btn_export = QPushButton("Report ▼")
        export_menu = QMenu(self)
        export_menu.addAction("Report (PDF)", self._export_report_pdf)
        export_menu.addAction("Report (Excel)", self._export_report_xlsx)
        self.btn_export.setMenu(export_menu)
        self.btn_export.setEnabled(False)

        top = QHBoxLayout()
        top.addWidget(QLabel("Položka:"))
        top.addWidget(self.search_edit, 1)
        top.addWidget(QLabel("Alias:"))
        top.addWidget(self.alias_combo)
        top.addWidget(btn)
        top.addWidget(btn_alias)
        top.addWidget(self.btn_export)

        headers = ["Dátum", "Predajca", "Položka", "Množstvo",
                   "Jedn. cena", "Cena", "Kategória"]
        self.table = QTableWidget(0, len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.table.setSortingEnabled(True)
        # Results are a read-only view of receipt data — names must match the
        # original receipt, so the table must not be editable.
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # Double-clicking a row opens the receipt the item belongs to.
        self.table.cellDoubleClicked.connect(self._open_receipt_for_row)

        self.totals = QLabel("")
        self.totals.setObjectName("LastReceipt")

        self.chart_view = QChartView()
        self.chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.chart_view.setMinimumHeight(180)
        self._clear_chart()

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.table, 3)
        layout.addWidget(self.totals)
        layout.addWidget(self.chart_view, 2)

    # ------------------------------------------------------------ profile / aliases

    def set_profile(self, profile_id: Optional[int]) -> None:
        """Set the active profile, refresh aliases and clear current results."""
        self._profile_id = profile_id
        self.table.setRowCount(0)
        self.totals.setText("")
        self._last_term = ""
        self._last_alias_id = None
        self._last_label = ""
        self.btn_export.setEnabled(False)
        self._reload_aliases()
        self._clear_chart()

    def _reload_aliases(self) -> None:
        """Populate the alias dropdown with distinct display names."""
        self.alias_combo.blockSignals(True)
        self.alias_combo.clear()
        self.alias_combo.addItem("— bez aliasu —", None)
        if self._profile_id:
            seen = set()
            for alias in self._db.get_aliases(self._profile_id):
                if alias.display_name in seen:
                    continue
                seen.add(alias.display_name)
                self.alias_combo.addItem(alias.display_name, alias.id)
        self.alias_combo.blockSignals(False)

    def _on_alias_changed(self, _index: int) -> None:
        """Run a search immediately when the user picks an alias."""
        if self.alias_combo.currentData() is not None:
            self.run_search()

    def _open_alias_manager(self) -> None:
        if not self._profile_id:
            return
        AliasManagerDialog(self._db, self._profile_id, self).exec()
        self._reload_aliases()

    # ------------------------------------------------------------ search

    def run_search(self) -> None:
        """Execute the item search and populate table + totals + price chart."""
        if not self._profile_id:
            return
        term = self.search_edit.text().strip()
        alias_id = self.alias_combo.currentData()
        self._last_term = term
        self._last_alias_id = alias_id
        self._last_label = (
            self.alias_combo.currentText() if alias_id is not None
            else (term or "Všetky položky")
        )

        rows = self._db.search_items(self._profile_id, term, alias_id=alias_id)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        total_qty = 0.0
        total_spend = 0.0
        for i, r in enumerate(rows):
            datum = str(r.get("r_datum") or "")[:10]
            date_item = QTableWidgetItem(datum)
            date_item.setData(Qt.ItemDataRole.UserRole, r.get("receipt_id"))
            self.table.setItem(i, 0, date_item)
            self.table.setItem(i, 1, QTableWidgetItem(r.get("vendor_name") or "—"))
            self.table.setItem(i, 2, QTableWidgetItem(r.get("name") or ""))
            self.table.setItem(i, 3, QTableWidgetItem(f"{r.get('quantity') or 0:g}"))
            self.table.setItem(i, 4, QTableWidgetItem(f"{r.get('unit_price') or 0:.2f}"))
            self.table.setItem(i, 5, QTableWidgetItem(f"{r.get('price') or 0:.2f}"))
            self.table.setItem(i, 6, QTableWidgetItem(r.get("category_name") or "Nezaradené"))
            total_qty += float(r.get("quantity") or 0)
            total_spend += float(r.get("price") or 0)
        self.table.setSortingEnabled(True)
        self.totals.setText(
            f"Počet: {len(rows)} &nbsp;|&nbsp; "
            f"Množstvo spolu: {total_qty:g} &nbsp;|&nbsp; "
            f"Spolu: <span style='color:{c.CLR_ACCENT}'>{round(total_spend, 2):.2f} €</span>"
        )
        self.btn_export.setEnabled(bool(rows))
        self._build_price_chart()

    # ------------------------------------------------------------ open receipt

    def _open_receipt_for_row(self, row: int, _column: int) -> None:
        """Open the detail dialog for the receipt the double-clicked item is on."""
        if not self._profile_id:
            return
        cell = self.table.item(row, 0)
        if cell is None:
            return
        receipt_id = cell.data(Qt.ItemDataRole.UserRole)
        if receipt_id is None:
            return
        receipt = self._db.get_receipt(int(receipt_id))
        if not receipt:
            return
        profile = self._db.get_profile(self._profile_id)
        vat_enabled = bool(profile.vat_enabled) if profile else False
        ReceiptDetailDialog(self._db, receipt, vat_enabled, self).exec()
        # Category edits made in the detail may change the results — refresh.
        self.run_search()

    # ------------------------------------------------------------ price chart

    def _clear_chart(self) -> None:
        """Show an empty chart with a hint."""
        chart = QChart()
        chart.setTitle("Vývoj jednotkovej ceny")
        chart.setBackgroundBrush(QColor(c.CLR_BG_MAIN))
        chart.setTitleBrush(QColor(c.CLR_TEXT_PRIMARY))
        chart.legend().setVisible(False)
        self.chart_view.setChart(chart)

    def _build_price_chart(self) -> None:
        """Plot the unit-price trend over time for the current search."""
        if not self._profile_id:
            return
        series_data = self._db.get_item_price_series(
            self._profile_id, self._last_term, alias_id=self._last_alias_id
        )
        if not series_data:
            self._clear_chart()
            return

        series = QLineSeries()
        series.setPointsVisible(True)
        series.setColor(QColor(c.CLR_ACCENT))
        min_price = min(p for _, p in series_data)
        max_price = max(p for _, p in series_data)
        min_ts = max_ts = None
        for date_iso, price in series_data:
            qdt = QDateTime.fromString(date_iso, "yyyy-MM-dd")
            if not qdt.isValid():
                continue
            ms = qdt.toMSecsSinceEpoch()
            series.append(float(ms), float(price))
            min_ts = ms if min_ts is None else min(min_ts, ms)
            max_ts = ms if max_ts is None else max(max_ts, ms)

        chart = QChart()
        chart.addSeries(series)
        chart.setTitle(f"Vývoj jednotkovej ceny — {self._last_label}")
        chart.setBackgroundBrush(QColor(c.CLR_BG_MAIN))
        chart.setTitleBrush(QColor(c.CLR_TEXT_PRIMARY))
        chart.legend().setVisible(False)

        axis_x = QDateTimeAxis()
        axis_x.setFormat("MM/yyyy")
        axis_x.setLabelsColor(QColor(c.CLR_TEXT_PRIMARY))
        axis_x.setTickCount(min(max(len(series_data), 2), 8))
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(axis_x)

        axis_y = QValueAxis()
        axis_y.setLabelFormat("%.2f €")
        axis_y.setLabelsColor(QColor(c.CLR_TEXT_PRIMARY))
        span = max(max_price - min_price, 0.10)
        axis_y.setRange(max(min_price - span * 0.2, 0), max_price + span * 0.2)
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_y)

        self.chart_view.setChart(chart)

    # ------------------------------------------------------------ export

    def _export_report_pdf(self) -> None:
        """Export the consumption report (per-month qty + spend) as a PDF."""
        self._export_report("pdf")

    def _export_report_xlsx(self) -> None:
        """Export the consumption report as an Excel workbook."""
        self._export_report("xlsx")

    def _export_report(self, fmt: str) -> None:
        """Build the monthly report for the current search and export it."""
        if not self._profile_id or (not self._last_term and self._last_alias_id is None):
            return
        profile = self._db.get_profile(self._profile_id)
        if not profile:
            return
        monthly = self._db.get_item_monthly_report(
            self._profile_id, self._last_term, alias_id=self._last_alias_id
        )
        if not monthly:
            QMessageBox.information(self, "Export", "Žiadne dáta na export.")
            return
        safe = "".join(ch if ch.isalnum() else "_" for ch in self._last_label) or "polozka"
        ext, filt = ("xlsx", "Excel (*.xlsx)") if fmt == "xlsx" else ("pdf", "PDF (*.pdf)")
        last_dir = self._db.get_setting("last_export_dir", str(Path.home()))
        suggested = str(Path(last_dir) / f"report_{safe}.{ext}")
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportovať report položky", suggested, filt
        )
        if not path:
            return
        self._db.set_setting("last_export_dir", str(Path(path).parent))
        try:
            if fmt == "xlsx":
                excel_export.export_item_report_xlsx(
                    Path(path), self._last_label, monthly, profile
                )
            else:
                pdf_export.export_item_report_pdf(
                    Path(path), self._last_label, monthly, profile
                )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Chyba exportu", str(exc))
            return
        open_path(Path(path))
