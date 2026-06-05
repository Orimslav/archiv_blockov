"""e-kasa QR code parser for Archiv_blockov.

Ported from Scan_blocky/core/ekasa_parser.py and extended with
``extract_items()`` so each parsed receipt carries its full line items
(available for online and uploaded-offline receipts).

Uses the stdlib ``urllib`` for the eKasa API (no extra dependency).
"""

import json
import logging
import time
import urllib.error
import urllib.request
from datetime import date
from typing import List, Optional

from models.models import ParsedReceipt, ReceiptItem, VatBreakdown

logger = logging.getLogger(__name__)

EKASA_URL = "https://ekasa.financnasprava.sk/mdu/api/v1/opd/receipt/find"
EKASA_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def fetch_receipt_detail(qr_raw: str) -> dict:
    """Fetch a raw eKasa API receipt dict by QR string.

    Works for both online (UUID) and offline (OKP:CRC:…) formats.
    Raises ConnectionError or ValueError on failure.
    """
    qr_raw = qr_raw.strip()
    if _is_offline_format(qr_raw):
        return _fetch_offline_from_ekasa(qr_raw)
    return _fetch_from_ekasa(qr_raw)


def parse_qr(qr_raw: str) -> ParsedReceipt:
    """Parse a Slovak e-kasa QR code string into a ``ParsedReceipt``.

    For online receipts (no colon-delimited offline format) sends ``receiptId``
    directly to the API. For offline receipts uses the FIELDS-style lookup.
    Falls back to local QR parsing if the API call fails.
    """
    qr_raw = qr_raw.strip()
    result = ParsedReceipt(qr_raw=qr_raw, vat=VatBreakdown())

    try:
        if _is_offline_format(qr_raw):
            receipt = _fetch_offline_from_ekasa(qr_raw)
        else:
            receipt = _fetch_from_ekasa(qr_raw)
    except (ConnectionError, ValueError) as exc:
        logger.warning(f"eKasa API zlyhalo: {exc}")
        if _is_offline_format(qr_raw):
            partial = _parse_offline_qr(qr_raw)
            result.datum = partial.get("datum")
            result.ico = ""  # unknown — vendor selected manually
            result.vat.celkom = partial.get("celkom", 0.0)
            result.is_offline = True
        result.data_complete = False
        result.parse_error = str(exc)
        return result

    # ---- map API response ------------------------------------------------
    org = receipt.get("organization") or {}
    result.ico = str(org.get("ico") or receipt.get("ico") or "")
    result.dic = str(org.get("dic") or receipt.get("dic") or "")
    result.nazov = str(org.get("name") or "")
    result.adresa = _build_address_from_org(org)
    result.datum = _parse_date(
        receipt.get("issueDate") or receipt.get("createDate") or ""
    )
    result.vat = _extract_vat(receipt)
    result.platba = _detect_platba(receipt)
    result.items = extract_items(receipt)
    result.data_complete = bool(result.items)

    try:
        result.api_data = json.dumps(receipt, ensure_ascii=False)
    except (TypeError, ValueError):
        result.api_data = None

    return result


def extract_items(api_receipt: dict) -> List[ReceiptItem]:
    """Extract line items from a raw eKasa receipt dict.

    Field map follows ekasa_raw.py: items/receiptItems, name/itemName,
    quantity/qty, unitPrice, price/totalPrice, vatRate. Returns a list of
    ``ReceiptItem`` without ``id``/``receipt_id`` (filled on insert).
    """
    raw_items = api_receipt.get("items") or api_receipt.get("receiptItems") or []
    items: List[ReceiptItem] = []
    for raw in raw_items:
        name = str(raw.get("name") or raw.get("itemName") or "").strip()
        quantity = _to_float(raw.get("quantity"), raw.get("qty"), default=1.0)
        unit_price = _to_float(raw.get("unitPrice"), default=0.0)
        price = _to_float(raw.get("price"), raw.get("totalPrice"), default=0.0)
        vat_rate = _to_float(raw.get("vatRate"), default=0.0)
        if not unit_price and quantity:
            unit_price = round(price / quantity, 4) if quantity else 0.0
        items.append(
            ReceiptItem(
                id=None,
                receipt_id=None,
                name=name,
                quantity=quantity,
                unit_price=round(unit_price, 4),
                price=round(price, 2),
                vat_rate=vat_rate,
            )
        )
    return items


