"""PDF export (ReportLab, A4).

Provides faithful single-receipt copies plus period/summary reports:

* ``export_receipt_detail_pdf``    — one receipt as a printable document
* ``export_period_pdf``            — receipt list for a period/filter
* ``export_category_summary_pdf``  — per-category totals (item-level sums)
* ``export_item_report_pdf``       — item consumption report (per month)
* ``export_vat_summary_pdf``       — VAT recap per rate (firm mode)

Slovak diacritics are handled by registering a TrueType font found in the
platform's font directories (Windows / Linux / macOS), falling back to
Helvetica.
"""

import io
import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont, TTFError
from reportlab.platypus import (
    HRFlowable,
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from models.models import Profile, Receipt, ReceiptItem

logger = logging.getLogger(__name__)

_MONTHS_SK = [
    "", "Január", "Február", "Marec", "Apríl", "Máj", "Jún",
    "Júl", "August", "September", "Október", "November", "December",
]

_FONT_NAME = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"
_FONT_REGISTERED = False

# Each candidate lists the regular/bold filename variants to try. Windows and
# Linux ship the same families under different file names and casing (Linux is
# case-sensitive), so we list every spelling we expect to find.
_FONT_CANDIDATES = [
    ("DejaVu", "DejaVuBold",
     ("dejavusans.ttf", "DejaVuSans.ttf"),
     ("dejavusans-bold.ttf", "DejaVuSans-Bold.ttf")),
    ("Liberation", "LiberationBold",
     ("liberationsans-regular.ttf", "LiberationSans-Regular.ttf"),
     ("liberationsans-bold.ttf", "LiberationSans-Bold.ttf")),
    ("Calibri", "CalibriBold",
     ("calibri.ttf",), ("calibrib.ttf",)),
    ("Arial", "ArialBold",
     ("arial.ttf",), ("arialbd.ttf",)),
    ("Tahoma", "TahomaBold",
     ("tahoma.ttf",), ("tahomabd.ttf",)),
    ("Verdana", "VerdanaBold",
     ("verdana.ttf",), ("verdanab.ttf",)),
]

# Font directories per platform; missing dirs are skipped silently.
_FONT_DIRS = [
    Path("C:/Windows/Fonts"),                         # Windows
    Path("/usr/share/fonts"),                          # Linux (system)
    Path("/usr/local/share/fonts"),                    # Linux (local)
    Path.home() / ".fonts",                            # Linux (user, legacy)
    Path.home() / ".local/share/fonts",                # Linux (user, XDG)
    Path("/Library/Fonts"),                            # macOS
    Path("/System/Library/Fonts"),                     # macOS
    Path.home() / "Library/Fonts",                     # macOS (user)
]


def _find_font_file(names: Sequence[str]) -> Optional[Path]:
    """Locate the first matching font file across the known font directories.

    Tries a direct match in each directory first, then a recursive search
    (Linux nests fonts in subfolders such as ``truetype/dejavu``).
    """
    for fonts_dir in _FONT_DIRS:
        if not fonts_dir.is_dir():
            continue
        for name in names:
            direct = fonts_dir / name
            if direct.exists():
                return direct
        for name in names:
            match = next(fonts_dir.rglob(name), None)
            if match is not None:
                return match
    return None


def _register_font() -> None:
    """Register a Slovak-capable TTF once; keep Helvetica as fallback."""
    global _FONT_NAME, _FONT_BOLD, _FONT_REGISTERED
    if _FONT_REGISTERED:
        return
    _FONT_REGISTERED = True
    for regular, bold, reg_files, bold_files in _FONT_CANDIDATES:
        reg_path = _find_font_file(reg_files)
        if reg_path is None:
            continue
        try:
            pdfmetrics.registerFont(TTFont(regular, str(reg_path)))
            bold_path = _find_font_file(bold_files)
            if bold_path is not None:
                pdfmetrics.registerFont(TTFont(bold, str(bold_path)))
                _FONT_NAME, _FONT_BOLD = regular, bold
            else:
                _FONT_NAME, _FONT_BOLD = regular, regular
            return
        except (OSError, TTFError):
            continue


def _money(value) -> str:
    """Format a monetary value with two decimals and a Slovak decimal comma."""
    return f"{value or 0:.2f}".replace(".", ",")


def _qty(value) -> str:
    """Format a quantity/rate compactly with a Slovak decimal comma."""
    return f"{value or 0:g}".replace(".", ",")


def _pct(value) -> str:
    """Format a percentage with one decimal and a Slovak decimal comma."""
    return f"{value or 0:.1f}".replace(".", ",")


def export_receipt_detail_pdf(
    receipt: Receipt,
    items: List[ReceiptItem],
    organization: Dict,
    identifiers: Dict,
    dest: Optional[Path] = None,
) -> Path:
    """Render a single receipt as a printable A4 PDF and return its path."""
    _register_font()

    if dest is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = Path(tempfile.gettempdir()) / f"doklad_{receipt.id}_{stamp}.pdf"
    dest = Path(dest)

    styles = _styles()
    doc = SimpleDocTemplate(
        str(dest), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Doklad {receipt.id}",
    )
    story: list = []

    story.append(Paragraph("Pokladničný doklad", styles["title"]))
    story.append(Spacer(1, 6))

    # Vendor block on the left, QR code (from the original QR string) on the right.
    org_name = organization.get("name") or receipt.vendor_name or "—"
    vendor_flow: list = [Paragraph(_esc(org_name), styles["vendor"])]
    for line in _vendor_lines(organization):
        vendor_flow.append(Paragraph(_esc(line), styles["normal"]))

    qr_image = _qr_image(identifiers.get("qr_raw") or identifiers.get("receiptId"))
    if qr_image is not None:
        head = Table([[vendor_flow, qr_image]], colWidths=[None, 34 * mm])
        head.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(head)
    else:
        story.extend(vendor_flow)
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", color=colors.black))
    story.append(Spacer(1, 6))

    # Receipt meta
    meta = [
        ("Číslo dokladu", identifiers.get("receiptNumber")),
        ("Dátum a čas", identifiers.get("issueDate") or receipt.datum_display()),
        ("Pokladnica", identifiers.get("cashRegisterCode")),
        ("Platba", "Karta" if receipt.platba == "karta" else "Hotovosť"),
    ]
    for label, value in meta:
        if value:
            story.append(Paragraph(f"<b>{label}:</b> {_esc(str(value))}", styles["normal"]))
    story.append(Spacer(1, 8))

    # Items table
    story.append(Paragraph("Položky", styles["heading"]))
    story.append(_items_table(items, styles))
    story.append(Spacer(1, 8))

    # VAT summary
    vat_rows = _vat_rows(receipt)
    if vat_rows:
        story.append(Paragraph("DPH súhrn", styles["heading"]))
        for line in vat_rows:
            story.append(Paragraph(_esc(line), styles["normal"]))
        story.append(Spacer(1, 4))

    story.append(Paragraph(f"<b>SPOLU: {_money(receipt.celkom)} €</b>", styles["total"]))
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", color=colors.black))
    story.append(Spacer(1, 6))

    # Identifiers
    story.append(Paragraph("Identifikátory", styles["heading"]))
    for label, key in (("UID / receiptId", "receiptId"), ("OKP", "okp"),
                       ("PKP", "pkp"), ("QR", "qr_raw")):
        value = identifiers.get(key)
        if value:
            story.append(Paragraph(f"<b>{label}:</b> {_esc(str(value))}", styles["mono"]))

    doc.build(story)
    logger.info(f"PDF dokladu vytvorené: {dest}")
    return dest


def export_period_pdf(
    dest: Path,
    receipts: Sequence[Receipt],
    profile: Profile,
    period_label: str = "",
    vendor_label: str = "",
) -> Path:
    """Render the receipt list for a period/filter as an A4 PDF.

    Firm profiles (``vat_enabled``) use landscape with VAT columns; only a
    rate's columns appear when some receipt carries a non-zero value (the
    0 % base column is always shown). Household profiles use a compact
    portrait layout. A SPOLU / Hotovosť / Karta summary closes the table.
    """
    _register_font()
    dest = Path(dest)
    styles = _styles()
    vat = profile.vat_enabled

    doc = SimpleDocTemplate(
        str(dest),
        pagesize=landscape(A4) if vat else A4,
        leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm,
        title="Bločky",
    )
    story: list = [
        Paragraph("Prehľad bločkov", styles["title"]),
        Paragraph(_esc(_report_subtitle(profile, period_label, vendor_label)), styles["normal"]),
        Spacer(1, 8),
    ]
    story.append(_period_table(receipts, vat, styles))
    doc.build(story)
    logger.info(f"PDF prehľad bločkov vytvorené: {dest}")
    return dest


def export_category_summary_pdf(
    dest: Path,
    totals: Sequence[Tuple[str, str, float]],
    profile: Profile,
    period_label: str = "",
    vendor_label: str = "",
) -> Path:
    """Render per-category totals (name, color, sum) with a grand total."""
    _register_font()
    dest = Path(dest)
    styles = _styles()

    grand = round(sum(t for _, _, t in totals), 2)
    header = ["Kategória", "Suma (€)", "Podiel"]
    data = [[Paragraph(_esc(h), styles["cellb"]) for h in header]]
    for name, color, total in totals:
        share = (total / grand * 100) if grand else 0.0
        data.append([
            _chip_cell(name, color, styles),
            Paragraph(_money(total), styles["cell"]),
            Paragraph(f"{_pct(share)} %", styles["cell"]),
        ])
    data.append([
        Paragraph("SPOLU", styles["cellb"]),
        Paragraph(_money(grand), styles["cellb"]),
        Paragraph("100,0 %", styles["cellb"]),
    ])
    table = Table(data, colWidths=[None, 32 * mm, 26 * mm])
    table.setStyle(_grid_style(total_row=True))

    story = [
        Paragraph("Súhrn podľa kategórií", styles["title"]),
        Paragraph(_esc(_report_subtitle(profile, period_label, vendor_label)), styles["normal"]),
        Spacer(1, 8),
        table,
    ]
    doc = SimpleDocTemplate(
        str(dest), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm, title="Súhrn kategórií",
    )
    doc.build(story)
    logger.info(f"PDF súhrn kategórií vytvorené: {dest}")
    return dest


def export_item_report_pdf(
    dest: Path,
    item_label: str,
    monthly: Sequence[Tuple[int, float, float]],
    profile: Profile,
    year: Optional[int] = None,
) -> Path:
    """Render a per-month consumption report (month, quantity, spend)."""
    _register_font()
    dest = Path(dest)
    styles = _styles()

    total_qty = round(sum(q for _, q, _ in monthly), 3)
    total_spend = round(sum(s for _, _, s in monthly), 2)
    header = ["Mesiac", "Množstvo", "Suma (€)"]
    data = [[Paragraph(_esc(h), styles["cellb"]) for h in header]]
    for month, qty, spend in monthly:
        label = _MONTHS_SK[month] if 1 <= month <= 12 else "—"
        data.append([
            Paragraph(_esc(label), styles["cell"]),
            Paragraph(_qty(qty), styles["cell"]),
            Paragraph(_money(spend), styles["cell"]),
        ])
    data.append([
        Paragraph("SPOLU", styles["cellb"]),
        Paragraph(_qty(total_qty), styles["cellb"]),
        Paragraph(_money(total_spend), styles["cellb"]),
    ])
    table = Table(data, colWidths=[None, 32 * mm, 32 * mm])
    table.setStyle(_grid_style(total_row=True))

    scope = f"Rok {year}" if year else "Všetky obdobia"
    story = [
        Paragraph(f"Spotreba: {_esc(item_label)}", styles["title"]),
        Paragraph(_esc(f"Profil: {profile.name}   ·   {scope}"), styles["normal"]),
        Spacer(1, 8),
        table,
    ]
    doc = SimpleDocTemplate(
        str(dest), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm, title="Spotreba položky",
    )
    doc.build(story)
    logger.info(f"PDF report položky vytvorené: {dest}")
    return dest


def export_vat_summary_pdf(
    dest: Path,
    receipts: Sequence[Receipt],
    profile: Profile,
    period_label: str = "",
    vendor_label: str = "",
) -> Path:
    """Render a VAT recap per rate (base + tax) for the period (firm mode)."""
    _register_font()
    dest = Path(dest)
    styles = _styles()

    rates = [
        ("0 %", lambda r: (r.base_0, 0.0)),
        ("5 %", lambda r: (r.base_5, r.tax_5)),
        ("19 %", lambda r: (r.base_19, r.tax_19)),
        ("23 %", lambda r: (r.base_23, r.tax_23)),
    ]
    header = ["Sadzba DPH", "Základ (€)", "Daň (€)", "Spolu (€)"]
    data = [[Paragraph(_esc(h), styles["cellb"]) for h in header]]
    sum_base = sum_tax = 0.0
    for label, getter in rates:
        base = round(sum(getter(r)[0] or 0 for r in receipts), 2)
        tax = round(sum(getter(r)[1] or 0 for r in receipts), 2)
        if not base and not tax and label != "0 %":
            continue
        sum_base += base
        sum_tax += tax
        data.append([
            Paragraph(_esc(label), styles["cell"]),
            Paragraph(_money(base), styles["cell"]),
            Paragraph(_money(tax), styles["cell"]),
            Paragraph(_money(base + tax), styles["cell"]),
        ])
    rounding = round(sum(r.zaokruhlenie or 0 for r in receipts), 2)
    grand = round(sum(r.celkom or 0 for r in receipts), 2)
    data.append([
        Paragraph("SPOLU", styles["cellb"]),
        Paragraph(_money(round(sum_base, 2)), styles["cellb"]),
        Paragraph(_money(round(sum_tax, 2)), styles["cellb"]),
        Paragraph(_money(round(sum_base + sum_tax, 2)), styles["cellb"]),
    ])
    table = Table(data, colWidths=[None, 32 * mm, 32 * mm, 32 * mm])
    table.setStyle(_grid_style(total_row=True))

    story = [
        Paragraph("DPH podklad", styles["title"]),
        Paragraph(_esc(_report_subtitle(profile, period_label, vendor_label)), styles["normal"]),
        Spacer(1, 8),
        table,
        Spacer(1, 8),
        Paragraph(f"Zaokrúhlenie: {_money(rounding)} €", styles["normal"]),
        Paragraph(f"<b>Celkom k úhrade: {_money(grand)} €</b>", styles["total"]),
    ]
    doc = SimpleDocTemplate(
        str(dest), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm, title="DPH podklad",
    )
    doc.build(story)
    logger.info(f"PDF DPH podklad vytvorené: {dest}")
    return dest


# ------------------------------------------------------------------ helpers

def _report_subtitle(profile: Profile, period_label: str, vendor_label: str = "") -> str:
    """Build the 'Profil: … · Obdobie: … · Predajca: …' subtitle for reports."""
    parts = [f"Profil: {profile.name}"]
    parts.append(f"Obdobie: {period_label}" if period_label else "Obdobie: všetko")
    if vendor_label:
        parts.append(f"Predajca: {vendor_label}")
    parts.append(f"Vytvorené: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    return "   ·   ".join(parts)


def _period_table(receipts: Sequence[Receipt], vat: bool, styles: Dict) -> Table:
    """Build the period receipt table with VAT-aware columns + totals."""
    # Decide which VAT-rate columns carry data (gating rules).
    def any_nonzero(getter) -> bool:
        return any(round(getter(r) or 0, 2) for r in receipts)

    # Column spec: (label, getter, align, sum_field). sum_field names the
    # Receipt attribute summed into the SPOLU row (None = not summed).
    cols: List[Tuple[str, object, str, Optional[str]]] = [
        ("Dátum", lambda r: r.datum_display(), "left", None),
        ("Predajca", lambda r: r.vendor_name or "—", "left", None),
        ("Kategória", lambda r: r.category_name or "Nezaradené", "left", None),
    ]
    if vat:
        cols.append(("0% Z", lambda r: _money(r.base_0), "right", "base_0"))
        if any_nonzero(lambda r: r.base_5) or any_nonzero(lambda r: r.tax_5):
            cols.append(("5% Z", lambda r: _money(r.base_5), "right", "base_5"))
            cols.append(("5% D", lambda r: _money(r.tax_5), "right", "tax_5"))
        if any_nonzero(lambda r: r.base_19) or any_nonzero(lambda r: r.tax_19):
            cols.append(("19% Z", lambda r: _money(r.base_19), "right", "base_19"))
            cols.append(("19% D", lambda r: _money(r.tax_19), "right", "tax_19"))
        if any_nonzero(lambda r: r.base_23) or any_nonzero(lambda r: r.tax_23):
            cols.append(("23% Z", lambda r: _money(r.base_23), "right", "base_23"))
            cols.append(("23% D", lambda r: _money(r.tax_23), "right", "tax_23"))
        if any_nonzero(lambda r: r.zaokruhlenie):
            cols.append(("Zaokr.", lambda r: _money(r.zaokruhlenie), "right", "zaokruhlenie"))
    cols.append(("Celkom", lambda r: _money(r.celkom), "right", "celkom"))
    cols.append(("Platba", lambda r: "Karta" if r.platba == "karta" else "Hotovosť", "left", None))
    cols.append(("Popis", lambda r: r.popis or "", "left", None))

    header = [Paragraph(_esc(label), styles["cellb"]) for label, _, _, _ in cols]
    data = [header]
    for r in receipts:
        data.append([
            Paragraph(_esc(str(getter(r))), styles["cell"]) for _, getter, _, _ in cols
        ])

    # SPOLU: sum every numeric column (VAT breakdown + Celkom).
    spolu_row = [Paragraph("", styles["cell"]) for _ in cols]
    spolu_row[0] = Paragraph("SPOLU", styles["cellb"])
    for i, (_, _, _, field) in enumerate(cols):
        if field:
            s = round(sum(getattr(r, field, 0) or 0 for r in receipts), 2)
            spolu_row[i] = Paragraph(_money(s), styles["cellb"])
    data.append(spolu_row)

    # Hotovosť / Karta: the Celkom total split by payment method.
    celkom_idx = next(i for i, col in enumerate(cols) if col[0] == "Celkom")
    total_cash = round(sum(r.celkom or 0 for r in receipts if r.platba != "karta"), 2)
    total_card = round(sum(r.celkom or 0 for r in receipts if r.platba == "karta"), 2)
    for label, value in (("Hotovosť", total_cash), ("Karta", total_card)):
        row = [Paragraph("", styles["cell"]) for _ in cols]
        row[0] = Paragraph(_esc(label), styles["cellb"])
        row[celkom_idx] = Paragraph(_money(value), styles["cellb"])
        data.append(row)

    table = Table(data, repeatRows=1)
    # Pure black-and-white: no background fills, black grid, header and totals
    # set off by bold lines instead of colour.
    style = [
        ("FONTNAME", (0, 0), (-1, -1), _FONT_NAME),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEABOVE", (0, len(receipts) + 1), (-1, len(receipts) + 1), 1.0, colors.black),
    ]
    for i, (_, _, align, _) in enumerate(cols):
        style.append(("ALIGN", (i, 0), (i, -1), "RIGHT" if align == "right" else "LEFT"))
    table.setStyle(TableStyle(style))
    return table


def _grid_style(total_row: bool = False) -> TableStyle:
    """Black-and-white grid style for summary tables (no fills, bold lines)."""
    style = [
        ("FONTNAME", (0, 0), (-1, -1), _FONT_NAME),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if total_row:
        style.append(("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black))
    return TableStyle(style)


def _chip_cell(name: str, color: str, styles: Dict) -> Paragraph:
    """Render the category name as a plain cell (black-and-white, no swatch).

    The ``color`` argument is kept for call-site compatibility but ignored so
    the report stays purely black-and-white for printing.
    """
    return Paragraph(_esc(name), styles["cell"])


def _styles() -> Dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["Normal"]
    return {
        "title": ParagraphStyle("title", parent=base, fontName=_FONT_BOLD,
                                fontSize=16, spaceAfter=10),
        "vendor": ParagraphStyle("vendor", parent=base, fontName=_FONT_BOLD,
                                 fontSize=12),
        "heading": ParagraphStyle("heading", parent=base, fontName=_FONT_BOLD,
                                  fontSize=11, spaceAfter=4),
        "normal": ParagraphStyle("normal", parent=base, fontName=_FONT_NAME,
                                 fontSize=10, leading=14),
        "mono": ParagraphStyle("mono", parent=base, fontName=_FONT_NAME,
                               fontSize=9, leading=12),
        "total": ParagraphStyle("total", parent=base, fontName=_FONT_BOLD,
                                fontSize=12),
        "cell": ParagraphStyle("cell", parent=base, fontName=_FONT_NAME,
                               fontSize=9, leading=11),
        "cellb": ParagraphStyle("cellb", parent=base, fontName=_FONT_BOLD,
                                fontSize=9, leading=11),
    }


def _qr_image(data: Optional[str], size_mm: float = 32) -> Optional[Image]:
    """Render the QR string to a ReportLab Image, or None if unavailable."""
    if not data:
        return None
    try:
        import qrcode

        qr = qrcode.QRCode(border=1, box_size=10)
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        return Image(buffer, width=size_mm * mm, height=size_mm * mm)
    except Exception as exc:  # noqa: BLE001 — QR is optional, never block export
        logger.warning(f"QR kód sa nepodarilo vygenerovať: {exc}")
        return None


def _vendor_lines(org: Dict) -> List[str]:
    lines = []
    address = " ".join(filter(None, [
        org.get("streetName") or "",
        str(org.get("buildingNumber")
            or org.get("propertyRegistrationNumber") or ""),
    ])).strip()
    city = " ".join(filter(None, [
        str(org.get("postalCode") or ""),
        org.get("municipality") or "",
    ])).strip()
    full_addr = ", ".join(p for p in (address, city, org.get("country") or "") if p)
    if full_addr:
        lines.append(full_addr)
    ids = []
    if org.get("ico"):
        ids.append(f"IČO: {org['ico']}")
    if org.get("dic"):
        ids.append(f"DIČ: {org['dic']}")
    if org.get("icDph") or org.get("vatId"):
        ids.append(f"IČ DPH: {org.get('icDph') or org.get('vatId')}")
    if ids:
        lines.append("   ".join(ids))
    return lines


def _items_table(items: List[ReceiptItem], styles: Dict) -> Table:
    header = ["Názov", "Množ.", "Jedn. cena", "Cena", "DPH %"]
    data = [[Paragraph(_esc(h), styles["cellb"]) for h in header]]
    for it in items:
        data.append([
            Paragraph(_esc(it.name), styles["cell"]),
            Paragraph(_qty(it.quantity), styles["cell"]),
            Paragraph(_money(it.unit_price), styles["cell"]),
            Paragraph(_money(it.price), styles["cell"]),
            Paragraph(_qty(it.vat_rate), styles["cell"]),
        ])
    table = Table(data, colWidths=[None, 18 * mm, 24 * mm, 24 * mm, 16 * mm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _FONT_NAME),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _vat_rows(receipt: Receipt) -> List[str]:
    rows = []
    for label, base, tax in (
        ("0 %", receipt.base_0, 0.0),
        ("5 %", receipt.base_5, receipt.tax_5),
        ("19 %", receipt.base_19, receipt.tax_19),
        ("23 %", receipt.base_23, receipt.tax_23),
    ):
        if base or tax:
            rows.append(f"Sadzba {label}: základ {_money(base)} € · daň {_money(tax)} €")
    if receipt.zaokruhlenie:
        rows.append(f"Zaokrúhlenie: {_money(receipt.zaokruhlenie)} €")
    return rows


def _esc(text: str) -> str:
    """Escape characters special to ReportLab paragraph markup."""
    return (str(text).replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;"))
