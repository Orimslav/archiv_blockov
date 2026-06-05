"""Dev-only helper: populate the database with realistic sample receipts.

Run from the project root::

    venv\\Scripts\\python.exe tests\\seed_sample_data.py

It is **re-runnable**: every receipt it creates carries a ``qr_raw`` starting
with ``SEED:``; on each run those rows are deleted first, so the sample set is
refreshed rather than duplicated. Real (non-seed) receipts are never touched.

Two profiles are populated:

* ``Moja domácnosť`` (household, no VAT) — groceries, drugstore, restaurants,
  transport across several months of 2025–2026.
* ``Moja firma`` (firm, VAT) — office supplies, fuel, business lunches with a
  proper per-rate VAT breakdown (Slovak rates: 23 % standard, 19 % / 5 %
  reduced, 0 %).

Staple items (Chlieb, Mlieko, …) appear in many months with drifting unit
prices, so the item search, consumption report and price-trend chart have
something meaningful to show.
"""

import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.database import Database
from models.models import ParsedReceipt, Profile, Receipt, ReceiptItem

# An item as authored in this seed: (name, quantity, unit_price_incl_vat,
# vat_rate, category_name). The line total and VAT split are derived.
ItemSpec = Tuple[str, float, float, float, str]
# A vendor: (ico, dic, name, address)
VendorSpec = Tuple[str, str, str, str]


def _round2(x: float) -> float:
    return round(x + 1e-9, 2)


def _build_receipt(
    profile_id: int,
    vendor_id: int,
    when: date,
    items: List[ReceiptItem],
    platba: str,
    popis: str,
    default_category_id: Optional[int],
    vat_enabled: bool,
    qr_raw: str,
) -> Receipt:
    """Aggregate item-level VAT into a Receipt with totals."""
    base = {0.0: 0.0, 5.0: 0.0, 19.0: 0.0, 23.0: 0.0}
    tax = {0.0: 0.0, 5.0: 0.0, 19.0: 0.0, 23.0: 0.0}
    total = 0.0
    for it in items:
        total += it.price
        rate = it.vat_rate if it.vat_rate in base else 0.0
        if vat_enabled and rate:
            net = it.price / (1 + rate / 100.0)
            base[rate] += net
            tax[rate] += it.price - net
        else:
            base[rate] += it.price
    return Receipt(
        id=None,
        profile_id=profile_id,
        vendor_id=vendor_id,
        datum=when,
        base_0=_round2(base[0.0]),
        base_5=_round2(base[5.0]),
        tax_5=_round2(tax[5.0]),
        base_19=_round2(base[19.0]),
        tax_19=_round2(tax[19.0]),
        base_23=_round2(base[23.0]),
        tax_23=_round2(tax[23.0]),
        zaokruhlenie=0.0,
        celkom=_round2(total),
        platba=platba,
        popis=popis,
        qr_raw=qr_raw,
        default_category_id=default_category_id,
        data_complete=True,
    )


def _make_items(specs: List[ItemSpec], cat_map: Dict[str, int]) -> List[ReceiptItem]:
    items: List[ReceiptItem] = []
    for name, qty, unit, rate, cat in specs:
        items.append(ReceiptItem(
            id=None, receipt_id=None, name=name, quantity=qty,
            unit_price=_round2(unit), price=_round2(unit * qty),
            vat_rate=rate, category_id=cat_map.get(cat),
        ))
    return items


def _ensure_profile(db: Database, name: str, kind: str, vat: bool,
                    ico: str = "", dic: str = "") -> int:
    for p in db.get_profiles():
        if p.name == name:
            return p.id
    return db.add_profile(Profile(None, name, kind, vat, ico, dic))


def _ensure_category(db: Database, profile_id: int, cat_map: Dict[str, int],
                     name: str, color: str) -> None:
    if name not in cat_map:
        cat_map[name] = db.add_category(profile_id, name, color)


def _vendor(db: Database, profile_id: int, spec: VendorSpec) -> int:
    ico, dic, name, addr = spec
    parsed = ParsedReceipt(qr_raw="", ico=ico, dic=dic, nazov=name, adresa=addr)
    return db.get_or_create_vendor(profile_id, parsed).id