# ------------------------------------------------------------------ helpers

def _to_float(*values, default: float = 0.0) -> float:
    """Return the first value that converts to a non-None float, else default."""
    for value in values:
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def _fetch_offline_from_ekasa(qr_raw: str) -> dict:
    """Fetch offline receipt from eKasa API using FIELDS-style lookup."""
    parts = qr_raw.strip().split(":")
    if len(parts) != 5:
        raise ValueError(f"Neplatný offline QR formát: {qr_raw}")

    okp, crc, date_str, seq, total_str = parts
    if len(date_str) != 12:
        raise ValueError(f"Neplatný dátum v QR: {date_str}")

    issue_date_formatted = (
        f"{date_str[4:6]}.{date_str[2:4]}.20{date_str[0:2]} "
        f"{date_str[6:8]}:{date_str[8:10]}:{date_str[10:12]}"
    )
    payload = {
        "okp": okp,
        "cashRegisterCode": crc,
        "receiptNumber": seq,
        "totalAmount": total_str,
        "issueDateFormatted": issue_date_formatted,
    }
    logger.debug(f"eKasa offline lookup: {payload}")

    data = _post_json(payload, timeout=12)
    if data.get("returnValue") != 0:
        raise ValueError(
            f"eKasa offline API vrátilo chybu (returnValue={data.get('returnValue')})"
        )
    if data.get("receipt") is not None:
        return data["receipt"]

    # Async response — poll for result (FIELDS, then receiptId fallbacks)
    polled = _poll_from_response(data)
    if polled is not None:
        return polled

    # Method 2 — receiptId = full QR; Method 3 — receiptId = OKP
    for rid in (qr_raw, okp):
        try:
            return _fetch_from_ekasa(rid)
        except (ConnectionError, ValueError):
            continue
    raise ValueError("eKasa offline API nevrátilo dáta dokladu.")


def _fetch_from_ekasa(receipt_id: str) -> dict:
    """Fetch receipt data from eKasa API by receiptId."""
    data = _post_json({"receiptId": receipt_id}, timeout=10)
    if data.get("returnValue") != 0:
        raise ValueError(
            f"eKasa API vrátilo chybu (returnValue={data.get('returnValue')})"
        )
    if data.get("receipt") is not None:
        return data["receipt"]
    polled = _poll_from_response(data)
    if polled is not None:
        return polled
    raise ValueError("eKasa API nevrátilo dáta dokladu.")


def _post_json(payload: dict, timeout: int = 10) -> dict:
    """POST a JSON payload to the eKasa API and return the parsed response."""
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        EKASA_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": EKASA_USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise ConnectionError(f"Nepodarilo sa pripojiť k eKasa: {exc}") from exc


def _poll_from_response(data: dict) -> Optional[dict]:
    """Poll for an async eKasa result if the response carries a searchUuid."""
    search_info = data.get("searchIdentification") or {}
    search_uuid = search_info.get("searchUuid")
    bucket = search_info.get("bucket", 0)
    if not search_uuid:
        return None
    return _poll_search_uuid(search_uuid, bucket)


def _poll_search_uuid(search_uuid: str, bucket: int) -> Optional[dict]:
    """Poll eKasa for async search result. Returns receipt dict or None."""
    variants = [
        {"searchUuid": search_uuid},
        {"searchUuid": search_uuid, "bucket": bucket},
    ]
    for attempt in range(1, 4):
        for body_dict in variants:
            try:
                data = _post_json(body_dict, timeout=10)
                if data.get("receipt") is not None:
                    return data["receipt"]
            except ConnectionError:
                pass
        if attempt < 3:
            time.sleep(1)
    return None


def _is_offline_format(qr: str) -> bool:
    """Return True if the QR string looks like an offline e-kasa format."""
    parts = qr.strip().split(":")
    return len(parts) == 5 and "-" in parts[0]


def _parse_offline_qr(offline_id: str) -> dict:
    """Extract minimal data from offline QR (date + total). Vendor unknown."""
    parts = offline_id.strip().split(":")
    datum_str = parts[2] if len(parts) > 2 else ""
    suma_str = parts[4] if len(parts) > 4 else "0"

    parsed_date: Optional[date] = None
    if len(datum_str) == 12:
        yy, mm, dd = datum_str[0:2], datum_str[2:4], datum_str[4:6]
        try:
            parsed_date = date.fromisoformat(f"20{yy}-{mm}-{dd}")
        except ValueError:
            pass
    try:
        celkom = float(suma_str)
    except ValueError:
        celkom = 0.0
    return {"datum": parsed_date, "celkom": celkom}


