"""Data models for the Archiv_blockov application.

All identifiers are in English; GUI strings live in the UI layer (Slovak).
Monetary values are floats; always ``round(x, 2)`` before summing/exporting.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional


@dataclass
class Profile:
    """An archiving profile (e.g. household or firm)."""

    id: Optional[int]
    name: str
    kind: str = "household"          # 'household' | 'firm'
    vat_enabled: bool = False
    ico: str = ""
    dic: str = ""

    def display_name(self) -> str:
        """Return the profile name for UI lists."""
        return self.name


@dataclass
class Category:
    """A user-defined category, scoped to a profile."""

    id: Optional[int]
    profile_id: int
    name: str
    color: str = "#4a9eff"


@dataclass
class Vendor:
    """A vendor (predajca), auto-detected from the QR / IČO lookup."""

    id: Optional[int]
    profile_id: int
    ico: str = ""
    dic: str = ""
    name: str = ""
    address: str = ""
    default_category_id: Optional[int] = None

    def display_name(self) -> str:
        """Return vendor name for UI dropdowns."""
        return self.name or self.ico or "—"


@dataclass
class VatBreakdown:
    """VAT breakdown extracted from a QR receipt."""

    base_0: float = 0.0
    base_5: float = 0.0
    tax_5: float = 0.0
    base_19: float = 0.0
    tax_19: float = 0.0
    base_23: float = 0.0
    tax_23: float = 0.0
    zaokruhlenie: float = 0.0
    celkom: float = 0.0


@dataclass
class ReceiptItem:
    """A single line item of a receipt."""

    id: Optional[int]
    receipt_id: Optional[int]
    name: str = ""
    quantity: float = 1.0
    unit_price: float = 0.0
    price: float = 0.0              # line total incl. VAT
    vat_rate: float = 0.0
    category_id: Optional[int] = None
    is_synthetic: bool = False


@dataclass
class Receipt:
    """One archived receipt (bloček), filed by its QR date."""

    id: Optional[int]
    profile_id: int
    vendor_id: Optional[int]
    datum: Optional[date]
    base_0: float = 0.0
    base_5: float = 0.0
    tax_5: float = 0.0
    base_19: float = 0.0
    tax_19: float = 0.0
    base_23: float = 0.0
    tax_23: float = 0.0
    zaokruhlenie: float = 0.0
    celkom: float = 0.0
    platba: str = "hotovost"
    popis: str = ""
    qr_raw: str = ""
    default_category_id: Optional[int] = None
    account_year: int = 0
    account_month: int = 0
    data_complete: bool = True
    sync_attempts: int = 0
    last_sync_attempt: Optional[str] = None
    sync_error: Optional[str] = None
    api_data: Optional[str] = None

    # Convenience fields populated by joins (not stored directly):
    vendor_name: str = ""
    category_name: str = ""
    category_color: str = ""
    category_count: int = 0        # distinct categories among items (for "zmiešané")

    def datum_display(self) -> str:
        """Return date in Slovak display format DD.MM.YYYY."""
        return self.datum.strftime("%d.%m.%Y") if self.datum else ""

    def period_display(self) -> str:
        """Return accounting period as MM/YYYY string."""
        if self.account_year and self.account_month:
            return f"{self.account_month:02d}/{self.account_year}"
        return ""


@dataclass
class ItemAlias:
    """Maps a display name (e.g. 'Chlieb') to a LIKE pattern over item names."""

    id: Optional[int]
    profile_id: int
    display_name: str
    pattern: str


@dataclass
class ParsedReceipt:
    """Result of parsing an e-kasa QR code."""

    qr_raw: str
    ico: str = ""
    dic: str = ""
    nazov: str = ""
    adresa: str = ""
    datum: Optional[date] = None
    vat: VatBreakdown = field(default_factory=VatBreakdown)
    platba: str = "hotovost"
    items: List[ReceiptItem] = field(default_factory=list)
    is_offline: bool = False
    data_complete: bool = True
    parse_error: Optional[str] = None
    api_data: Optional[str] = None