def _clear_seed(db: Database) -> int:
    """Delete previously seeded receipts (qr_raw LIKE 'SEED:%'). Returns count."""
    with db._cursor() as cur:  # noqa: SLF001 — dev script, direct access is fine
        cur.execute("SELECT COUNT(*) AS n FROM receipts WHERE qr_raw LIKE 'SEED:%'")
        n = int(cur.fetchone()["n"])
        cur.execute("DELETE FROM receipts WHERE qr_raw LIKE 'SEED:%'")
    return n


def _seed_aliases(db: Database, profile_id: int, aliases: List[Tuple[str, str]]) -> None:
    """Add demo aliases (display_name, pattern); skip duplicates silently."""
    existing = {(a.display_name, a.pattern) for a in db.get_aliases(profile_id)}
    for display_name, pattern in aliases:
        if (display_name, pattern) in existing:
            continue
        try:
            db.add_alias(profile_id, display_name, pattern)
        except Exception:  # noqa: BLE001 — UNIQUE(pattern) clash is fine
            pass


def _seed_popis_history(db: Database, profile_id: int) -> None:
    """Backfill the description history from the seeded receipts (for reuse menu)."""
    with db._cursor() as cur:  # noqa: SLF001 — dev script, direct access is fine
        cur.execute(
            "SELECT DISTINCT popis FROM receipts "
            "WHERE profile_id = ? AND popis IS NOT NULL AND popis <> ''",
            (profile_id,),
        )
        popisy = [row["popis"] for row in cur.fetchall()]
    for popis in popisy:
        db.add_popis_history(profile_id, popis)


# --------------------------------------------------------------------------- vendors

HOUSEHOLD_VENDORS: Dict[str, VendorSpec] = {
    "LIDL": ("35790221", "SK2020151206", "Lidl SR v.o.s.", "Nevädzová 6, 821 01 Bratislava"),
    "BILLA": ("31347037", "SK2020312503", "BILLA s.r.o.", "Bajkalská 19/A, 821 02 Bratislava"),
    "KAUFLAND": ("35790164", "SK2020188083", "Kaufland SR v.o.s.", "Trnavská cesta 41/A, 831 04 Bratislava"),
    "DM": ("31393781", "SK2020317286", "dm drogerie markt s.r.o.", "Na pántoch 18, 831 06 Bratislava"),
    "RESTAURACIA": ("36123456", "SK2020123456", "Reštaurácia U Zlatého bažanta", "Hlavná 12, 040 01 Košice"),
    "SHELL": ("31361081", "SK2020308582", "Shell Slovakia s.r.o.", "Einsteinova 23, 851 01 Bratislava"),
    "MHD": ("00492736", "SK2020919689", "Dopravný podnik Bratislava a.s.", "Olejkárska 1, 814 52 Bratislava"),
}

FIRM_VENDORS: Dict[str, VendorSpec] = {
    "ALZA": ("36562939", "SK2021816990", "Alza.sk s.r.o.", "Bottova 7, 811 09 Bratislava"),
    "OFFICE": ("31320414", "SK2020290173", "Office Depot s.r.o.", "Diaľničná cesta 4, 903 01 Senec"),
    "OMV": ("00603783", "SK2020331980", "OMV Slovensko s.r.o.", "Einsteinova 25, 851 01 Bratislava"),
    "RESTAURACIA": ("36123456", "SK2020123456", "Reštaurácia U Zlatého bažanta", "Hlavná 12, 040 01 Košice"),
    "MARTINUS": ("45503249", "SK2023003097", "Martinus s.r.o.", "Gorkého 4, 036 01 Martin"),
}


