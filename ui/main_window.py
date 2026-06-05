"""Main application window — header, sidebar, tabs, scanner and scan flow."""

import logging
from datetime import date
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QObject, QSize, Qt, QThread, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core import company_lookup
from core.database import Database
from core import excel_export
from core import pdf_export
from core.ekasa_parser import parse_qr
from models.models import ParsedReceipt, Profile, Receipt, ReceiptItem
from ui import constants as c
from ui.category_manager import CategoryManagerDialog
from ui.dashboard import DashboardWidget
from ui.dialogs import ManualReceiptDialog, ProfileDialog, SaveReceiptDialog
from ui.item_search import ItemSearchView
from ui.platform_utils import open_path, open_url
from ui.profile_panel import ProfilePanel
from ui.receipt_detail import ReceiptDetailDialog
from ui.receipt_view import ReceiptView
from ui.scanner import ScannerInput

logger = logging.getLogger(__name__)

_YEARS = list(range(2025, 2036))


class ScanWorker(QObject):
    """Runs parse_qr on a worker thread (never blocks the GUI)."""

    finished = Signal(object)   # ParsedReceipt
    failed = Signal(str)

    def __init__(self, qr_raw: str) -> None:
        super().__init__()
        self._qr_raw = qr_raw

    def run(self) -> None:
        """Parse the QR and emit the result."""
        try:
            parsed = parse_qr(self._qr_raw)
            self.finished.emit(parsed)
        except Exception as exc:  # noqa: BLE001 — report to UI
            logger.exception("Scan worker zlyhal")
            self.failed.emit(str(exc))


class ResyncWorker(QObject):
    """Re-fetches incomplete receipts from eKasa on a worker thread.

    Receipts that now return items get their items, VAT breakdown, vendor and
    ``api_data`` filled and ``data_complete`` set; still-empty ones only record
    a bounded sync attempt. The GUI thread is never blocked.
    """

    finished = Signal(int, int)   # (updated, total)
    failed = Signal(str)

    def __init__(self, db: Database, profile_id: int,
                 max_attempts: Optional[int]) -> None:
        super().__init__()
        self._db = db
        self._profile_id = profile_id
        self._max_attempts = max_attempts

    def run(self) -> None:
        """Process all eligible incomplete receipts and emit the tally."""
        try:
            incomplete = self._db.get_incomplete_receipts(
                self._profile_id, self._max_attempts
            )
            updated = sum(1 for r in incomplete if self._sync_one(r))
            self.finished.emit(updated, len(incomplete))
        except Exception as exc:  # noqa: BLE001 — report to UI
            logger.exception("Resync worker zlyhal")
            self.failed.emit(str(exc))

    def _sync_one(self, r: Receipt) -> bool:
        """Re-sync a single receipt. Returns True when it became complete."""
        if not r.qr_raw:
            return False
        try:
            parsed = parse_qr(r.qr_raw)
        except Exception as exc:  # noqa: BLE001 — record and move on
            self._db.record_sync_attempt(r.id, str(exc))
            return False
        if not parsed.items:
            self._db.record_sync_attempt(r.id, "Bloček ešte nebol nahraný do eKasa.")
            return False

        # Resolve / create the vendor from the freshly fetched data
        # (manual UID-only entries have no vendor yet).
        if parsed.ico and not parsed.nazov:
            info = company_lookup.lookup_by_ico(parsed.ico)
            if info:
                parsed.nazov = info.name
                parsed.adresa = info.full_address()
                parsed.dic = parsed.dic or info.dic
        if parsed.ico or parsed.nazov:
            vendor = self._db.get_or_create_vendor(self._profile_id, parsed)
            self._db.set_receipt_vendor(r.id, vendor.id)

        for it in parsed.items:
            it.category_id = r.default_category_id
        self._db.replace_items(r.id, parsed.items)
        r.base_0, r.base_5, r.tax_5 = parsed.vat.base_0, parsed.vat.base_5, parsed.vat.tax_5
        r.base_19, r.tax_19 = parsed.vat.base_19, parsed.vat.tax_19
        r.base_23, r.tax_23 = parsed.vat.base_23, parsed.vat.tax_23
        r.zaokruhlenie, r.celkom = parsed.vat.zaokruhlenie, parsed.vat.celkom
        r.platba = parsed.platba
        if parsed.datum:
            r.datum = parsed.datum
            r.account_year, r.account_month = parsed.datum.year, parsed.datum.month
        self._db.update_receipt_vat(r)
        self._db.set_receipt_complete(r.id, True, parsed.api_data or "")
        return True


