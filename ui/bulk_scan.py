"""BulkScanDialog — scan many receipts in a row without per-receipt prompts.

While this window is open the main scanner is suspended and this dialog owns
the input: it carries its own hidden scanner buffer, and each scanned QR is
forwarded (via the ``scanned`` signal) to the main window, which saves it
silently using the vendor's learned default category. A large counter and a
running list give live feedback; closing the window ends bulk mode.
"""

from typing import Optional

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui import constants as c


class BulkScanDialog(QDialog):
    """Modeless window capturing a stream of scans for silent bulk saving."""

    # Emitted with the raw QR string each time a receipt is scanned.
    scanned = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._count = 0

        self.setWindowTitle("Hromadné skenovanie")
        self.setMinimumSize(560, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        info = QLabel(
            "Skenujte bločky jeden za druhým — každý sa uloží automaticky "
            "s kategóriou podľa predajcu (inak „Nezaradené“). Kategórie a "
            "podrobnosti môžete upraviť neskôr. Okno zatvorte, keď skončíte."
        )
        info.setWordWrap(True)

        self.counter = QLabel("0")
        self.counter.setObjectName("BulkCounter")
        self.counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.counter.setStyleSheet(
            f"font-size: 64px; font-weight: bold; color: {c.CLR_ACCENT};"
        )
        caption = QLabel("naskenovaných bločkov")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caption.setStyleSheet(f"color: {c.CLR_TEXT_SECONDARY};")

        self.status = QLabel("● Pripravený na sken…")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setStyleSheet(f"color: {c.CLR_SUCCESS}; font-weight: bold;")

        self.list = QListWidget()

        # Hidden buffer the USB scanner types into (this window owns input).
        self._buffer = QLineEdit(self)
        self._buffer.setObjectName("BulkScannerBuffer")
        self._buffer.setFixedSize(1, 1)
        self._buffer.move(-100, -100)  # off-screen
        self._buffer.returnPressed.connect(self._handle_return)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        btn_done = QPushButton("Hotovo")
        # Don't let the scanner's terminating Enter trigger this button as the
        # dialog's default — otherwise the first scan would close the window.
        btn_done.setAutoDefault(False)
        btn_done.setDefault(False)
        btn_done.clicked.connect(self.accept)
        buttons.addWidget(btn_done)

        layout.addWidget(info)
        layout.addWidget(self.counter)
        layout.addWidget(caption)
        layout.addWidget(self.status)
        layout.addWidget(self.list, 1)
        layout.addLayout(buttons)

    # ------------------------------------------------------------ focus / input

    def showEvent(self, event: QEvent) -> None:  # noqa: N802 — Qt override
        """Grab scanner focus and watch clicks so the buffer stays focused."""
        super().showEvent(event)
        QApplication.instance().installEventFilter(self)
        self._buffer.setFocus()

    def hideEvent(self, event: QEvent) -> None:  # noqa: N802 — Qt override
        """Stop watching clicks once the window is hidden (close or accept)."""
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().hideEvent(event)

    def reclaim_focus(self) -> None:
        """Return focus to the hidden scanner buffer."""
        self._buffer.setFocus()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Reclaim buffer focus shortly after any click inside this window."""
        if event.type() == QEvent.Type.MouseButtonRelease:
            QTimer.singleShot(50, self.reclaim_focus)
        return False

    def _handle_return(self) -> None:
        """Emit the scanned QR string and clear the buffer."""
        qr = self._buffer.text().strip()
        self._buffer.clear()
        if qr:
            self.status.setText("⏳ Spracúvam bloček…")
            self.status.setStyleSheet(f"color: {c.CLR_WARNING}; font-weight: bold;")
            self.scanned.emit(qr)

    # ------------------------------------------------------------ result entries

    def add_success(self, text: str) -> None:
        """Record a successfully saved receipt and bump the counter."""
        self._count += 1
        self.counter.setText(str(self._count))
        self._append(f"✓  {text}", c.CLR_SUCCESS)
        self._ready()

    def add_error(self, text: str) -> None:
        """Record a failed / skipped scan without bumping the counter."""
        self._append(f"✗  {text}", c.CLR_ERROR)
        self._ready()

    def _append(self, text: str, color: str) -> None:
        item = QListWidgetItem(text)
        item.setForeground(QColor(color))
        self.list.addItem(item)
        self.list.scrollToBottom()

    def _ready(self) -> None:
        self.status.setText("● Pripravený na sken…")
        self.status.setStyleSheet(f"color: {c.CLR_SUCCESS}; font-weight: bold;")
        self.reclaim_focus()