def seed_household(db: Database, profile_id: int) -> int:
    """Seed the household profile. Returns number of receipts created."""
    cat_map = {c.name: c.id for c in db.get_categories(profile_id)}
    _ensure_category(db, profile_id, cat_map, "Alkohol", "#c0392b")
    cat_map = {c.name: c.id for c in db.get_categories(profile_id)}
    vid = {k: _vendor(db, profile_id, v) for k, v in HOUSEHOLD_VENDORS.items()}

    # bread/milk unit prices drift month to month (for the price-trend chart)
    bread = {1: 1.29, 2: 1.29, 3: 1.35, 4: 1.39, 5: 1.45, 6: 1.49}
    milk = {1: 0.99, 2: 1.05, 3: 1.05, 4: 1.09, 5: 1.12, 6: 1.15}

    count = 0
    seq = 0

    def add(vendor: str, when: date, specs: List[ItemSpec], platba: str,
            popis: str, default_cat: str) -> None:
        nonlocal count, seq
        seq += 1
        items = _make_items(specs, cat_map)
        rec = _build_receipt(
            profile_id, vid[vendor], when, items, platba, popis,
            cat_map.get(default_cat), vat_enabled=False,
            qr_raw=f"SEED:H:{seq}",
        )
        rid = db.insert_receipt(rec)
        db.insert_items(rid, items)
        count += 1

    for m in range(1, 7):
        # weekly grocery shop at LIDL
        add("LIDL", date(2026, m, 6), [
            ("Chlieb cel.", 2, bread[m], 0, "Potraviny"),
            ("Mlieko polotučné 1l", 3, milk[m], 0, "Potraviny"),
            ("Maslo 125g", 1, 2.49, 0, "Potraviny"),
            ("Jablká 1kg", 2, 1.89, 0, "Potraviny"),
            ("Pivo Šariš 0,5l", 6, 0.89, 0, "Alkohol"),
        ], "karta", "Týždenný nákup", "Potraviny")

        # mid-month BILLA
        add("BILLA", date(2026, m, 16), [
            ("Rožky 6ks", 2, 0.54, 0, "Potraviny"),
            ("Syr Eidam 100g", 2, 1.19, 0, "Potraviny"),
            ("Mlieko polotučné 1l", 2, milk[m] + 0.04, 0, "Potraviny"),
            ("Kuracie prsia 1kg", 1, 6.99, 0, "Potraviny"),
        ], "hotovost", "Doplnenie", "Potraviny")

        # drugstore every other month
        if m % 2 == 1:
            add("DM", date(2026, m, 11), [
                ("Zubná pasta", 1, 2.79, 0, "Drogéria"),
                ("Sprchový gél", 2, 1.99, 0, "Drogéria"),
                ("Toaletný papier 8ks", 1, 3.49, 0, "Drogéria"),
            ], "karta", "", "Drogéria")

        # restaurant once a month
        add("RESTAURACIA", date(2026, m, 21), [
            ("Obedové menu", 2, 8.90, 0, "Reštaurácie"),
            ("Kofola 0,5l", 2, 1.80, 0, "Reštaurácie"),
        ], "karta", "Obed", "Reštaurácie")

        # transport
        add("MHD", date(2026, m, 3), [
            ("Predplatný lístok mesačný", 1, 26.90, 0, "Doprava"),
        ], "karta", "MHD predplatné", "Doprava")

    # a couple of late-2025 receipts (out-of-order filing demo)
    add("KAUFLAND", date(2025, 12, 22), [
        ("Vianočný kapor 1kg", 1, 7.49, 0, "Potraviny"),
        ("Zemiaky 5kg", 1, 3.99, 0, "Potraviny"),
        ("Víno biele 0,75l", 2, 4.99, 0, "Alkohol"),
    ], "karta", "Vianočný nákup", "Potraviny")
    add("SHELL", date(2025, 11, 18), [
        ("Káva so sebou", 1, 1.90, 0, "Reštaurácie"),
        ("Bageta", 1, 3.20, 0, "Potraviny"),
    ], "hotovost", "", "Ostatné")

    return count


