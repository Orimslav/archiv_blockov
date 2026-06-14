"""SQLite database manager for Archiv_blockov.

Handles schema creation, idempotent migrations (ALTER TABLE / CREATE INDEX),
a ``PRAGMA user_version`` guard for ordered data migrations, and all CRUD.
Registers ``normalize_name`` as a SQLite function for diacritics/case-
insensitive item and alias matching.
"""

import logging
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Generator, List, Optional, Tuple

from core.text_utils import normalize_name
from models.models import (
    Category,
    ItemAlias,
    ParsedReceipt,
    Profile,
    Receipt,
    ReceiptItem,
    Vendor,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# Sentinel for the category filter: match receipts with at least one
# uncategorized item (receipt_items.category_id IS NULL).
UNCATEGORIZED_FILTER = "__uncategorized__"

# Tables that a valid Archiv_blockov database must contain (restore guard).
_REQUIRED_TABLES = {
    "profiles", "categories", "vendors", "receipts", "receipt_items", "settings",
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS profiles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'household',
    vat_enabled INTEGER NOT NULL DEFAULT 0,
    ico         TEXT DEFAULT '',
    dic         TEXT DEFAULT '',
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS categories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER REFERENCES profiles(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    color      TEXT DEFAULT '#4a9eff',
    UNIQUE(profile_id, name)
);

CREATE TABLE IF NOT EXISTS vendors (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id          INTEGER REFERENCES profiles(id) ON DELETE CASCADE,
    ico                 TEXT,
    dic                 TEXT,
    name                TEXT,
    address             TEXT,
    default_category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    UNIQUE(profile_id, ico)
);

CREATE TABLE IF NOT EXISTS receipts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id          INTEGER REFERENCES profiles(id) ON DELETE CASCADE,
    vendor_id           INTEGER REFERENCES vendors(id) ON DELETE SET NULL,
    datum               DATE,
    base_0              REAL DEFAULT 0,
    base_5              REAL DEFAULT 0,
    tax_5               REAL DEFAULT 0,
    base_19             REAL DEFAULT 0,
    tax_19              REAL DEFAULT 0,
    base_23             REAL DEFAULT 0,
    tax_23              REAL DEFAULT 0,
    zaokruhlenie        REAL DEFAULT 0,
    celkom              REAL,
    platba              TEXT DEFAULT 'hotovost',
    popis               TEXT,
    qr_raw              TEXT,
    default_category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    account_year        INTEGER,
    account_month       INTEGER,
    data_complete       INTEGER DEFAULT 1,
    sync_attempts       INTEGER DEFAULT 0,
    last_sync_attempt   TIMESTAMP,
    sync_error          TEXT,
    api_data            TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS receipt_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id   INTEGER REFERENCES receipts(id) ON DELETE CASCADE,
    name         TEXT,
    quantity     REAL DEFAULT 1,
    unit_price   REAL DEFAULT 0,
    price        REAL DEFAULT 0,
    vat_rate     REAL DEFAULT 0,
    category_id  INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    is_synthetic INTEGER DEFAULT 0,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS item_aliases (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id   INTEGER REFERENCES profiles(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    pattern      TEXT NOT NULL,
    UNIQUE(profile_id, pattern)
);

CREATE TABLE IF NOT EXISTS popis_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER REFERENCES profiles(id) ON DELETE CASCADE,
    popis      TEXT NOT NULL,
    UNIQUE(profile_id, popis)
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
"""

INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_receipts_profile_period ON receipts(profile_id, account_year, account_month)",
    "CREATE INDEX IF NOT EXISTS idx_receipts_profile_datum  ON receipts(profile_id, datum)",
    "CREATE INDEX IF NOT EXISTS idx_receipts_vendor         ON receipts(vendor_id)",
    "CREATE INDEX IF NOT EXISTS idx_items_receipt           ON receipt_items(receipt_id)",
    "CREATE INDEX IF NOT EXISTS idx_items_category          ON receipt_items(category_id)",
    "CREATE INDEX IF NOT EXISTS idx_items_name              ON receipt_items(name)",
    "CREATE INDEX IF NOT EXISTS idx_vendors_profile_ico     ON vendors(profile_id, ico)",
]

DEFAULT_CATEGORIES = [
    ("Potraviny", "#2ecc71"),
    ("Drogéria", "#9b59b6"),
    ("Reštaurácie", "#e67e22"),
    ("Doprava", "#3498db"),
    ("Ostatné", "#888888"),
]


class Database:
    """Manages the SQLite connection and all CRUD operations."""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    # ------------------------------------------------------------ lifecycle

    def connect(self) -> None:
        """Open the connection, register functions, init schema + migrations."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self._path),
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.create_function("normalize_name", 1, normalize_name)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()
        logger.info(f"Databáza pripojená: {self._path}")

    def disconnect(self) -> None:
        """Close the connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def path(self) -> Path:
        """Return the database file path."""
        return self._path

    def _init_schema(self) -> None:
        with self._conn:  # type: ignore[union-attr]
            self._conn.executescript(SCHEMA_SQL)  # type: ignore[union-attr]
            for sql in INDEX_SQL:
                self._conn.execute(sql)  # type: ignore[union-attr]
        self._run_migrations()

    def _run_migrations(self) -> None:
        """Apply idempotent column adds and ordered (user_version) migrations."""
        column_migrations: List[str] = [
            # Provisioned for forward compatibility — safe no-ops if present.
            "ALTER TABLE receipts ADD COLUMN sync_error TEXT",
        ]
        for sql in column_migrations:
            try:
                with self._conn:  # type: ignore[union-attr]
                    self._conn.execute(sql)  # type: ignore[union-attr]
            except sqlite3.OperationalError:
                pass

        version = self._conn.execute("PRAGMA user_version").fetchone()[0]  # type: ignore[union-attr]
        if version < SCHEMA_VERSION:
            # Reserved for ordered data transforms; none needed at v1.
            with self._conn:  # type: ignore[union-attr]
                self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")  # type: ignore[union-attr]

    @contextmanager
    def _cursor(self) -> Generator[sqlite3.Cursor, None, None]:
        """Yield a cursor inside a transaction."""
        assert self._conn is not None, "Databáza nie je pripojená"
        with self._conn:
            yield self._conn.cursor()

    # ------------------------------------------------------------ profiles

    def get_profiles(self) -> List[Profile]:
        """Return all profiles ordered by name."""
        with self._cursor() as cur:
            cur.execute("SELECT * FROM profiles ORDER BY name COLLATE NOCASE")
            return [self._row_to_profile(r) for r in cur.fetchall()]

    def get_profile(self, profile_id: int) -> Optional[Profile]:
        """Return a single profile by id."""
        with self._cursor() as cur:
            cur.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,))
            row = cur.fetchone()
            return self._row_to_profile(row) if row else None

    def add_profile(self, p: Profile) -> int:
        """Insert a profile, seed default categories, return new id."""
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO profiles (name, kind, vat_enabled, ico, dic) "
                "VALUES (?, ?, ?, ?, ?)",
                (p.name, p.kind, int(p.vat_enabled), p.ico, p.dic),
            )
            profile_id = cur.lastrowid
            for name, color in DEFAULT_CATEGORIES:
                cur.execute(
                    "INSERT INTO categories (profile_id, name, color) VALUES (?, ?, ?)",
                    (profile_id, name, color),
                )
        return int(profile_id)

    def update_profile(self, p: Profile) -> None:
        """Update an existing profile."""
        with self._cursor() as cur:
            cur.execute(
                "UPDATE profiles SET name=?, kind=?, vat_enabled=?, ico=?, dic=? "
                "WHERE id=?",
                (p.name, p.kind, int(p.vat_enabled), p.ico, p.dic, p.id),
            )

    def delete_profile(self, profile_id: int) -> None:
        """Delete a profile and cascade to its data."""
        with self._cursor() as cur:
            cur.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))

    # ------------------------------------------------------------ categories

    def get_categories(self, profile_id: int) -> List[Category]:
        """Return categories for a profile ordered by name."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM categories WHERE profile_id = ? ORDER BY name COLLATE NOCASE",
                (profile_id,),
            )
            return [
                Category(r["id"], r["profile_id"], r["name"], r["color"])
                for r in cur.fetchall()
            ]

    def add_category(self, profile_id: int, name: str, color: str = "#4a9eff") -> int:
        """Insert a category, return its id."""
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO categories (profile_id, name, color) VALUES (?, ?, ?)",
                (profile_id, name, color),
            )
            return int(cur.lastrowid)

    def update_category(self, category_id: int, name: str, color: str) -> None:
        """Update a category."""
        with self._cursor() as cur:
            cur.execute(
                "UPDATE categories SET name=?, color=? WHERE id=?",
                (name, color, category_id),
            )

    def delete_category(self, category_id: int) -> None:
        """Delete a category (items fall back to NULL = Nezaradené)."""
        with self._cursor() as cur:
            cur.execute("DELETE FROM categories WHERE id = ?", (category_id,))

    # ------------------------------------------------------------ vendors

    def get_vendors(self, profile_id: int) -> List[Vendor]:
        """Return vendors for a profile ordered by name."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM vendors WHERE profile_id = ? ORDER BY name COLLATE NOCASE",
                (profile_id,),
            )
            return [self._row_to_vendor(r) for r in cur.fetchall()]

    def get_or_create_vendor(self, profile_id: int, parsed: ParsedReceipt) -> Vendor:
        """Resolve a vendor by IČO under the profile, creating it if unknown.

        Some e-kasa receipts carry no IČO (the API returns ``ico=null``) — only
        a DIČ. Vendors are unique on ``(profile_id, ico)``, so storing an empty
        string would make every IČO-less vendor collide. For those, match on DIČ
        then name, and store ``NULL`` (SQLite treats NULLs as distinct, so any
        number of IČO-less vendors can coexist).
        """
        with self._cursor() as cur:
            row = None
            if parsed.ico:
                cur.execute(
                    "SELECT * FROM vendors WHERE profile_id = ? AND ico = ?",
                    (profile_id, parsed.ico),
                )
                row = cur.fetchone()
            else:
                if parsed.dic:
                    cur.execute(
                        "SELECT * FROM vendors WHERE profile_id = ? "
                        "AND COALESCE(ico, '') = '' AND dic = ?",
                        (profile_id, parsed.dic),
                    )
                    row = cur.fetchone()
                if row is None and parsed.nazov:
                    cur.execute(
                        "SELECT * FROM vendors WHERE profile_id = ? "
                        "AND COALESCE(ico, '') = '' AND name = ?",
                        (profile_id, parsed.nazov),
                    )
                    row = cur.fetchone()
            if row:
                return self._row_to_vendor(row)
            cur.execute(
                "INSERT INTO vendors (profile_id, ico, dic, name, address) "
                "VALUES (?, ?, ?, ?, ?)",
                (profile_id, parsed.ico or None, parsed.dic, parsed.nazov, parsed.adresa),
            )
            vendor_id = int(cur.lastrowid)
        return Vendor(
            id=vendor_id,
            profile_id=profile_id,
            ico=parsed.ico,
            dic=parsed.dic,
            name=parsed.nazov,
            address=parsed.adresa,
        )

    def get_or_create_vendor_by_name(self, profile_id: int, name: str) -> Vendor:
        """Resolve/create a vendor by display name (manual entry)."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM vendors WHERE profile_id = ? AND name = ?",
                (profile_id, name),
            )
            row = cur.fetchone()
            if row:
                return self._row_to_vendor(row)
            cur.execute(
                "INSERT INTO vendors (profile_id, ico, dic, name, address) "
                "VALUES (?, NULL, '', ?, '')",
                (profile_id, name),
            )
            vendor_id = int(cur.lastrowid)
        return Vendor(vendor_id, profile_id, "", "", name, "")

    def set_vendor_default_category(self, vendor_id: int, category_id: Optional[int]) -> None:
        """Learn the vendor's default category."""
        with self._cursor() as cur:
            cur.execute(
                "UPDATE vendors SET default_category_id=? WHERE id=?",
                (category_id, vendor_id),
            )

    # ------------------------------------------------------------ receipts

    def receipt_exists(self, profile_id: int, qr_raw: str) -> bool:
        """Duplicate guard — True if this qr_raw already exists in the profile."""
        if not qr_raw:
            return False
        with self._cursor() as cur:
            cur.execute(
                "SELECT 1 FROM receipts WHERE profile_id = ? AND qr_raw = ? LIMIT 1",
                (profile_id, qr_raw),
            )
            return cur.fetchone() is not None

    def insert_receipt(self, r: Receipt) -> int:
        """Insert a receipt row, deriving accounting period from datum."""
        year = r.datum.year if r.datum else (r.account_year or 0)
        month = r.datum.month if r.datum else (r.account_month or 0)
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO receipts (
                    profile_id, vendor_id, datum, base_0, base_5, tax_5,
                    base_19, tax_19, base_23, tax_23, zaokruhlenie, celkom,
                    platba, popis, qr_raw, default_category_id,
                    account_year, account_month, data_complete, api_data, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    r.profile_id, r.vendor_id,
                    r.datum.isoformat() if r.datum else None,
                    round(r.base_0, 2), round(r.base_5, 2), round(r.tax_5, 2),
                    round(r.base_19, 2), round(r.tax_19, 2),
                    round(r.base_23, 2), round(r.tax_23, 2),
                    round(r.zaokruhlenie, 2),
                    round(r.celkom, 2) if r.celkom is not None else None,
                    r.platba, r.popis, r.qr_raw, r.default_category_id,
                    year, month, int(r.data_complete), r.api_data,
                    datetime.now().isoformat(sep=" ", timespec="seconds"),
                ),
            )
            return int(cur.lastrowid)

    def insert_items(self, receipt_id: int, items: List[ReceiptItem]) -> None:
        """Insert receipt items."""
        if not items:
            return
        with self._cursor() as cur:
            cur.executemany(
                """INSERT INTO receipt_items (
                    receipt_id, name, quantity, unit_price, price, vat_rate,
                    category_id, is_synthetic
                ) VALUES (?,?,?,?,?,?,?,?)""",
                [
                    (
                        receipt_id, it.name, it.quantity, it.unit_price,
                        round(it.price, 2), it.vat_rate, it.category_id,
                        int(it.is_synthetic),
                    )
                    for it in items
                ],
            )

    def replace_items(self, receipt_id: int, items: List[ReceiptItem]) -> None:
        """Replace all items of a receipt (used by re-sync)."""
        with self._cursor() as cur:
            cur.execute("DELETE FROM receipt_items WHERE receipt_id = ?", (receipt_id,))
        self.insert_items(receipt_id, items)

    def get_items(self, receipt_id: int) -> List[ReceiptItem]:
        """Return all items of a receipt."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM receipt_items WHERE receipt_id = ? ORDER BY id",
                (receipt_id,),
            )
            return [self._row_to_item(r) for r in cur.fetchall()]

    def set_item_category(self, item_id: int, category_id: Optional[int]) -> None:
        """Set a single item's category and keep the receipt chip in sync.

        After the item changes, the receipt's ``default_category_id`` is
        recomputed from its items: if every item shares one category the
        receipt adopts it; if they differ it is cleared to NULL so the main
        table shows the „zmiešané" chip.
        """
        now = datetime.now().isoformat(sep=" ", timespec="seconds")
        with self._cursor() as cur:
            cur.execute(
                "UPDATE receipt_items SET category_id=?, updated_at=? WHERE id=?",
                (category_id, now, item_id),
            )
            row = cur.execute(
                "SELECT receipt_id FROM receipt_items WHERE id=?", (item_id,)
            ).fetchone()
            if row is not None:
                self._sync_receipt_default_category(cur, row["receipt_id"], now)

    def _sync_receipt_default_category(self, cur, receipt_id: int, now: str) -> None:
        """Set ``default_category_id`` to the items' shared category, else NULL.

        Operates on an open cursor so it joins the caller's transaction.
        """
        rows = cur.execute(
            "SELECT DISTINCT category_id FROM receipt_items WHERE receipt_id=?",
            (receipt_id,),
        ).fetchall()
        distinct = [r["category_id"] for r in rows]
        new_default = distinct[0] if len(distinct) == 1 else None
        cur.execute(
            "UPDATE receipts SET default_category_id=?, updated_at=? WHERE id=?",
            (new_default, now, receipt_id),
        )

    def set_receipt_category(self, receipt_id: int, category_id: Optional[int]) -> None:
        """Set the receipt default category and cascade to all its items."""
        now = datetime.now().isoformat(sep=" ", timespec="seconds")
        with self._cursor() as cur:
            cur.execute(
                "UPDATE receipts SET default_category_id=?, updated_at=? WHERE id=?",
                (category_id, now, receipt_id),
            )
            cur.execute(
                "UPDATE receipt_items SET category_id=?, updated_at=? WHERE receipt_id=?",
                (category_id, now, receipt_id),
            )

    def set_receipt_vendor(self, receipt_id: int, vendor_id: Optional[int]) -> None:
        """Set the receipt's vendor (used by re-sync of manual UID entries)."""
        with self._cursor() as cur:
            cur.execute(
                "UPDATE receipts SET vendor_id=?, updated_at=? WHERE id=?",
                (vendor_id, datetime.now().isoformat(sep=" ", timespec="seconds"),
                 receipt_id),
            )

    def set_receipt_platba(self, receipt_id: int, platba: str) -> None:
        """Inline toggle of the payment method."""
        with self._cursor() as cur:
            cur.execute(
                "UPDATE receipts SET platba=?, updated_at=? WHERE id=?",
                (platba, datetime.now().isoformat(sep=" ", timespec="seconds"), receipt_id),
            )

    def set_receipt_popis(self, receipt_id: int, popis: str) -> None:
        """Update a receipt's description."""
        with self._cursor() as cur:
            cur.execute(
                "UPDATE receipts SET popis=?, updated_at=? WHERE id=?",
                (popis, datetime.now().isoformat(sep=" ", timespec="seconds"), receipt_id),
            )

    def set_receipt_complete(self, receipt_id: int, complete: bool, api_data: str) -> None:
        """Mark a receipt complete and refresh its stored api_data."""
        with self._cursor() as cur:
            cur.execute(
                "UPDATE receipts SET data_complete=?, api_data=?, sync_error=NULL, "
                "updated_at=? WHERE id=?",
                (
                    int(complete), api_data,
                    datetime.now().isoformat(sep=" ", timespec="seconds"), receipt_id,
                ),
            )

    def delete_receipt(self, receipt_id: int) -> None:
        """Delete a receipt and cascade to its items."""
        with self._cursor() as cur:
            cur.execute("DELETE FROM receipts WHERE id = ?", (receipt_id,))

    def get_receipts(
        self,
        profile_id: int,
        year: Optional[int] = None,
        month: Optional[int] = None,
        category_id: Optional[int] = None,
        vendor_id: Optional[int] = None,
        search: str = "",
    ) -> List[Receipt]:
        """Return receipts for a profile with optional filters, joined with
        vendor + category info and a distinct-category count over items."""
        sql = [
            """SELECT r.*, v.name AS vendor_name,
                      c.name AS category_name, c.color AS category_color,
                      (SELECT COUNT(DISTINCT IFNULL(ri.category_id, -1))
                         FROM receipt_items ri WHERE ri.receipt_id = r.id) AS category_count
                 FROM receipts r
                 LEFT JOIN vendors v   ON v.id = r.vendor_id
                 LEFT JOIN categories c ON c.id = r.default_category_id
                WHERE r.profile_id = ?"""
        ]
        params: list = [profile_id]
        if year:
            sql.append("AND r.account_year = ?")
            params.append(year)
        if month:
            sql.append("AND r.account_month = ?")
            params.append(month)
        if vendor_id:
            sql.append("AND r.vendor_id = ?")
            params.append(vendor_id)
        if category_id == UNCATEGORIZED_FILTER:
            sql.append(
                "AND EXISTS (SELECT 1 FROM receipt_items ri "
                "WHERE ri.receipt_id = r.id AND ri.category_id IS NULL)"
            )
        elif category_id:
            sql.append(
                "AND EXISTS (SELECT 1 FROM receipt_items ri "
                "WHERE ri.receipt_id = r.id AND ri.category_id = ?)"
            )
            params.append(category_id)
        if search:
            term = f"%{search.strip()}%"
            sql.append(
                "AND (IFNULL(v.name,'') LIKE ? OR IFNULL(r.popis,'') LIKE ? "
                "OR CAST(r.celkom AS TEXT) LIKE ? OR IFNULL(r.datum,'') LIKE ?)"
            )
            params.extend([term, term, term, term])
        sql.append("ORDER BY r.datum IS NULL, r.datum ASC, r.id ASC")

        with self._cursor() as cur:
            cur.execute(" ".join(sql), params)
            return [self._row_to_receipt(r) for r in cur.fetchall()]

    def get_receipt(self, receipt_id: int) -> Optional[Receipt]:
        """Return a single receipt joined with vendor/category info."""
        with self._cursor() as cur:
            cur.execute(
                """SELECT r.*, v.name AS vendor_name,
                          c.name AS category_name, c.color AS category_color, 1 AS category_count
                     FROM receipts r
                     LEFT JOIN vendors v   ON v.id = r.vendor_id
                     LEFT JOIN categories c ON c.id = r.default_category_id
                    WHERE r.id = ?""",
                (receipt_id,),
            )
            row = cur.fetchone()
            return self._row_to_receipt(row) if row else None

    def get_incomplete_receipts(self, profile_id: int, max_attempts: Optional[int] = None) -> List[Receipt]:
        """Return receipts with data_complete = 0 (optionally under attempt cap)."""
        sql = "SELECT * FROM receipts WHERE profile_id = ? AND data_complete = 0"
        params: list = [profile_id]
        if max_attempts is not None:
            sql += " AND sync_attempts < ?"
            params.append(max_attempts)
        with self._cursor() as cur:
            cur.execute(sql, params)
            return [self._row_to_receipt(r) for r in cur.fetchall()]

    def record_sync_attempt(self, receipt_id: int, error: Optional[str]) -> None:
        """Increment sync_attempts, stamp last_sync_attempt, store error."""
        with self._cursor() as cur:
            cur.execute(
                "UPDATE receipts SET sync_attempts = sync_attempts + 1, "
                "last_sync_attempt = ?, sync_error = ? WHERE id = ?",
                (datetime.now().isoformat(sep=" ", timespec="seconds"), error, receipt_id),
            )

    def update_receipt_vat(self, r: Receipt) -> None:
        """Update VAT/total/payment columns after a re-sync."""
        with self._cursor() as cur:
            cur.execute(
                """UPDATE receipts SET base_0=?, base_5=?, tax_5=?, base_19=?,
                       tax_19=?, base_23=?, tax_23=?, zaokruhlenie=?, celkom=?,
                       platba=?, datum=?, account_year=?, account_month=?, updated_at=?
                     WHERE id=?""",
                (
                    round(r.base_0, 2), round(r.base_5, 2), round(r.tax_5, 2),
                    round(r.base_19, 2), round(r.tax_19, 2),
                    round(r.base_23, 2), round(r.tax_23, 2),
                    round(r.zaokruhlenie, 2), round(r.celkom, 2),
                    r.platba, r.datum.isoformat() if r.datum else None,
                    r.account_year, r.account_month,
                    datetime.now().isoformat(sep=" ", timespec="seconds"), r.id,
                ),
            )

    # ------------------------------------------------------------ item search

    def search_items(
        self,
        profile_id: int,
        term: str = "",
        alias_id: Optional[int] = None,
        year: Optional[int] = None,
        month: Optional[int] = None,
        category_id: Optional[int] = None,
    ) -> List[dict]:
        """Search line items (diacritics/case-insensitive). Returns rows as dicts."""
        sql = [
            """SELECT ri.*, r.datum AS r_datum, v.name AS vendor_name,
                      c.name AS category_name, c.color AS category_color
                 FROM receipt_items ri
                 JOIN receipts r    ON r.id = ri.receipt_id
                 LEFT JOIN vendors v ON v.id = r.vendor_id
                 LEFT JOIN categories c ON c.id = ri.category_id
                WHERE r.profile_id = ?"""
        ]
        params: list = [profile_id]
        patterns = self._resolve_patterns(profile_id, term, alias_id)
        if patterns:
            clause = " OR ".join(
                ["normalize_name(ri.name) LIKE normalize_name(?)"] * len(patterns)
            )
            sql.append(f"AND ({clause})")
            params.extend(patterns)
        if year:
            sql.append("AND r.account_year = ?")
            params.append(year)
        if month:
            sql.append("AND r.account_month = ?")
            params.append(month)
        if category_id:
            sql.append("AND ri.category_id = ?")
            params.append(category_id)
        sql.append("ORDER BY r.datum IS NULL, r.datum ASC, ri.id ASC")

        with self._cursor() as cur:
            cur.execute(" ".join(sql), params)
            return [dict(r) for r in cur.fetchall()]

    def _resolve_patterns(self, profile_id: int, term: str, alias_id: Optional[int]) -> List[str]:
        """Build LIKE patterns from a free term and/or an alias.

        Selecting an alias matches **all** patterns that share its display
        name, so a single „Chlieb" pick sums every variant grouped under it.
        """
        patterns: List[str] = []
        if alias_id:
            with self._cursor() as cur:
                cur.execute(
                    "SELECT display_name FROM item_aliases WHERE id = ? AND profile_id = ?",
                    (alias_id, profile_id),
                )
                row = cur.fetchone()
                if row:
                    cur.execute(
                        "SELECT pattern FROM item_aliases "
                        "WHERE profile_id = ? AND display_name = ?",
                        (profile_id, row["display_name"]),
                    )
                    for prow in cur.fetchall():
                        pat = prow["pattern"]
                        patterns.append(pat if "%" in pat else f"%{pat}%")
        if term.strip():
            patterns.append(f"%{term.strip()}%")
        return patterns

    def get_item_monthly_report(
        self, profile_id: int, term: str = "", alias_id: Optional[int] = None,
        year: Optional[int] = None,
    ) -> List[Tuple[int, float, float]]:
        """Return (month, total_qty, total_spend) for the matched item/alias."""
        rows = self.search_items(profile_id, term, alias_id, year=year)
        buckets: dict = {}
        for r in rows:
            datum = r.get("r_datum")
            month = 0
            if datum:
                try:
                    month = date.fromisoformat(str(datum)[:10]).month
                except ValueError:
                    month = 0
            qty, spend = buckets.get(month, (0.0, 0.0))
            buckets[month] = (
                qty + float(r.get("quantity") or 0),
                round(spend + float(r.get("price") or 0), 2),
            )
        return [(m, q, s) for m, (q, s) in sorted(buckets.items())]

    def get_item_price_series(
        self, profile_id: int, term: str = "", alias_id: Optional[int] = None,
    ) -> List[Tuple[str, float]]:
        """Return (date_iso, unit_price) ordered by date for the matched item."""
        rows = self.search_items(profile_id, term, alias_id)
        series: List[Tuple[str, float]] = []
        for r in rows:
            datum = r.get("r_datum")
            if datum and r.get("unit_price"):
                series.append((str(datum)[:10], float(r["unit_price"])))
        return series

    # ------------------------------------------------------------ aggregates

    def get_category_totals(
        self, profile_id: int, year: Optional[int] = None, month: Optional[int] = None,
        vendor_id: Optional[int] = None,
    ) -> List[Tuple[str, str, float]]:
        """Return (category_name, color, total) per category (item-level sums)."""
        sql = [
            """SELECT IFNULL(c.name, 'Nezaradené') AS cname,
                      IFNULL(c.color, '#888888') AS ccolor,
                      ROUND(SUM(ri.price), 2) AS total
                 FROM receipt_items ri
                 JOIN receipts r ON r.id = ri.receipt_id
                 LEFT JOIN categories c ON c.id = ri.category_id
                WHERE r.profile_id = ?"""
        ]
        params: list = [profile_id]
        if year:
            sql.append("AND r.account_year = ?")
            params.append(year)
        if month:
            sql.append("AND r.account_month = ?")
            params.append(month)
        if vendor_id:
            sql.append("AND r.vendor_id = ?")
            params.append(vendor_id)
        sql.append("GROUP BY cname, ccolor ORDER BY total DESC")
        with self._cursor() as cur:
            cur.execute(" ".join(sql), params)
            return [(r["cname"], r["ccolor"], r["total"] or 0.0) for r in cur.fetchall()]

    def get_monthly_totals(self, profile_id: int, year: int) -> List[Tuple[int, float]]:
        """Return (month, total) for a year (receipt-level totals)."""
        with self._cursor() as cur:
            cur.execute(
                """SELECT account_month AS m, ROUND(SUM(celkom), 2) AS total
                     FROM receipts WHERE profile_id = ? AND account_year = ?
                    GROUP BY account_month ORDER BY account_month""",
                (profile_id, year),
            )
            return [(r["m"] or 0, r["total"] or 0.0) for r in cur.fetchall()]

    def get_receipt_years(self, profile_id: int) -> List[int]:
        """Return distinct accounting years present in the profile, ascending.

        Lets the UI offer years outside the default range (e.g. receipts
        scanned from 2024 or earlier, filed by their QR date)."""
        with self._cursor() as cur:
            cur.execute(
                """SELECT DISTINCT account_year AS y FROM receipts
                    WHERE profile_id = ? AND account_year IS NOT NULL
                      AND account_year > 0
                    ORDER BY account_year""",
                (profile_id,),
            )
            return [int(r["y"]) for r in cur.fetchall()]

    def count_uncategorized(self, profile_id: int) -> int:
        """Count items still without a category in the profile."""
        with self._cursor() as cur:
            cur.execute(
                """SELECT COUNT(*) AS n FROM receipt_items ri
                     JOIN receipts r ON r.id = ri.receipt_id
                    WHERE r.profile_id = ? AND ri.category_id IS NULL""",
                (profile_id,),
            )
            return int(cur.fetchone()["n"])

    # ------------------------------------------------------------ aliases / popis

    def get_aliases(self, profile_id: int) -> List[ItemAlias]:
        """Return item aliases for a profile."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM item_aliases WHERE profile_id = ? ORDER BY display_name",
                (profile_id,),
            )
            return [
                ItemAlias(r["id"], r["profile_id"], r["display_name"], r["pattern"])
                for r in cur.fetchall()
            ]

    def add_alias(self, profile_id: int, display_name: str, pattern: str) -> int:
        """Add an item alias."""
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO item_aliases (profile_id, display_name, pattern) "
                "VALUES (?, ?, ?)",
                (profile_id, display_name, pattern),
            )
            return int(cur.lastrowid)

    def delete_alias(self, alias_id: int) -> None:
        """Delete an item alias."""
        with self._cursor() as cur:
            cur.execute("DELETE FROM item_aliases WHERE id = ?", (alias_id,))

    def get_popis_history(self, profile_id: int) -> List[str]:
        """Return saved descriptions for the profile."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT popis FROM popis_history WHERE profile_id = ? ORDER BY popis",
                (profile_id,),
            )
            return [r["popis"] for r in cur.fetchall()]

    def add_popis_history(self, profile_id: int, popis: str) -> None:
        """Remember a description for quick reuse."""
        if not popis.strip():
            return
        with self._cursor() as cur:
            cur.execute(
                "INSERT OR IGNORE INTO popis_history (profile_id, popis) VALUES (?, ?)",
                (profile_id, popis.strip()),
            )

    # ------------------------------------------------------------ settings

    def get_setting(self, key: str, default: str = "") -> str:
        """Return a setting value or the default."""
        with self._cursor() as cur:
            cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cur.fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        """Insert or update a setting."""
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )

    # ------------------------------------------------------------ backup

    def backup_database(self, dest_dir: Path) -> Path:
        """Copy the DB to a timestamped file in dest_dir; return the new path."""
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = dest_dir / f"archiv_blockov_{stamp}.db"
        if self._conn:
            self._conn.commit()
        shutil.copy2(self._path, dest)
        logger.info(f"Záloha DB: {dest}")
        return dest

    @staticmethod
    def _validate_sqlite_file(path: Path) -> None:
        """Raise ValueError unless *path* is a valid Archiv_blockov DB.

        Checks the SQLite file header, the presence of the required tables and
        that the schema version is not newer than this build understands.
        """
        try:
            with open(path, "rb") as fh:
                header = fh.read(16)
        except OSError as exc:
            raise ValueError(f"Súbor sa nedá čítať: {exc}") from exc
        if header[:15] != b"SQLite format 3":
            raise ValueError("Vybraný súbor nie je SQLite databáza.")

        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            names = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            missing = _REQUIRED_TABLES - names
            if missing:
                raise ValueError(
                    "Databáza nemá očakávanú schému (chýbajú tabuľky: "
                    + ", ".join(sorted(missing)) + ")."
                )
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise ValueError(
                    f"Databáza pochádza z novšej verzie aplikácie "
                    f"(verzia schémy {version} > {SCHEMA_VERSION})."
                )
        finally:
            conn.close()

    def restore_database(self, src_file: Path) -> Path:
        """Restore the DB from a backup file, returning the safety-backup path.

        Safety rules: (1) validate the source is a real SQLite DB with the
        expected schema; (2) auto-back up the current DB (timestamped) so the
        restore is reversible; (3) swap the file with the connection closed,
        then reopen. The live DB is never overwritten in place while open.
        """
        src_file = Path(src_file)
        if not src_file.is_file():
            raise FileNotFoundError(f"Súbor neexistuje: {src_file}")
        self._validate_sqlite_file(src_file)

        # 2) reversible safety backup of the current DB
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safety = self._path.with_name(f"{self._path.stem}_pred_obnovou_{stamp}.db")
        if self._conn:
            self._conn.commit()
        if self._path.exists():
            shutil.copy2(self._path, safety)

        # 3) swap with the connection closed, then reopen
        self.disconnect()
        shutil.copy2(src_file, self._path)
        self.connect()
        logger.info(f"DB obnovená z {src_file}; predošlá uložená do {safety}")
        return safety

    # ------------------------------------------------------------ row mappers

    @staticmethod
    def _row_to_profile(r: sqlite3.Row) -> Profile:
        return Profile(
            id=r["id"], name=r["name"], kind=r["kind"],
            vat_enabled=bool(r["vat_enabled"]),
            ico=r["ico"] or "", dic=r["dic"] or "",
        )

    @staticmethod
    def _row_to_vendor(r: sqlite3.Row) -> Vendor:
        return Vendor(
            id=r["id"], profile_id=r["profile_id"],
            ico=r["ico"] or "", dic=r["dic"] or "",
            name=r["name"] or "", address=r["address"] or "",
            default_category_id=r["default_category_id"],
        )

    @staticmethod
    def _row_to_item(r: sqlite3.Row) -> ReceiptItem:
        return ReceiptItem(
            id=r["id"], receipt_id=r["receipt_id"], name=r["name"] or "",
            quantity=r["quantity"] or 0.0, unit_price=r["unit_price"] or 0.0,
            price=r["price"] or 0.0, vat_rate=r["vat_rate"] or 0.0,
            category_id=r["category_id"], is_synthetic=bool(r["is_synthetic"]),
        )

    @staticmethod
    def _row_to_receipt(r: sqlite3.Row) -> Receipt:
        keys = r.keys()
        datum_val = r["datum"]
        parsed_date: Optional[date] = None
        if datum_val:
            try:
                parsed_date = (
                    datum_val if isinstance(datum_val, date)
                    else date.fromisoformat(str(datum_val)[:10])
                )
            except ValueError:
                parsed_date = None
        return Receipt(
            id=r["id"], profile_id=r["profile_id"], vendor_id=r["vendor_id"],
            datum=parsed_date,
            base_0=r["base_0"] or 0.0, base_5=r["base_5"] or 0.0, tax_5=r["tax_5"] or 0.0,
            base_19=r["base_19"] or 0.0, tax_19=r["tax_19"] or 0.0,
            base_23=r["base_23"] or 0.0, tax_23=r["tax_23"] or 0.0,
            zaokruhlenie=r["zaokruhlenie"] or 0.0, celkom=r["celkom"] or 0.0,
            platba=r["platba"] or "hotovost", popis=r["popis"] or "",
            qr_raw=r["qr_raw"] or "", default_category_id=r["default_category_id"],
            account_year=r["account_year"] or 0, account_month=r["account_month"] or 0,
            data_complete=bool(r["data_complete"]),
            sync_attempts=r["sync_attempts"] or 0,
            last_sync_attempt=r["last_sync_attempt"],
            sync_error=r["sync_error"],
            api_data=r["api_data"],
            vendor_name=r["vendor_name"] if "vendor_name" in keys else "",
            category_name=r["category_name"] if "category_name" in keys and r["category_name"] else "",
            category_color=r["category_color"] if "category_color" in keys and r["category_color"] else "",
            category_count=r["category_count"] if "category_count" in keys else 0,
        )
