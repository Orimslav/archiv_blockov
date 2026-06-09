"""USB QR scanner input handling.

A hidden ``QLineEdit`` permanently holds focus as the scanner buffer. The
scanner types into it and ``returnPressed`` fires the ``on_scan`` callback.
An application-level event filter reclaims focus to the buffer shortly after
clicks on non-text widgets, mirroring Scan_blocky's approach.
"""

from typing import Callable

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
    QWidget,
)

# Widget types that legitimately keep focus while the user types manually.
_TEXT_WIDGETS = (QLineEdit, QPlainTextEdit, QTextEdit, QComboBox)


class ScannerInput(QObject):
    """Manages a hidden scanner buffer and focus reclaim behaviour."""

    # Emitted when scan readiness changes (buffer gains/loses keyboard focus).
    ready_changed = Signal(bool)

    def __init__(self, parent: QWidget, on_scan: Callable[[str], None]) -> None:
        super().__init__(parent)
        self._on_scan = on_scan
        self._suspended = False
        self._buffer = QLineEdit(parent)
        self._buffer.setObjectName("ScannerBuffer")
        self._buffer.setFixedSize(1, 1)
        self._buffer.move(-100, -100)  # off-screen
        self._buffer.returnPressed.connect(self._handle_return)
        self._buffer.setFocus()

    def install(self, app: QApplication) -> None:
        """Install the application-level focus-reclaim event filter."""
        app.installEventFilter(self)

    def set_suspended(self, suspended: bool) -> None:
        """Pause/resume focus reclaim (used while a modal scan window owns input).

        While suspended the main buffer neither reclaims focus nor reports
        readiness, so another window (e.g. the bulk-scan dialog) can own the
        scanner. Resuming returns focus to the buffer.
        """
        self._suspended = suspended
        if not suspended:
            self.reclaim_focus()

    def reclaim_focus(self) -> None:
        """Move focus back to the scanner buffer."""
        self._buffer.setFocus()

    def is_ready(self) -> bool:
        """Return True if the scanner buffer currently holds keyboard focus."""
        return self._buffer.hasFocus()

    def _handle_return(self) -> None:
        """Emit the scanned QR string and clear the buffer."""
        qr = self._buffer.text().strip()
        self._buffer.clear()
        if qr:
            self._on_scan(qr)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Reclaim focus after clicks and track scan-readiness via focus."""
        if self._suspended:
            return False
        event_type = event.type()
        if event_type == QEvent.Type.MouseButtonRelease:
            focused = QApplication.focusWidget()
            if not isinstance(focused, _TEXT_WIDGETS):
                QTimer.singleShot(50, self.reclaim_focus)
        elif obj is self._buffer:
            if event_type == QEvent.Type.FocusIn:
                self.ready_changed.emit(True)
            elif event_type == QEvent.Type.FocusOut:
                self.ready_changed.emit(False)
        return False
