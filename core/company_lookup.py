"""
Slovak company data lookup via registeruz.sk (free, no API key required).

Two-step process:
  1. GET /uctovne-jednotky?ico=... -> internal ID list
  2. GET /uctovna-jednotka?id=...  -> company detail
"""

import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_BASE = "https://www.registeruz.sk/cruz-public/api"
_TIMEOUT = 8


class CompanyInfo:
    """Holds fetched company data."""

    def __init__(
        self,
        ico: str = "",
        dic: str = "",
        name: str = "",
        street: str = "",
        city: str = "",
        psc: str = "",
    ) -> None:
        self.ico = ico
        self.dic = dic
        self.name = name
        self.street = street
        self.city = city
        self.psc = psc

    def full_address(self) -> str:
        """Returns formatted address string."""
        parts = [p for p in (self.street, self.psc, self.city) if p]
        return ", ".join(parts)


def lookup_by_ico(ico: str) -> Optional[CompanyInfo]:
    """
    Fetch company information from registeruz.sk by IČO.

    Args:
        ico: 8-digit Slovak company identifier.

    Returns:
        CompanyInfo if found, None on any error or not-found.
    """
    try:
        internal_id = _get_internal_id(ico)
        if internal_id is None:
            return None
        return _get_company_detail(internal_id, ico)
    except Exception as exc:
        logger.warning(f"registeruz.sk lookup failed for IČO {ico}: {exc}")
        return None


def _get_internal_id(ico: str) -> Optional[int]:
    """Step 1 — resolve IČO to registeruz internal numeric ID."""
    url = f"{_BASE}/uctovne-jednotky"
    params = {"zmenene-od": "2000-01-01", "ico": ico}
    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.warning(f"registeruz ID lookup error: {exc}")
        return None

    ids = data.get("id") or data.get("ids") or []
    if not ids:
        return None
    return int(ids[0])


def _get_company_detail(internal_id: int, original_ico: str) -> Optional[CompanyInfo]:
    """Step 2 — fetch full company detail by internal ID."""
    url = f"{_BASE}/uctovna-jednotka"
    params = {"id": internal_id}
    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.warning(f"registeruz detail error: {exc}")
        return None

    return CompanyInfo(
        ico=str(data.get("ico") or original_ico),
        dic=str(data.get("dic") or ""),
        name=str(data.get("nazovUJ") or ""),
        street=str(data.get("ulica") or ""),
        city=str(data.get("mesto") or ""),
        psc=str(data.get("psc") or ""),
    )
