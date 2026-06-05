"""Offline eKasa receipt lookup — the proven 3-method fallback chain.

Ported from Scan_blocky/ekasa_offline.py (CLI tester) into a reusable module.
Offline QR format:  OKP:CASH_REG_CODE:YYMMDDHHMMSS:SEQ:SUMA

Returns the full ``receipt`` dict (including ``items``) once the cash register
has uploaded the receipt; raises ``ValueError`` otherwise.
"""

import logging
import time
from datetime import datetime
from typing import Optional

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

EKASA_URL = "https://ekasa.financnasprava.sk/mdu/api/v1/opd/receipt/find"
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


def parse_offline_qr(qr: str) -> dict:
    """Parse OKP:CRC:YYMMDDHHMMSS:SEQ:SUMA into its components."""
    parts = qr.strip().split(":")
    if len(parts) != 5:
        raise ValueError(
            f"Očakávam 5 častí oddelených ':', dostal {len(parts)}: {qr}"
        )
    okp, crc, date_str, seq, total_str = parts
    if len(date_str) != 12:
        raise ValueError(
            f"Dátum musí mať 12 znakov (YYMMDDHHMMSS), dostal: '{date_str}'"
        )
    dt = datetime(
        2000 + int(date_str[0:2]), int(date_str[2:4]), int(date_str[4:6]),
        int(date_str[6:8]), int(date_str[8:10]), int(date_str[10:12]),
    )
    return {
        "okp": okp,
        "crc": crc,
        "dt": dt,
        "seq": seq,
        "total": float(total_str),
        "total_str": total_str,
        "issueDateFormatted": dt.strftime("%d.%m.%Y %H:%M:%S"),
    }


def lookup_offline(qr: str) -> Optional[dict]:
    """Resolve an offline receipt via the 3-method chain.

    Returns the receipt dict (with items) or ``None`` if not yet uploaded /
    not found. Raises ``ValueError`` only on a malformed QR string.
    """
    p = parse_offline_qr(qr)

    # Method 1 — FIELDS lookup
    receipt = _try(
        {
            "okp": p["okp"],
            "cashRegisterCode": p["crc"],
            "receiptNumber": p["seq"],
            "totalAmount": p["total_str"],
            "issueDateFormatted": p["issueDateFormatted"],
        }
    )
    if receipt:
        return receipt

    # Method 2 — receiptId = full QR string
    receipt = _try({"receiptId": qr})
    if receipt:
        return receipt

    # Method 3 — receiptId = OKP only
    receipt = _try({"receiptId": p["okp"]})
    if receipt:
        return receipt

    return None


def _try(payload: dict) -> Optional[dict]:
    """POST one payload; handle sync + async (searchUuid) responses."""
    try:
        resp = requests.post(
            EKASA_URL, headers=HEADERS, json=payload, timeout=12, verify=False
        )
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.debug(f"eKasa offline pokus zlyhal: {exc}")
        return None

    if resp.status_code != 200 or data.get("returnValue") != 0:
        return None
    if data.get("receipt") is not None:
        return data["receipt"]

    si = data.get("searchIdentification") or {}
    uuid = si.get("searchUuid", "")
    bucket = si.get("bucket", 0)
    if uuid:
        return _poll(uuid, bucket)
    return None


def _poll(search_uuid: str, bucket: int,
          attempts: int = 6, delay: float = 2.0) -> Optional[dict]:
    """Poll an async searchUuid for the resolved receipt."""
    variants = [
        {"searchUuid": search_uuid},
        {"searchUuid": search_uuid, "bucket": bucket},
    ]
    for i in range(1, attempts + 1):
        for body in variants:
            try:
                resp = requests.post(
                    EKASA_URL, headers=HEADERS, json=body, timeout=12, verify=False
                )
                data = resp.json()
                if data.get("receipt") is not None:
                    return data["receipt"]
            except (requests.RequestException, ValueError):
                pass
        if i < attempts:
            time.sleep(delay)
    return None