def seed_firm(db: Database, profile_id: int) -> int:
    """Seed the firm profile (VAT). Returns number of receipts created."""
    cat_map = {c.name: c.id for c in db.get_categories(profile_id)}
    _ensure_category(db, profile_id, cat_map, "Kancelárske potreby", "#1abc9c")
    _ensure_category(db, profile_id, cat_map, "PHM", "#e74c3c")
    _ensure_category(db, profile_id, cat_map, "IT vybavenie", "#34495e")
    cat_map = {c.name: c.id for c in db.get_categories(profile_id)}
    vid = {k: _vendor(db, profile_id, v) for k, v in FIRM_VENDORS.items()}

    count = 0
    seq = 0

    def add(vendor: str, when: date, specs: List[ItemSpec], platba: str,
            popis: str, default_cat: str) -> None:
        nonlocal count, seq
        seq += 1
        items = _make_items(specs, cat_map)
        rec = _build_receipt(
            profile_id, vid[vendor], when, items, platba, popis,
            cat_map.get(default_cat), vat_enabled=True,
            qr_raw=f"SEED:F:{seq}",
        )
        rid = db.insert_receipt(rec)
        db.insert_items(rid, items)
        count += 1

    for m in range(1, 7):
        # monthly office supplies (mixed standard + reduced rates)
        add("OFFICE", date(2026, m, 5), [
            ("Kancelársky papier A4 500", 5, 6.49, 23, "Kancelárske potreby"),
            ("Tonerová kazeta", 1, 79.90, 23, "Kancelárske potreby"),
            ("Perá guľôčkové 10ks", 2, 4.50, 23, "Kancelárske potreby"),
        ], "karta", "Mesačné kancelárske potreby", "Kancelárske potreby")

        # fuel twice a month
        add("OMV", date(2026, m, 9), [
            ("Nafta Diesel", 45.2, 1.589, 23, "PHM"),
        ], "karta", "Tankovanie", "PHM")
        add("OMV", date(2026, m, 23), [
            ("Natural 95", 38.7, 1.629, 23, "PHM"),
        ], "karta", "Tankovanie", "PHM")

        # business lunch (restaurant — 19% reduced rate on food in SK)
        add("RESTAURACIA", date(2026, m, 14), [
            ("Obchodný obed", 3, 12.50, 19, "Reštaurácie"),
            ("Minerálka", 3, 2.20, 23, "Reštaurácie"),
        ], "karta", "Obchodné stretnutie", "Reštaurácie")

    # occasional IT purchases
    add("ALZA", date(2026, 2, 18), [
        ("Monitor 27\" LED", 2, 199.00, 23, "IT vybavenie"),
        ("USB-C kábel", 3, 9.90, 23, "IT vybavenie"),
    ], "karta", "Vybavenie kancelárie", "IT vybavenie")
    add("ALZA", date(2026, 5, 7), [
        ("Notebook 14\"", 1, 899.00, 23, "IT vybavenie"),
    ], "karta", "Nový notebook", "IT vybavenie")
    # books (10% reduced rate -> use 5% bucket as nearest reduced; demo of 5%)
    add("MARTINUS", date(2026, 3, 12), [
        ("Odborná literatúra", 2, 24.90, 5, "Ostatné"),
    ], "hotovost", "Odborné knihy", "Ostatné")

    return count


def main() -> None:
    db = Database(_ROOT / "data" / "archiv_blockov.db")
    db.connect()
    try:
        removed = _clear_seed(db)
        if removed:
            print(f"Odstránených starých seed bločkov: {removed}")

        hh_id = _ensure_profile(db, "Moja domácnosť", "household", False)
        firm_id = _ensure_profile(db, "Moja firma", "firm", True,
                                  ico="51234567", dic="SK2120654321")

        n_hh = seed_household(db, hh_id)
        n_firm = seed_firm(db, firm_id)

        # Demo aliases — one display name grouping several name variants.
        _seed_aliases(db, hh_id, [
            ("Chlieb", "chlieb"),
            ("Mlieko", "mlieko"),
            ("Pivo", "pivo"),
            ("Mliečne", "mlieko"),
            ("Mliečne", "syr"),
            ("Mliečne", "maslo"),
        ])
        _seed_aliases(db, firm_id, [
            ("Pohonné hmoty", "nafta"),
            ("Pohonné hmoty", "natural"),
        ])

        # Backfill description history so the right-click reuse menu has options.
        _seed_popis_history(db, hh_id)
        _seed_popis_history(db, firm_id)

        print(f"Vytvorené bločky — domácnosť: {n_hh}, firma: {n_firm}")
        print(f"Databáza: {db.path}")
    finally:
        db.disconnect()


if __name__ == "__main__":
    main()