class MainWindow(QMainWindow):
    """Root window orchestrating profiles, scanning and the three tabs."""

    _KOFI_URL = "https://ko-fi.com/orimslav"

    def __init__(self, db: Database, assets_dir: Path) -> None:
        super().__init__()
        self._db = db
        self._assets_dir = assets_dir
        self._active_profile: Optional[Profile] = None
        self._thread: Optional[QThread] = None
        self._worker: Optional[ScanWorker] = None
        self._resync_thread: Optional[QThread] = None
        self._resync_worker: Optional[ResyncWorker] = None

        self.setWindowTitle("Archív bločkov")
        self.setMinimumSize(c.MIN_WINDOW_WIDTH, c.MIN_WINDOW_HEIGHT)
        self.resize(1600, 900)

        self._build_ui()

        self.scanner = ScannerInput(self, self._on_scan)
        self.scanner.ready_changed.connect(self._update_scanner_status)
        self._update_scanner_status(self.scanner.is_ready())
        self._load_profiles()
        self._auto_refresh_incomplete()

    def _update_scanner_status(self, ready: bool) -> None:
        """Reflect scan readiness (buffer focus) in the header indicator."""
        if ready:
            self.scanner_status.setText("● Pripravený na sken")
            self.scanner_status.setStyleSheet(f"color:{c.CLR_SUCCESS}; font-weight:bold;")
        else:
            self.scanner_status.setText("○ Klik do okna pre sken")
            self.scanner_status.setStyleSheet(f"color:{c.CLR_TEXT_SECONDARY};")

    # ------------------------------------------------------------ UI build

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        self.profile_panel = ProfilePanel()
        self.profile_panel.profile_selected.connect(self._on_profile_selected)
        self.profile_panel.add_requested.connect(self._add_profile)
        self.profile_panel.edit_requested.connect(self._edit_profile)
        self.profile_panel.delete_requested.connect(self._delete_profile)
        body.addWidget(self.profile_panel)
        body.addWidget(self._build_tabs(), 1)
        root.addLayout(body, 1)

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("HeaderBar")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(12, 8, 12, 8)

        logo = QLabel()
        logo_path = self._assets_dir / "logo.png"
        if logo_path.exists():
            pix = QPixmap(str(logo_path)).scaledToHeight(
                c.LOGO_SIZE, Qt.TransformationMode.SmoothTransformation
            )
            logo.setPixmap(pix)
        title = QLabel("Archív bločkov")
        title.setObjectName("AppTitle")

        self.scanner_status = QLabel("○ Pripravený na sken")
        self.scanner_status.setObjectName("ScannerStatus")
        self.last_receipt_label = QLabel("")
        self.last_receipt_label.setObjectName("LastReceipt")

        layout.addWidget(logo)
        layout.addWidget(title)
        layout.addSpacing(20)
        layout.addWidget(self.last_receipt_label, 1)
        layout.addWidget(self.scanner_status)
        kofi = self._build_kofi_button()
        if kofi is not None:
            layout.addWidget(kofi)
        return header

    def _build_kofi_button(self) -> Optional[QPushButton]:
        """Header icon linking to the author's Ko-fi support page."""
        icon_path = self._assets_dir / "kofi_icon.png"
        if not icon_path.exists():
            return None
        btn = QPushButton()
        btn.setObjectName("KofiButton")
        btn.setIcon(QIcon(str(icon_path)))
        btn.setIconSize(QSize(c.LOGO_SIZE, c.LOGO_SIZE))
        btn.setFlat(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip("Podporte vývoj — kúpte mi kávu (Ko-fi)")
        btn.clicked.connect(lambda: open_url(self._KOFI_URL))
        return btn

    def _build_tabs(self) -> QTabWidget:
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_receipts_tab(), "Bločky")
        self.item_search = ItemSearchView(self._db)
        self.tabs.addTab(self.item_search, "Položky")
        self.dashboard = DashboardWidget(self._db)
        self.tabs.addTab(self.dashboard, "Dashboard")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        return self.tabs

    def _build_receipts_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Filter toolbar
        filters = QHBoxLayout()
        self.year_combo = QComboBox()
        self.year_combo.addItem("Všetky roky", None)
        for y in _YEARS:
            self.year_combo.addItem(str(y), y)
        self.month_combo = QComboBox()
        self.month_combo.addItem("Všetky mesiace", None)
        for i, m in enumerate(c.MONTHS_SK, start=1):
            self.month_combo.addItem(m, i)
        self.category_filter = QComboBox()
        self.vendor_filter = QComboBox()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Hľadať…")

        self.year_combo.currentIndexChanged.connect(self._reload_receipts)
        self.month_combo.currentIndexChanged.connect(self._reload_receipts)
        self.category_filter.currentIndexChanged.connect(self._reload_receipts)
        self.vendor_filter.currentIndexChanged.connect(self._reload_receipts)
        self.search_edit.textChanged.connect(self._reload_receipts)

        for label, w in (
            ("Rok:", self.year_combo), ("Mesiac:", self.month_combo),
            ("Kategória:", self.category_filter), ("Predajca:", self.vendor_filter),
        ):
            filters.addWidget(QLabel(label))
            filters.addWidget(w)
        filters.addWidget(self.search_edit, 1)
        layout.addLayout(filters)

        # Receipt table
        self.receipt_view = ReceiptView()
        self.receipt_view.receipt_activated.connect(self._open_receipt_detail)
        self.receipt_view.delete_requested.connect(self._delete_receipt)
        self.receipt_view.platba_changed.connect(self._db.set_receipt_platba)
        self.receipt_view.popis_changed.connect(self._on_popis_changed)
        layout.addWidget(self.receipt_view, 1)

        # Action buttons
        actions = QHBoxLayout()
        btn_uid = QPushButton("Zadať UID")
        btn_manual = QPushButton("Pridať ručne")
        btn_detail = QPushButton("Zobraziť doklad")
        btn_delete = QPushButton("Vymazať")
        btn_categories = QPushButton("Kategórie…")
        self.btn_resync = QPushButton("Aktualizovať neúplné")
        btn_resync = self.btn_resync
        btn_export = QPushButton("Export ▼")
        btn_export.setMenu(self._build_export_menu())
        btn_backup = QPushButton("Zálohovať DB")
        btn_restore = QPushButton("Obnoviť DB")
        btn_security = QPushButton("Zabezpečenie…")
        btn_uid.clicked.connect(self._enter_uid)
        btn_manual.clicked.connect(self._add_manual_receipt)
        btn_detail.clicked.connect(self._open_selected_detail)
        btn_delete.clicked.connect(self._delete_selected_receipt)
        btn_categories.clicked.connect(self._open_category_manager)
        btn_resync.clicked.connect(self._resync_incomplete)
        btn_backup.clicked.connect(self._backup_db)
        btn_restore.clicked.connect(self._restore_db)
        btn_security.clicked.connect(self._open_security)
        for b in (btn_uid, btn_manual, btn_detail, btn_delete, btn_categories,
                  btn_resync, btn_export, btn_backup, btn_restore, btn_security):
            actions.addWidget(b)
        actions.addStretch(1)
        layout.addLayout(actions)
        return tab

    # ------------------------------------------------------------ profiles

    def _load_profiles(self) -> None:
        profiles = self._db.get_profiles()
        if not profiles:
            self._prompt_first_profile()
            profiles = self._db.get_profiles()
            if not profiles:
                return
        active_id = self._db.get_setting("active_profile_id", "")
        active = int(active_id) if active_id.isdigit() else profiles[0].id
        self.profile_panel.set_profiles(profiles, active)

    def _prompt_first_profile(self) -> None:
        QMessageBox.information(
            self, "Vitajte",
            "Najprv vytvorte profil. Odporúčame „Moja domácnosť“.",
        )
        dialog = ProfileDialog(self)
        dialog.name_edit.setText("Moja domácnosť")
        if dialog.exec():
            self._db.add_profile(dialog.result_profile())

    def _on_profile_selected(self, profile_id: int) -> None:
        self._active_profile = self._db.get_profile(profile_id)
        if not self._active_profile:
            return
        self._db.set_setting("active_profile_id", str(profile_id))
        self._refresh_filter_combos()
        self._reload_receipts()
        self.item_search.set_profile(profile_id)
        self.dashboard.set_profile(profile_id)
        self._update_uncategorized_badge()

    def _add_profile(self) -> None:
        dialog = ProfileDialog(self)
        if dialog.exec():
            new_id = self._db.add_profile(dialog.result_profile())
            self.profile_panel.set_profiles(self._db.get_profiles(), new_id)

    def _edit_profile(self, profile_id: int) -> None:
        profile = self._db.get_profile(profile_id)
        if not profile:
            return
        dialog = ProfileDialog(self, profile)
        if dialog.exec():
            self._db.update_profile(dialog.result_profile())
            self.profile_panel.set_profiles(self._db.get_profiles(), profile_id)
            self._on_profile_selected(profile_id)

    def _delete_profile(self, profile_id: int) -> None:
        if len(self._db.get_profiles()) <= 1:
            QMessageBox.warning(self, "Nedá sa", "Musí existovať aspoň jeden profil.")
            return
        reply = QMessageBox.question(
            self, "Vymazať profil",
            "Naozaj vymazať profil a všetky jeho dáta (bločky, kategórie…)?",
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._db.delete_profile(profile_id)
            self._load_profiles()

    # ------------------------------------------------------------ filters

    def _refresh_filter_combos(self) -> None:
        if not self._active_profile:
            return
        pid = self._active_profile.id
        self.category_filter.blockSignals(True)
        self.vendor_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem("Všetky kategórie", None)
        for cat in self._db.get_categories(pid):
            self.category_filter.addItem(cat.name, cat.id)
        self.vendor_filter.clear()
        self.vendor_filter.addItem("Všetci predajcovia", None)
        for v in self._db.get_vendors(pid):
            self.vendor_filter.addItem(v.display_name(), v.id)
        self.category_filter.blockSignals(False)
        self.vendor_filter.blockSignals(False)

    def _reload_receipts(self) -> None:
        if not self._active_profile:
            return
        receipts = self._db.get_receipts(
            self._active_profile.id,
            year=self.year_combo.currentData(),
            month=self.month_combo.currentData(),
            category_id=self.category_filter.currentData(),
            vendor_id=self.vendor_filter.currentData(),
            search=self.search_edit.text(),
        )
        self.receipt_view.set_data(receipts, self._active_profile.vat_enabled)
        self.receipt_view.set_popis_history(
            self._db.get_popis_history(self._active_profile.id)
        )

    def _update_uncategorized_badge(self) -> None:
        if self._active_profile:
            count = self._db.count_uncategorized(self._active_profile.id)
            self.profile_panel.set_uncategorized_count(count)

    def _on_tab_changed(self, index: int) -> None:
        if self.tabs.tabText(index) == "Dashboard":
            self.dashboard.refresh()

    # ------------------------------------------------------------ scanning

    def _on_popis_changed(self, receipt_id: int, popis: str) -> None:
        """Persist an inline description edit and remember it for reuse."""
        self._db.set_receipt_popis(receipt_id, popis)
        if popis and self._active_profile:
            self._db.add_popis_history(self._active_profile.id, popis)
            self.receipt_view.set_popis_history(
                self._db.get_popis_history(self._active_profile.id)
            )

    def _enter_uid(self) -> None:
        """Manually enter a receipt UID/ID — behaves exactly like a scan."""
        if not self._active_profile:
            QMessageBox.warning(self, "Žiadny profil", "Najprv vyberte profil.")
            return
        uid, ok = QInputDialog.getText(
            self, "Zadať UID",
            "Zadajte UID / ID bločku (keď je QR poškodený):",
        )
        if ok and uid.strip():
            self._on_scan(uid.strip())

    def _on_scan(self, qr_raw: str) -> None:
        if not self._active_profile:
            QMessageBox.warning(self, "Žiadny profil", "Najprv vyberte profil.")
            return
        if self._db.receipt_exists(self._active_profile.id, qr_raw):
            reply = QMessageBox.question(
                self, "Duplicitný bloček",
                "Tento bloček už v profile existuje. Uložiť napriek tomu?",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.last_receipt_label.setText("Spracúvam bloček…")
        self._start_scan_worker(qr_raw)

    def _start_scan_worker(self, qr_raw: str) -> None:
        self._thread = QThread()
        self._worker = ScanWorker(qr_raw)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_scan_finished)
        self._worker.failed.connect(self._on_scan_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_scan_failed(self, message: str) -> None:
        self.last_receipt_label.setText("")
        QMessageBox.critical(self, "Chyba skenovania", message)

    def _on_scan_finished(self, parsed: ParsedReceipt) -> None:
        # Enrich vendor via registeruz if name missing but IČO present.
        if parsed.ico and not parsed.nazov:
            info = company_lookup.lookup_by_ico(parsed.ico)
            if info:
                parsed.nazov = info.name
                parsed.adresa = info.full_address()
                parsed.dic = parsed.dic or info.dic
        self._save_parsed_receipt(parsed)

    def _save_parsed_receipt(self, parsed: ParsedReceipt) -> None:
        pid = self._active_profile.id
        vendor = self._db.get_or_create_vendor(pid, parsed)
        categories = self._db.get_categories(pid)
        preselect = vendor.default_category_id

        dialog = SaveReceiptDialog(parsed, categories, preselect, self)
        if not dialog.exec():
            self.last_receipt_label.setText("")
            return

        category_id = dialog.selected_category_id()
        receipt = self._parsed_to_receipt(parsed, pid, vendor.id, category_id,
                                          dialog.popis())
        receipt_id = self._db.insert_receipt(receipt)
        self._db.insert_items(receipt_id, self._items_for_save(parsed, category_id))

        if category_id is not None:
            self._db.set_vendor_default_category(vendor.id, category_id)
        if dialog.popis():
            self._db.add_popis_history(pid, dialog.popis())

        self._refresh_filter_combos()
        self._reload_receipts()
        self.receipt_view.select_receipt(receipt_id)
        self._update_uncategorized_badge()

        total = parsed.vat.celkom or 0.0
        cat_name = next((cc.name for cc in categories if cc.id == category_id), "Nezaradené")
        self.last_receipt_label.setText(
            f"Posledný bloček: {vendor.display_name()}  {total:.2f} €  {cat_name}"
        )

    @staticmethod
    def _parsed_to_receipt(parsed: ParsedReceipt, profile_id: int,
                           vendor_id: int, category_id: Optional[int],
                           popis: str) -> Receipt:
        v = parsed.vat
        return Receipt(
            id=None, profile_id=profile_id, vendor_id=vendor_id, datum=parsed.datum,
            base_0=v.base_0, base_5=v.base_5, tax_5=v.tax_5,
            base_19=v.base_19, tax_19=v.tax_19, base_23=v.base_23, tax_23=v.tax_23,
            zaokruhlenie=v.zaokruhlenie, celkom=v.celkom, platba=parsed.platba,
            popis=popis, qr_raw=parsed.qr_raw, default_category_id=category_id,
            data_complete=parsed.data_complete, api_data=parsed.api_data,
        )

    @staticmethod
    def _items_for_save(parsed: ParsedReceipt, category_id: Optional[int]
                        ) -> List[ReceiptItem]:
        """Return items with the chosen category, or one synthetic total item."""
        if parsed.items:
            for it in parsed.items:
                it.category_id = category_id
            return parsed.items
        return [ReceiptItem(
            id=None, receipt_id=None, name="(celý bloček)", quantity=1,
            unit_price=parsed.vat.celkom or 0.0, price=parsed.vat.celkom or 0.0,
            vat_rate=0, category_id=category_id, is_synthetic=True,
        )]

    # ------------------------------------------------------------ manual entry

    def _add_manual_receipt(self) -> None:
        if not self._active_profile:
            return
        pid = self._active_profile.id
        categories = self._db.get_categories(pid)
        vendor_names = [v.display_name() for v in self._db.get_vendors(pid)]
        dialog = ManualReceiptDialog(
            categories, self._active_profile.vat_enabled, vendor_names, self
        )
        if not dialog.exec():
            return
        vals = dialog.values()
        vendor = self._db.get_or_create_vendor_by_name(pid, vals["vendor_name"])
        receipt = Receipt(
            id=None, profile_id=pid, vendor_id=vendor.id, datum=vals["datum"],
            celkom=vals["celkom"], platba=vals["platba"], popis=vals["popis"],
            default_category_id=vals["category_id"], data_complete=False,
        )
        receipt_id = self._db.insert_receipt(receipt)
        self._db.insert_items(receipt_id, [ReceiptItem(
            id=None, receipt_id=None, name="(celý bloček)", quantity=1,
            unit_price=vals["celkom"], price=vals["celkom"], vat_rate=0,
            category_id=vals["category_id"], is_synthetic=True,
        )])
        self._refresh_filter_combos()
        self._reload_receipts()
        self.receipt_view.select_receipt(receipt_id)
        self._update_uncategorized_badge()

    # ------------------------------------------------------------ detail / delete

    def _open_selected_detail(self) -> None:
        rid = self.receipt_view.selected_receipt_id()
        if rid:
            self._open_receipt_detail(rid)
        else:
            QMessageBox.information(self, "Žiadny výber", "Vyberte bloček.")

    def _open_receipt_detail(self, receipt_id: int) -> None:
        receipt = self._db.get_receipt(receipt_id)
        if not receipt:
            return
        dialog = ReceiptDetailDialog(
            self._db, receipt, self._active_profile.vat_enabled, self
        )
        dialog.exec()
        self._reload_receipts()
        self._update_uncategorized_badge()

    def _delete_selected_receipt(self) -> None:
        rid = self.receipt_view.selected_receipt_id()
        if rid:
            self._delete_receipt(rid)

    def _delete_receipt(self, receipt_id: int) -> None:
        reply = QMessageBox.question(
            self, "Vymazať bloček", "Naozaj vymazať vybraný bloček?"
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._db.delete_receipt(receipt_id)
            self._reload_receipts()
            self._update_uncategorized_badge()

    # ------------------------------------------------------------ categories

    def _open_category_manager(self) -> None:
        if not self._active_profile:
            return
        CategoryManagerDialog(self._db, self._active_profile.id, self).exec()
        self._refresh_filter_combos()
        self._reload_receipts()

    # ------------------------------------------------------------ re-sync

    def _resync_incomplete(self) -> None:
        """Manual re-sync — always forces a retry regardless of the attempt cap."""
        self._start_resync(max_attempts=None, silent=False)

    def _auto_refresh_incomplete(self) -> None:
        """On-start re-sync — only when enabled, capped by max_sync_attempts."""
        if self._db.get_setting("auto_refresh_incomplete", "1") != "1":
            return
        self._start_resync(max_attempts=self._max_sync_attempts(), silent=True)

    def _max_sync_attempts(self) -> int:
        """Read the re-sync attempt cap for the auto-refresh (default 10)."""
        value = self._db.get_setting("max_sync_attempts", "10")
        return int(value) if value.isdigit() else 10

    def _start_resync(self, max_attempts: Optional[int], *, silent: bool) -> None:
        """Spin up the resync worker for the active profile (if not already running)."""
        if not self._active_profile or self._resync_thread is not None:
            return
        incomplete = self._db.get_incomplete_receipts(
            self._active_profile.id, max_attempts
        )
        if not incomplete:
            if not silent:
                QMessageBox.information(self, "Hotovo", "Žiadne neúplné bločky.")
            return

        self.btn_resync.setEnabled(False)
        self._resync_thread = QThread()
        self._resync_worker = ResyncWorker(
            self._db, self._active_profile.id, max_attempts
        )
        self._resync_worker.moveToThread(self._resync_thread)
        self._resync_thread.started.connect(self._resync_worker.run)
        self._resync_worker.finished.connect(
            lambda updated, total: self._on_resync_finished(updated, total, silent)
        )
        self._resync_worker.failed.connect(
            lambda error: self._on_resync_failed(error, silent)
        )
        self._resync_thread.start()

    def _on_resync_finished(self, updated: int, total: int, silent: bool) -> None:
        self._cleanup_resync_thread()
        self._reload_receipts()
        if not silent:
            QMessageBox.information(
                self, "Aktualizácia neúplných",
                f"Aktualizovaných {updated} z {total} bločkov.",
            )
        elif updated:
            self.last_receipt_label.setText(
                f"Automaticky doplnených {updated} neúplných bločkov"
            )

    def _on_resync_failed(self, error: str, silent: bool) -> None:
        self._cleanup_resync_thread()
        if not silent:
            QMessageBox.critical(self, "Chyba aktualizácie", error)
        else:
            logger.warning(f"Automatická aktualizácia neúplných zlyhala: {error}")

    def _cleanup_resync_thread(self) -> None:
        """Stop the resync thread and re-enable the button."""
        if self._resync_thread is not None:
            self._resync_thread.quit()
            self._resync_thread.wait()
        self._resync_thread = None
        self._resync_worker = None
        self.btn_resync.setEnabled(True)

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt override
        """Wait for any running worker thread before the window is destroyed."""
        for thread in (self._resync_thread, self._thread):
            if thread is not None and thread.isRunning():
                thread.quit()
                thread.wait()
        super().closeEvent(event)

    # ------------------------------------------------------------ export / backup

    def _build_export_menu(self) -> QMenu:
        """Build the Export dropdown menu (CSV/XLSX + PDF reports)."""
        menu = QMenu(self)
        menu.addAction("Bločky – PDF", self._export_period_pdf)
        menu.addAction("Bločky – Excel (.xlsx)", lambda: self._export_period_table("xlsx"))
        menu.addAction("Bločky – CSV", lambda: self._export_period_table("csv"))
        menu.addSeparator()
        menu.addAction("Súhrn kategórií – PDF", self._export_category_summary_pdf)
        self._vat_summary_action = menu.addAction(
            "DPH podklad – PDF", self._export_vat_summary_pdf
        )
        return menu

    def _current_receipts(self) -> Optional[List[Receipt]]:
        """Fetch receipts for the active profile honouring the current filters."""
        if not self._active_profile:
            return None
        receipts = self._db.get_receipts(
            self._active_profile.id,
            year=self.year_combo.currentData(),
            month=self.month_combo.currentData(),
            category_id=self.category_filter.currentData(),
            vendor_id=self.vendor_filter.currentData(),
            search=self.search_edit.text(),
        )
        if not receipts:
            QMessageBox.information(self, "Export", "Žiadne bločky na export.")
            return None
        return receipts

    def _period_label(self) -> str:
        """Human-readable label for the active year/month filter (for reports)."""
        year = self.year_combo.currentData()
        month = self.month_combo.currentData()
        month_name = c.MONTHS_SK[month - 1] if month else ""
        if year and month:
            return f"{month_name} {year}"
        if year:
            return str(year)
        if month:
            return f"{month_name} (všetky roky)"
        return ""

    def _vendor_label(self) -> str:
        """Selected vendor's display name for reports (empty when 'all')."""
        if self.vendor_filter.currentData():
            return self.vendor_filter.currentText()
        return ""

    def _save_path(self, caption: str, default_name: str, filt: str) -> Optional[Path]:
        """Show a save dialog and return the chosen path (or None)."""
        path, _ = QFileDialog.getSaveFileName(self, caption, default_name, filt)
        return Path(path) if path else None

    @staticmethod
    def _open_file(path: Path) -> None:
        """Open the produced file with the OS default handler."""
        open_path(path)

    def _export_period_table(self, fmt: str) -> None:
        """Export the current receipt list to CSV or XLSX."""
        receipts = self._current_receipts()
        if receipts is None:
            return
        ext, filt = ("xlsx", "Excel (*.xlsx)") if fmt == "xlsx" else ("csv", "CSV (*.csv)")
        dest = self._save_path("Exportovať bločky", f"blocky.{ext}", filt)
        if dest is None:
            return
        try:
            if fmt == "xlsx":
                excel_export.export_period_xlsx(dest, receipts, self._active_profile)
            else:
                excel_export.export_period_csv(dest, receipts, self._active_profile)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Chyba exportu", str(exc))
            return
        QMessageBox.information(self, "Export", f"Uložené: {dest}")

    def _export_period_pdf(self) -> None:
        """Export the current receipt list as a PDF report."""
        receipts = self._current_receipts()
        if receipts is None:
            return
        dest = self._save_path("Exportovať bločky (PDF)", "blocky.pdf", "PDF (*.pdf)")
        if dest is None:
            return
        try:
            pdf_export.export_period_pdf(
                dest, receipts, self._active_profile,
                self._period_label(), self._vendor_label(),
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Chyba exportu", str(exc))
            return
        self._open_file(dest)

    def _export_category_summary_pdf(self) -> None:
        """Export per-category totals for the active period as a PDF."""
        if not self._active_profile:
            return
        totals = self._db.get_category_totals(
            self._active_profile.id,
            year=self.year_combo.currentData(),
            month=self.month_combo.currentData(),
            vendor_id=self.vendor_filter.currentData(),
        )
        if not totals:
            QMessageBox.information(self, "Export", "Žiadne dáta na export.")
            return
        dest = self._save_path("Súhrn kategórií (PDF)", "suhrn_kategorii.pdf", "PDF (*.pdf)")
        if dest is None:
            return
        try:
            pdf_export.export_category_summary_pdf(
                dest, totals, self._active_profile,
                self._period_label(), self._vendor_label(),
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Chyba exportu", str(exc))
            return
        self._open_file(dest)

    def _export_vat_summary_pdf(self) -> None:
        """Export a VAT recap per rate for the active period (firm mode)."""
        if not self._active_profile:
            return
        if not self._active_profile.vat_enabled:
            QMessageBox.information(
                self, "DPH podklad",
                "DPH podklad je dostupný len pre firemný profil (s DPH).",
            )
            return
        receipts = self._current_receipts()
        if receipts is None:
            return
        dest = self._save_path("DPH podklad (PDF)", "dph_podklad.pdf", "PDF (*.pdf)")
        if dest is None:
            return
        try:
            pdf_export.export_vat_summary_pdf(
                dest, receipts, self._active_profile,
                self._period_label(), self._vendor_label(),
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Chyba exportu", str(exc))
            return
        self._open_file(dest)

    def _backup_db(self) -> None:
        last_dir = self._db.get_setting("db_backup_dir", str(Path.home()))
        folder = QFileDialog.getExistingDirectory(self, "Vyberte priečinok zálohy", last_dir)
        if not folder:
            return
        try:
            dest = self._db.backup_database(Path(folder))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Chyba zálohy", str(exc))
            return
        self._db.set_setting("db_backup_dir", folder)
        QMessageBox.information(self, "Záloha", f"Záloha vytvorená:\n{dest}")

    def _open_security(self) -> None:
        """Open the optional password-protection settings."""
        from ui.security_dialog import SecurityDialog

        SecurityDialog(self._db, self).exec()

    def _restore_db(self) -> None:
        """Restore the DB from a chosen backup file (with safety auto-backup)."""
        if self._resync_thread is not None:
            QMessageBox.information(
                self, "Obnova databázy",
                "Prebieha aktualizácia neúplných bločkov. "
                "Skúste to znova o chvíľu.",
            )
            return
        last_dir = self._db.get_setting("db_backup_dir", str(Path.home()))
        src, _ = QFileDialog.getOpenFileName(
            self, "Vyberte zálohu na obnovenie", last_dir,
            "SQLite databáza (*.db);;Všetky súbory (*)",
        )
        if not src:
            return
        reply = QMessageBox.warning(
            self, "Obnoviť databázu",
            "Týmto sa NAHRADIA všetky súčasné dáta databázou zo zálohy.\n\n"
            "Súčasná databáza sa pred obnovou automaticky zálohuje, takže "
            "krok je vratný.\n\nPokračovať?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            safety = self._db.restore_database(Path(src))
        except Exception as exc:  # noqa: BLE001 — surface validation/IO errors
            QMessageBox.critical(self, "Chyba obnovy", str(exc))
            return
        # Reload the whole UI from the freshly restored database.
        self._active_profile = None
        self._load_profiles()
        QMessageBox.information(
            self, "Obnova databázy",
            f"Databáza bola obnovená.\n\nPredošlá databáza je uložená v:\n{safety}",
        )