def _parse_date(value: str) -> Optional[date]:
    """Parse a date from various eKasa API formats."""
    if not value:
        return None
    value = str(value).strip()
    from datetime import datetime as dt
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return dt.strptime(value, fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _build_address_from_org(org: dict) -> str:
    """Build an address string from the 'organization' sub-object."""
    street = " ".join(filter(None, [
        org.get("streetName") or "",
        org.get("buildingNumber") or org.get("propertyRegistrationNumber") or "",
    ]))
    city = " ".join(filter(None, [
        org.get("postalCode") or "",
        org.get("municipality") or "",
    ]))
    parts = [p for p in (street, city, org.get("country") or "") if p]
    return ", ".join(parts)


def _detect_platba(receipt: dict) -> str:
    """Detect payment method (hotovost/karta) from eKasa fields."""
    cash = receipt.get("cashAmount")
    card = receipt.get("cardAmount")

    payments = receipt.get("payments") or []
    for p in payments:
        ptype = str(p.get("type") or p.get("paymentType") or "").lower()
        amount = float(p.get("amount") or 0)
        if amount > 0:
            if any(k in ptype for k in ("card", "karta", "bezhotovost")):
                return "karta"
            if any(k in ptype for k in ("cash", "hotovost")):
                return "hotovost"

    try:
        cash_val = float(cash) if cash is not None else None
        card_val = float(card) if card is not None else None
    except (ValueError, TypeError):
        return "hotovost"

    if card_val is not None and card_val > 0:
        if cash_val is None or cash_val == 0:
            return "karta"
    return "hotovost"


def _extract_vat(receipt: dict) -> VatBreakdown:
    """Extract the VAT breakdown from a raw eKasa receipt."""
    vat = VatBreakdown()

    summaries = receipt.get("vatSummary") or receipt.get("vatRateSummary") or []
    for entry in summaries:
        vat_info = entry.get("vat") or {}
        rate = float(vat_info.get("vatRate") or entry.get("vatRate") or 0)
        base = float(
            entry.get("vatBase") or entry.get("base") or entry.get("basisAmount") or 0
        )
        tax = float(entry.get("vatAmount") or entry.get("taxAmount") or 0)
        if rate == 0:
            vat.base_0 += base
        elif rate == 5:
            vat.base_5 += base
            vat.tax_5 += tax
        elif rate == 19:
            vat.base_19 += base
            vat.tax_19 += tax
        elif rate == 23:
            vat.base_23 += base
            vat.tax_23 += tax

    vat.celkom = float(receipt.get("totalPrice") or receipt.get("celkom") or 0)

    raw_rounding = (
        receipt.get("roundingAmount")
        or receipt.get("rounding")
        or receipt.get("zaokruhlenie")
    )
    if raw_rounding is not None:
        vat.zaokruhlenie = float(raw_rounding)
    else:
        vat_total = sum(
            float(e.get("vatBase") or 0) + float(e.get("vatAmount") or 0)
            for e in summaries
        )
        if vat.celkom and vat_total:
            vat.zaokruhlenie = round(vat.celkom - vat_total, 2)
        else:
            vat.zaokruhlenie = 0.0

    if not summaries:
        for item in receipt.get("items") or []:
            rate = float(item.get("vatRate") or 0)
            price = float(item.get("price") or 0)
            base = round(price / (1 + rate / 100), 4) if rate > 0 else price
            tax = round(price - base, 4)
            if rate == 0:
                vat.base_0 += base
            elif rate == 5:
                vat.base_5 += base
                vat.tax_5 += tax
            elif rate == 19:
                vat.base_19 += base
                vat.tax_19 += tax
            elif rate == 23:
                vat.base_23 += base
                vat.tax_23 += tax

    for attr in ("base_0", "base_5", "tax_5", "base_19", "tax_19",
                 "base_23", "tax_23", "zaokruhlenie", "celkom"):
        setattr(vat, attr, round(getattr(vat, attr), 2))
    return vat
