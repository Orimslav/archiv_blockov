# Archiv_blockov — Project Specification

## Communication
Always communicate with the user in **Slovak language**.

---

## Project Overview
A desktop **PySide6 (Qt)** application for **archiving Slovak e-kasa receipts (bločky)** scanned via USB QR scanner. Unlike the sibling project `Scan_blocky`, this app has **no client-firm bookkeeping hierarchy**. It is a personal/business receipt archive with:

- **Multiple profiles** (e.g. „Moja domácnosť", „Iná domácnosť", „Moja firma", „Iná firma")
- **Date-driven archiving** — every receipt is filed by the **date read from its QR code**, regardless of when it is scanned (a January receipt scanned in October lands in January)
- **User-defined categories** assigned at **item level** (whole-receipt default, overridable per item)
- **Universal VAT mode** — each profile chooses whether to compute the VAT breakdown (firm) or stay simple (household)
- **Rich outputs** — PDF reports, Excel/CSV export, per-category summaries, and an in-app dashboard with charts
- **Item-level search & reports** — search across receipt line items (e.g. „chlieb") and build consumption reports per item over time (quantity + spend, per month/year, with a price-trend chart)
- **View any stored receipt** — every saved receipt can be reopened from the DB and re-rendered as a full document (offline-capable, from stored `api_data`)
- **Full HD–optimized, responsive UI** — designed primarily for **1920×1080**; layouts resize gracefully and never clip. Visually in the *spirit* of `Scan_blocky` (same dark colour family) but **not a pixel-for-pixel copy** — prioritise clarity, usability and a clean modern layout

**Status: specification — to be implemented.**

### Relationship to `Scan_blocky`
This is a **separate project** in `C:\Webapp\Archiv_blockov\`. It **reuses logic and assets** (not UI) from `C:\Webapp\Scan_blocky\`:

| Reused from Scan_blocky | What |
|---|---|
| `core/ekasa_parser.py` | eKasa QR parsing + API (online + offline FIELDS lookup), VAT extraction, `api_data` capture. **Extended** with `extract_items()`. |
| `ekasa_offline.py` | **Offline receipt lookup that already returns full items** once the cash register has uploaded the receipt. Its 3-method fallback chain (FIELDS → receiptId=full QR → receiptId=OKP) and async `searchUuid` polling are the reference for the offline path. |
| `ekasa_raw.py` | Reference for the **full receipt field map** — exact item keys (`items`/`receiptItems`, `name`/`itemName`, `quantity`/`qty`, `unitPrice`, `price`/`totalPrice`, `vatRate`), org, VAT summary, payments. |
| `core/company_lookup.py` | registeruz.sk vendor lookup by IČO (`lookup_by_ico` → `CompanyInfo`). Copied as-is. |
| `assets/logo.png`, `assets/logo.ico` | Logo. Copied as-is. |
| `ui/constants.py` colour palette | Colour values reused — applied as **Qt QSS**, not tkinter. |
| `core/pdf_export.py` | ReportLab font registration + A4 pattern. Adapted to the new schema. |
| `core/database.py` migration pattern | `ALTER TABLE … ADD COLUMN` inside `try/except`; never recreate tables. |

> The UI is built **from scratch in PySide6** — the new structure (profiles, categories, items, item search, dashboard) differs too much to port tkinter widgets. The reuse is **logic + data + style values**, not widgets.

---

## Directory Structure
```
C:\Webapp\
├── Scan_blocky\        ← sibling app — source of styles, logo, eKasa/registeruz API
└── Archiv_blockov\     ← this project
```

```
Archiv_blockov/
├── main.py                  # entry point — init DB, optional login, show MainWindow
├── ui/
│   ├── main_window.py       # QMainWindow — root window, scanner, layout, tabs, toolbar
│   ├── profile_panel.py     # left sidebar — list of profiles + add/edit/delete
│   ├── receipt_view.py      # QTableView + model/proxy — receipt list, sort/filter
│   ├── receipt_detail.py    # ReceiptDetailDialog — header + items, per-item category, view-from-DB
│   ├── item_search.py       # ItemSearchView — search line items + consumption report + price chart
│   ├── category_manager.py  # CategoryManagerDialog — CRUD categories per profile
│   ├── alias_manager.py     # AliasManagerDialog — CRUD item aliases (report grouping)
│   ├── dashboard.py         # DashboardWidget — QtCharts (monthly + per-category)
│   ├── dialogs.py           # ProfileDialog, ManualReceiptDialog, ExportDialog, helpers
│   ├── scanner.py           # ScannerInput — USB scanner capture (hidden QLineEdit)
│   ├── style.py             # build_qss() — QSS string from constants palette
│   └── constants.py         # colours, fonts, sizes (ported values from Scan_blocky)
├── core/
│   ├── database.py          # Database — all SQLite operations + migrations
│   ├── ekasa_parser.py      # parse_qr(), fetch_receipt_detail(), extract_items()  (reused + extended)
│   ├── ekasa_offline.py     # offline lookup (3-method chain) returning full receipt+items  (reused)
│   ├── company_lookup.py    # lookup_by_ico()  (reused as-is)
│   ├── pdf_export.py         # export_period_pdf(), export_category_summary_pdf(),
│   │                         #   export_item_report_pdf(), export_vat_summary_pdf(), export_receipt_detail_pdf()
│   └── excel_export.py       # export_period_xlsx(), export_period_csv(), export_item_report_xlsx()  (NEW — openpyxl)
├── models/
│   └── models.py            # dataclasses: Profile, Category, Vendor, Receipt, ReceiptItem, ItemAlias, ParsedReceipt, VatBreakdown
├── assets/
│   ├── logo.png
│   └── logo.ico
└── data/
    └── archiv_blockov.db    # SQLite database
```

---

## Data Hierarchy

```
PROFILE (Moja domácnosť / Moja firma / …)
└── RECEIPT (bloček — filed by QR date)
    └── RECEIPT ITEMS (položky bločku — each with its own category; searchable)
```

- One profile contains **many receipts**, filed by **QR date** (`account_year` / `account_month` derived from `datum`)
- Each receipt contains **many items** (parsed from eKasa `api_data` — available for offline receipts too once uploaded)
- **Every item has a category** — defaults to the receipt's chosen category, individually overridable
- **Items are first-class searchable data** — the item-search view and consumption reports query `receipt_items` directly
- **Vendor** info is stored on each receipt (and cached in a lightweight `vendors` table per profile) for grouping/filtering and **auto-categorization** (learned IČO → default category)

---

## Profiles

The **left sidebar** lists profiles. The active profile scopes everything (receipts, categories, vendors, items, exports, dashboard).

### Profile fields
- `name` — display name (e.g. „Moja domácnosť")
- `kind` — `household` | `firm`
- `vat_enabled` — bool; `firm` defaults to `True`, `household` to `False` (user can change)
- `ico`, `dic` — optional, only meaningful for `firm` profiles (own identification; not required)

### Behaviour
- **Add / Edit / Delete** profile via sidebar buttons and right-click context menu (Qt `QMenu`)
- Deleting a profile asks for confirmation; cascades to its receipts, items, categories, vendors, aliases
- Switching profile reloads the receipt view, item search, category list and dashboard
- At least one profile must exist — on first run, prompt to create the first profile (suggest „Moja domácnosť")
- Remember last active profile in `settings.active_profile_id`

### VAT mode (per profile)
- `vat_enabled = True` (firm): receipt table & PDFs show the **full VAT breakdown** columns (0/5/19/23 % base + tax, rounding) — same column-visibility rules as `Scan_blocky` (a rate's columns appear only if some receipt has a non-zero value; 0 % base always shown)
- `vat_enabled = False` (household): VAT columns **hidden**; table shows Dátum · Predajca · Kategória · Celkom · Platba · Popis
- The DB **always stores** VAT columns (0 when household) — the toggle only affects display/export, so a profile can be switched without data loss

---

## Categories

Categories are **per-profile** (a household's categories differ from a firm's).

### Category fields
- `name` (e.g. „Potraviny", „Drogéria", „Alkohol", „Kancelárske potreby", „Reštaurácie", „PHM")
- `color` — hex string, used for chips in the table and dashboard slices

### Management (`CategoryManagerDialog`)
- CRUD list of categories for the active profile
- On **new profile creation**, seed a small default set (editable/deletable): „Potraviny", „Drogéria", „Reštaurácie", „Doprava", „Ostatné"
- A built-in **„Nezaradené"** (uncategorized) fallback is always available — implemented as `category_id IS NULL`, shown with a neutral grey chip

### Item-level categorization with whole-receipt default
1. When a receipt is saved, the user picks **one category for the whole receipt** (`receipts.default_category_id`)
   - If the vendor has a **learned default** (`vendors.default_category_id`), it is **preselected** automatically
   - Quick keyboard assignment: number keys map to the first N categories during the save dialog
2. **All items inherit** that category on insert (`receipt_items.category_id = default_category_id`)
3. Later, in `ReceiptDetailDialog`, the user can **override the category per item** via an inline dropdown
4. A **quick action** „Celý bloček → kategória X" sets all items at once
5. **Summaries, item reports and the dashboard are computed at item level** (`SUM(receipt_items.price) GROUP BY category_id`), so a split receipt contributes correct amounts to multiple categories

### Auto-categorization (learning)
- When a receipt's default category is chosen, store it on the vendor: `vendors.default_category_id = chosen`
- Next time a receipt from the same IČO is scanned, that category is preselected (always overridable)

### „Nezaradené" review queue *(suggestion)*
- A filter / sidebar badge showing the count of receipts (or items) still uncategorized, so the user can quickly clean them up

---

## Receipt View (QTableView)

Implemented with **`QAbstractTableModel` + `QSortFilterProxyModel`** so sorting and filtering are native.

### Columns (firm / `vat_enabled=True`)
| Dátum | Predajca | Kategória | 0% Základ | 5% Z | 5% D | 19% Z | 19% D | 23% Z | 23% D | Zaokr. | Celkom | Platba | Popis |

### Columns (household / `vat_enabled=False`)
| Dátum | Predajca | Kategória | Celkom | Platba | Popis |

### Column rules
- **Kategória cell** shows the receipt-level default category as a coloured chip; if items span multiple categories, show „zmiešané" + chip count
- VAT column visibility identical to `Scan_blocky` rules (non-zero data gates 5/19/23 % and rounding; 0 % base always shown in firm mode)
- **Platba** — inline toggle Hotovosť / Karta, saves immediately
- **Popis** — editable inline; right-click → history dropdown (per-profile `popis_history`)
- **Bottom summary rows**: SPOLU (accent), Hotovosť (green), Karta (purple)
- **Incomplete badge** — receipts still missing real items (offline, not yet uploaded) show a small „neúplný" marker (see Re-sync below)

### Sorting & default order
- Default sort: `datum ASC, id ASC` (chronological; same-day by insert order; NULL dates last)
- Clicking any column header re-sorts via the proxy model
- **Receipts are always filed by `datum`** — out-of-order scans appear in their correct date position automatically

### Filtering toolbar
- **Rok** (2025–2035 fixed range) + **Mesiac** dropdowns — filter by accounting period (derived from `datum`)
- **Kategória** dropdown — receipts containing at least one item in the selected category
- **Predajca** dropdown — filter by vendor
- **Hľadať** field — fulltext over vendor name, popis, total, date
- Filters combine (logical AND) via the proxy model

### Navigation
- Scrolling handled natively by `QTableView`
- After scan/save, the new receipt row is **selected and scrolled into view**
- Arrow keys move selection; `Delete` removes the selected receipt (with confirm)
- **Double-click / Enter / right-click → Zobraziť doklad** opens the stored receipt (see below)

---

## Receipt Detail — view any stored receipt (`ReceiptDetailDialog`)

A core feature: **any receipt already in the DB can be reopened and shown as a full document**, offline.

- Opens via double-click, Enter, or right-click → „Zobraziť doklad" on a receipt row
- Renders **from stored `api_data`** (no network needed); falls back to DB column values if `api_data` is absent
- Sections: Doklad, Predajca, Pokladňa, DPH súhrn (firm mode), OKP
- **Položky table** with an **inline category dropdown per row** (`QStyledItemDelegate` + `QComboBox`)
- „Celý bloček → kategória X" quick-action button
- „Aktualizovať z eKasa" button — re-fetches live (useful for incomplete offline receipts)
- „Exportovať doklad (PDF)" → `export_receipt_detail_pdf()`
- Saving category overrides updates `receipt_items.category_id` immediately

---

## Item Search & Consumption Reports (`ui/item_search.py`)

Dedicated view (own tab) for **searching and reporting on line items** — e.g. „koľko som minul na chlieb tento rok".

### Search
- **Položka** search field — matches `receipt_items.name` (case-insensitive, diacritics-insensitive `LIKE %term%`)
- **Name normalization** — SQLite `LIKE` is case-insensitive only for ASCII, so „chlieb" would not match „CHLIEB" with diacritics. Normalize both sides (lowercase, strip diacritics via `unicodedata.NFKD`, collapse repeated whitespace) before matching. Implement once as a helper (`core/text_utils.py::normalize_name()`) and register it as a SQLite function (`connection.create_function`) so the same normalization is usable inside SQL (`WHERE normalize_name(name) LIKE normalize_name(:term)`) and in alias matching. This also makes alias `pattern` matching diacritics/case tolerant for free.
- Optional **alias** selection — pick a predefined item alias („Chlieb") to match all its patterns at once
- Period filter (Rok / Mesiac) + category filter, combinable
- **Results table**: Dátum · Predajca · Položka · Množstvo · Jedn. cena · Cena · Kategória — one row per matching item, sortable
- Totals row: total quantity + total spend for the current result set

### Consumption report
- For the searched item/alias: aggregate **per month** (and per year) — quantity and spend
- **Mini charts (QtCharts)**:
  - Bar chart — spend per month
  - Line chart — **unit-price trend over time** *(suggestion)* (how the item's price evolved)
- Export the report to **PDF** (`export_item_report_pdf`) and **Excel** (`export_item_report_xlsx`)

### Item aliases *(suggestion — `AliasManagerDialog`)*
- Item names on receipts vary („Chlieb cel.", „CHLIEB 500g", „Chlieb tmavý")
- An alias maps a **display name** („Chlieb") to one or more **patterns** matched against item names
- Reports grouped by alias sum all matching variants together
- Without aliases, plain „contains" search still works — aliases are an optional convenience

---

## QR Scanner Input (USB — acts as keyboard)

Implemented in `ui/scanner.py` as a `ScannerInput` helper:

- A **hidden `QLineEdit`** (zero size / off-screen) holds focus as the permanent scanner buffer
- The scanner types into it; `returnPressed` triggers `on_scan(qr_raw)`
- An **application-level `eventFilter`** reclaims focus to the buffer shortly after clicks on non-text widgets (mirrors `Scan_blocky`'s click→`after()` approach using `QTimer.singleShot(50, …)`)
- Real text inputs keep focus while the user types manually — the filter checks `QApplication.focusWidget()` type before reclaiming
- Buffer-empty guard on key handlers so `Delete` / arrow keys never interfere with an in-progress scan

### eKasa data extracted (online **and** offline)
Both online and offline receipts return the **full document including line items** via the eKasa API. Offline receipts (`OKP:…`) are uploaded by the cash register as soon as it regains internet, after which the FIELDS lookup returns everything.

Extracted per receipt:
- Vendor: `ico`, `dic`, `nazov`, `adresa`
- `datum`, `platba`, VAT breakdown (0/5/19/23 %), `zaokruhlenie`, `celkom`
- **`items`** — list of `{name, quantity, unit_price, price (total incl. VAT), vat_rate}`
- Full raw API response stored in `receipts.api_data` (JSON) for offline re-render

### Offline lookup — reuse `ekasa_offline.py`
Port its proven flow into `core/ekasa_offline.py`:
1. Parse `OKP:CRC:YYMMDDHHMMSS:SEQ:SUMA` (`parts[1]` = cash-register code, **not** vendor IČO)
2. **Method 1 — FIELDS**: `{okp, cashRegisterCode, receiptNumber, totalAmount, issueDateFormatted (DD.MM.YYYY HH:MM:SS)}`
3. **Method 2** — `{receiptId: <full QR string>}`
4. **Method 3** — `{receiptId: <OKP>}`
5. Handle async responses by polling `searchUuid` (with/without `bucket`)
6. On success the returned `receipt` contains `items` → full data, no manual entry needed

### Item extraction — `extract_items(api_receipt) -> List[ReceiptItem]`
New public function in `ekasa_parser.py` (field map per `ekasa_raw.py`):
- `items = receipt.get("items") or receipt.get("receiptItems") or []`
- `name = item.get("name") or item.get("itemName")`
- `quantity = item.get("quantity") or item.get("qty") or 1`
- `unit_price = item.get("unitPrice")`
- `price = item.get("price") or item.get("totalPrice")` (line total incl. VAT)
- `vat_rate = item.get("vatRate") or 0`
- Returns `ReceiptItem` list (without `id`/`receipt_id`, filled on insert)

### Incomplete / not-yet-uploaded fallback
- If at scan time the API returns **no items** (cash register hasn't uploaded yet), save the receipt with **one synthetic item** = the total in the chosen category, and mark `receipts.data_complete = 0`
- This is the **exception, not the norm** — most offline receipts return full items shortly after

### Re-sync incomplete receipts *(suggestion)*
- A background/manual job **„Aktualizovať neúplné bločky"** re-queries eKasa for receipts where `data_complete = 0`
- On success: replace the synthetic item with the real items + VAT breakdown, set `data_complete = 1`, clear `sync_error`, refresh `api_data`
- Runs on app start (if `settings.auto_refresh_incomplete = 1`) and via a toolbar button; always in a worker thread
- **Bounded retries** — each attempt increments `receipts.sync_attempts` and stamps `last_sync_attempt`; on failure store the message in `sync_error`. The auto-refresh on start skips receipts past a cap (`settings.max_sync_attempts`, default 10) so a never-uploaded receipt does not hammer the eKasa API on every launch. The manual toolbar button always forces a retry regardless of the cap.

### Scanning flow
1. Scan QR → `parse_qr(qr_raw)` → `ParsedReceipt` (+ `api_data`)
2. Resolve vendor by IČO under the active profile; if unknown, `lookup_by_ico` → create `vendors` row
3. Preselect default category from `vendors.default_category_id` (or „Nezaradené")
4. Quick confirm dialog (date, vendor, total, category; number-key category shortcuts) → on save:
   - insert `receipts` row (`receipt.id` captured; set `data_complete`)
   - insert `receipt_items` (from `extract_items`, or one synthetic item), all with the chosen category
   - learn `vendors.default_category_id`
5. Reload view, select & scroll to the new receipt
6. **Duplicate guard**: if `qr_raw` already exists in the profile, warn and ask before saving

### Manual entry (`ManualReceiptDialog`)
- For genuinely unreadable receipts or the „Pridať ručne" button
- Fields: dátum, predajca (existing or new), kategória, celkom, platba, popis; VAT fields only in firm mode
- Saves a receipt with a single synthetic item in the chosen category (`data_complete = 0` if no QR)

---

## GUI Layout (Full HD, responsive)

```
┌────────────────────────────────────────────────────────────────────┐
│ [Logo] Archív bločkov               Profil: ▼   [● Skener aktívny]  │
├──────────────┬─────────────────────────────────────────────────────┤
│ PROFILY      │ [ Bločky ] [ Položky ] [ Dashboard ]   ← QTabWidget  │
│              │                                                     │
│ • M. domácn. │ Rok ▼ Mesiac ▼ Kategória ▼ Predajca ▼  Hľadať [___] │
│ • Iná domác. │                                                     │
│ • Moja firma │ QTableView (receipts)                  ▲           │
│              │   …                                    │ scroll    │
│ ──────────── │   …                                    ▼           │
│ Nezaradené 3 │ Súčty: SPOLU / Hotovosť / Karta                    │
│ [+ Profil]   │ [Pridať ručne][Upraviť][Vymazať] [Kategórie…]      │
│              │ [Aktualizovať neúplné] [Export ▼] [Zálohovať DB]   │
│              ├─────────────────────────────────────────────────────┤
│              │ Posledný bloček: LIDL  28.70 €  Potraviny           │
└──────────────┴─────────────────────────────────────────────────────┘
```

### UI design principles
- **Target 1920×1080**, but **fully responsive**: use `QSplitter` (sidebar | content), `QVBoxLayout`/`QHBoxLayout`/`QGridLayout` with stretch factors, and size hints — never hardcode pixel geometry
- **Minimum window size** ~1280×720; below that, panels stay usable (scroll, not clip)
- Sidebar width adjustable via the splitter; tables expand to fill remaining space
- High-DPI handled by Qt automatically; fonts scale via `QFont` point sizes
- Visual language: same dark colour family as `Scan_blocky` (via QSS), but a cleaner, modern, user-friendly layout — **not** required to match pixel-for-pixel
- Three tabs: **Bločky** (receipt view), **Položky** (item search + reports), **Dashboard** (charts)
- Right-click menus (`QMenu`): profile → Upraviť/Vymazať; receipt → Zobraziť doklad/Kopírovať ID/Vymazať

---

## Outputs / Exports

### PDF (`core/pdf_export.py`, ReportLab, A4 portrait)
- **`export_period_pdf`** — receipts for the selected period/filters; columns follow VAT mode; SPOLU/Hotovosť/Karta totals
- **`export_category_summary_pdf`** — per-category totals for the period (item-level sums) + grand total
- **`export_item_report_pdf`** — consumption report for a searched item/alias: per-month quantity + spend, totals
- **`export_vat_summary_pdf`** *(suggestion, firm mode)* — VAT recap per rate for the period (DPH podklad)
- **`export_receipt_detail_pdf`** — single receipt with items and (firm) VAT summary
- Slovak diacritics: register a TTF from `C:/Windows/Fonts` (arial/calibri/tahoma/verdana → Helvetica fallback)
- Auto-open with `os.startfile()` after creation

### Excel / CSV (`core/excel_export.py`, openpyxl)
- **`export_period_xlsx`** — one row per receipt (or optionally per item), all VAT columns in firm mode, category column; summary sheet with per-category totals
- **`export_period_csv`** — same data, UTF-8 BOM, `;` separator (Slovak locale)
- **`export_item_report_xlsx`** — item consumption report (monthly breakdown + totals)

### Dashboard (`ui/dashboard.py`, QtCharts)
- **Bar chart** — spending per month (current year, active profile)
- **Pie chart** — spending per category (current period/filter), slice colours from `categories.color`
- **KPI labels** — total spent, receipt count, top category
- Respects the active profile and period/category filters

### Database backup & restore *(suggestion)*
- „Zálohovať DB" toolbar action copies `data\archiv_blockov.db` to a timestamped file in a chosen folder (`settings.db_backup_dir`); important for a multi-year archive
- **„Obnoviť/Importovať DB"** — restores from a chosen backup file. Safety rules: (1) confirm with a clear warning that current data will be replaced; (2) **auto-backup the current DB first** (timestamped, so restore is reversible); (3) validate the chosen file is a real SQLite DB with the expected schema (check `PRAGMA user_version` and key tables) before swapping; (4) replace the file with the connection closed, then reopen and reload the UI. Never overwrite the live DB in place while a connection is open.

---

## Database (SQLite)

File: `C:\Webapp\Archiv_blockov\data\archiv_blockov.db`
Created/migrated automatically in `database.py::_run_migrations()`.
**Always use `ALTER TABLE … ADD COLUMN` inside `try/except` for migrations — never recreate tables.**

```sql
CREATE TABLE profiles (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'household',   -- 'household' | 'firm'
    vat_enabled INTEGER NOT NULL DEFAULT 0,   -- 0/1
    ico TEXT DEFAULT '',
    dic TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE categories (
    id INTEGER PRIMARY KEY,
    profile_id INTEGER REFERENCES profiles(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    color TEXT DEFAULT '#4a9eff',
    UNIQUE(profile_id, name)
);

CREATE TABLE vendors (
    id INTEGER PRIMARY KEY,
    profile_id INTEGER REFERENCES profiles(id) ON DELETE CASCADE,
    ico TEXT,
    dic TEXT,
    name TEXT,
    address TEXT,
    default_category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    UNIQUE(profile_id, ico)
);

CREATE TABLE receipts (
    id INTEGER PRIMARY KEY,
    profile_id INTEGER REFERENCES profiles(id) ON DELETE CASCADE,
    vendor_id INTEGER REFERENCES vendors(id) ON DELETE SET NULL,
    datum DATE,
    base_0 REAL DEFAULT 0,
    base_5 REAL DEFAULT 0,
    tax_5 REAL DEFAULT 0,
    base_19 REAL DEFAULT 0,
    tax_19 REAL DEFAULT 0,
    base_23 REAL DEFAULT 0,
    tax_23 REAL DEFAULT 0,
    zaokruhlenie REAL DEFAULT 0,
    celkom REAL,
    platba TEXT DEFAULT 'hotovost',
    popis TEXT,
    qr_raw TEXT,
    default_category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    account_year INTEGER,
    account_month INTEGER,
    data_complete INTEGER DEFAULT 1,  -- 0 = items not yet retrieved (offline not uploaded)
    sync_attempts INTEGER DEFAULT 0,    -- re-sync tries so far (incomplete receipts)
    last_sync_attempt TIMESTAMP,        -- when re-sync was last attempted
    sync_error TEXT,                    -- last re-sync failure message (NULL = none)
    api_data TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE receipt_items (
    id INTEGER PRIMARY KEY,
    receipt_id INTEGER REFERENCES receipts(id) ON DELETE CASCADE,
    name TEXT,
    quantity REAL DEFAULT 1,
    unit_price REAL DEFAULT 0,
    price REAL DEFAULT 0,            -- line total incl. VAT
    vat_rate REAL DEFAULT 0,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    is_synthetic INTEGER DEFAULT 0, -- 1 = placeholder = whole-receipt total (no real items yet)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE item_aliases (
    id INTEGER PRIMARY KEY,
    profile_id INTEGER REFERENCES profiles(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,     -- e.g. "Chlieb"
    pattern TEXT NOT NULL,          -- LIKE pattern matched against receipt_items.name
    UNIQUE(profile_id, pattern)
);

CREATE TABLE popis_history (
    id INTEGER PRIMARY KEY,
    profile_id INTEGER REFERENCES profiles(id) ON DELETE CASCADE,
    popis TEXT NOT NULL,
    UNIQUE(profile_id, popis)
);

CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
```

### Indexes
Created in `_run_migrations()` (idempotent `CREATE INDEX IF NOT EXISTS`). Required for fast filtering and item search at multi-year scale:
```sql
CREATE INDEX IF NOT EXISTS idx_receipts_profile_period ON receipts(profile_id, account_year, account_month);
CREATE INDEX IF NOT EXISTS idx_receipts_profile_datum  ON receipts(profile_id, datum);
CREATE INDEX IF NOT EXISTS idx_receipts_vendor         ON receipts(vendor_id);
CREATE INDEX IF NOT EXISTS idx_items_receipt           ON receipt_items(receipt_id);
CREATE INDEX IF NOT EXISTS idx_items_category          ON receipt_items(category_id);
CREATE INDEX IF NOT EXISTS idx_items_name              ON receipt_items(name);
CREATE INDEX IF NOT EXISTS idx_vendors_profile_ico     ON vendors(profile_id, ico);
```

### Migration versioning
- Keep the `Scan_blocky` pattern — idempotent `ALTER TABLE … ADD COLUMN` / `CREATE INDEX IF NOT EXISTS` inside `try/except`; **never recreate tables**.
- **Additionally** track `PRAGMA user_version` as a guard for ordered/data migrations (not just blind column adds): read it at start, run only the steps above the stored version, then bump it. SQLite-native, no extra table needed.
- The two layers complement each other: idempotent DDL makes re-runs safe; `user_version` gates one-off data transforms.

### Settings keys
| key | popis |
|-----|-------|
| `password_hash` | optional bcrypt hash (if login enabled) |
| `active_profile_id` | last selected profile |
| `ui_scaling` | optional UI scale factor |
| `auto_refresh_incomplete` | 0/1 — re-fetch incomplete receipts on start |
| `max_sync_attempts` | re-sync attempt cap for auto-refresh (default 10) |
| `db_backup_dir` | last chosen backup folder |

### Key DB methods (indicative)
```python
db.get_profiles() -> List[Profile]
db.add_profile(p) / db.update_profile(p) / db.delete_profile(id)
db.get_categories(profile_id) -> List[Category]
db.add_category(...) / db.update_category(...) / db.delete_category(id)
db.get_or_create_vendor(profile_id, parsed) -> Vendor
db.set_vendor_default_category(vendor_id, category_id)
db.insert_receipt(receipt) -> int
db.insert_items(receipt_id, items: List[ReceiptItem])
db.replace_items(receipt_id, items)        # used by re-sync
db.set_receipt_complete(receipt_id, complete: bool, api_data: str)
db.set_item_category(item_id, category_id)
db.set_receipt_category(receipt_id, category_id)   # cascades to its items
db.get_receipts(profile_id, year, month, category_id=None, vendor_id=None, search="") -> List[Receipt]
db.get_incomplete_receipts(profile_id) -> List[Receipt]
db.search_items(profile_id, term="", alias_id=None, year=None, month=None, category_id=None) -> List[ReceiptItem]
db.get_item_monthly_report(profile_id, term_or_alias, year) -> List[Tuple[month, qty, spend]]
db.get_item_price_series(profile_id, term_or_alias) -> List[Tuple[date, unit_price]]
db.get_category_totals(profile_id, year, month) -> List[Tuple[category, total]]
db.get_monthly_totals(profile_id, year) -> List[Tuple[month, total]]
db.get_aliases(profile_id) / db.add_alias(...) / db.delete_alias(id)
db.count_uncategorized(profile_id) -> int
db.record_sync_attempt(receipt_id, error: str | None)   # increments sync_attempts, stamps last_sync_attempt, sets sync_error
db.backup_database(dest_dir) -> Path
db.restore_database(src_file) -> None    # auto-backs up current DB, validates src, swaps with connection closed
db.get_setting(key, default="") / db.set_setting(key, value)
```

---

## Login (optional)
Carry over the `Scan_blocky` bcrypt login pattern **only if the user wants password protection**. If enabled, reuse `hash_password` / `verify_password`, lockout logic, and the admin-reset flow. Default: **no login** unless requested.

---

## PySide6 — Key Implementation Decisions

### Styling
- `ui/style.py::build_qss()` returns a QSS string built from the `constants.py` palette (ported from `Scan_blocky`: `CLR_BG_MAIN=#1a1a2e`, `CLR_ACCENT=#4a9eff`, etc.), applied via `app.setStyleSheet(...)`
- Logo loaded as `QPixmap` from `assets/logo.png`

### Tables
- `QAbstractTableModel` subclass per view; wrap in `QSortFilterProxyModel` for sorting + combined filtering
- Custom `QStyledItemDelegate` for the inline category `QComboBox` and coloured category chips

### Charts
- `QtCharts` (`QChart`, `QBarSeries`, `QPieSeries`, `QLineSeries`) embedded via `QChartView`

### Threading
- All eKasa API calls (scan, detail re-fetch, re-sync) run in a `QThread`/`QThreadPool` worker; UI updates via signals — **never block the GUI thread**

### Responsive layout
- `QSplitter` for sidebar|content; layouts with stretch factors; size hints; min window ~1280×720; no hardcoded geometry (see UI design principles)

### Scanner focus
- Hidden `QLineEdit` buffer + application `eventFilter` + `QTimer.singleShot(50, reclaim)` after non-text clicks

---

## Implementation Order (MVP first)

The specification is broad — build in dependency layers and ship a working core before the extras. Recommended order:

1. **DB + models + migrations** — schema above, `PRAGMA user_version` guard, indexes, dataclasses in `models.py`.
2. **QR parser + offline chain + save** — port `ekasa_parser.py` (+ `extract_items()`) and `ekasa_offline.py` (3-method chain + `searchUuid` polling). **Build the test QR sample set here** (see below) — the offline path cannot be reliably debugged without it. Includes vendor resolve + synthetic-item fallback for not-yet-uploaded receipts.
3. **Receipt view** — `QTableView` + model/proxy, filters, totals rows, profiles sidebar, scanner input.
4. **Receipt detail + item categories** — `ReceiptDetailDialog`, inline category delegate, per-item override, „celý bloček → kategória".
5. **Then the extras** — start with **one** export (period CSV or simple PDF), then dashboard, item search + consumption reports, aliases, re-sync UI, backup/restore.

> Keep the MVP narrow: profiles → scan → save → receipt list → detail with categories → one export. Everything else layers on top without schema changes (columns/indexes are already provisioned above).

## Test QR samples

Maintain a small fixture set (e.g. `tests/qr_samples.py` or a dev-only menu) covering every parse/lookup branch — needed to validate the eKasa chain before it touches real data:

| Sample | Expected behaviour |
|---|---|
| **Online QR** (full receipt available) | `parse_qr` → full items via API, `data_complete = 1` |
| **Offline `OKP:…`** (already uploaded) | offline chain resolves, full items returned, `data_complete = 1` |
| **Offline not yet uploaded** | no items → save one synthetic item, `data_complete = 0`, eligible for re-sync |
| **Receipt with zero line items** (valid but itemless) | handled without crashing; synthetic item = total |
| **Duplicate** (`qr_raw` already in profile) | duplicate guard warns and asks before saving |
| **Malformed / unparseable QR** | warning + manual entry dialog with whatever fields were recoverable |

## Build / Distribúcia

### PyInstaller — single-file exe
```
cd C:\Webapp\Archiv_blockov
venv\Scripts\pyinstaller archiv_blockov.spec --clean
```
- Onefile, no console, icon `assets/logo.ico`
- PySide6 exe is larger (~50–80 MB); collect QtCharts plugin
- Keep `runtime_tmpdir='.'` (same rationale as `Scan_blocky`: avoids the Windows DLL-lock error dialog on close)

### Frozen vs script paths
`main.py` distinguishes frozen/script mode (same pattern as `Scan_blocky`):
- Frozen: `_ROOT = Path(sys.executable).parent` — DB + log next to the exe
- Script: `_ROOT = Path(__file__).parent`
- DB auto-created at `<exe dir>\data\archiv_blockov.db`

### Distribúcia
**Manuálna** — developer sends the exe; **no auto-updater** (same policy as `Scan_blocky`).

---

## Dependencies
```
PySide6        # UI framework (Qt) + QtCharts — replaces customtkinter/tkinter
Pillow         # logo handling if needed
bcrypt         # optional login
reportlab      # PDF export
openpyxl       # Excel export (NEW)
requests       # registeruz.sk + eKasa offline lookup
urllib3        # SSL warning suppression
pyinstaller    # build (dev only)
sqlite3        # built-in
```
> `ekasa_parser.py` uses stdlib `urllib` for the eKasa API (ported as-is); `ekasa_offline.py` uses `requests`; `company_lookup.py` uses `requests`.

---

## Error Handling
- QR parse error → warning + manual entry dialog (date/total prefilled when available)
- Offline QR → FIELDS → receiptId(full) → receiptId(OKP) chain; on success full items returned
- Offline not yet uploaded → save with synthetic item, `data_complete=0`, retry via re-sync
- registeruz.sk unreachable → allow manual vendor entry
- Duplicate receipt (same `qr_raw` in profile) → warn, confirm before saving
- eKasa API HTTP 702 „Zlé vstupné hodnoty" → wrong field names/format (see `Scan_blocky` FIELDS docs)
- Network calls must never freeze the UI — always threaded

---

## Coding Standards

### Language rules
- All **code identifiers** (variables, functions, classes, constants, DB columns, comments) → **English**
- All **GUI labels, buttons, messages, errors, tooltips** → **Slovak**

### Python best practices
- PEP 8, type hints on all signatures, English docstrings on classes and public methods
- No bare `except:` — always name the exception
- `with` for DB connections and file I/O
- `pathlib.Path` for all paths
- Monetary values: REAL in DB, **always `round(x, 2)` before summing/comparing/exporting** (avoids float drift in totals); 2 decimals in display
- Dates: ISO `YYYY-MM-DD` in DB, `DD.MM.YYYY` in display
- `updated_at` on `receipts` / `receipt_items` is refreshed on every UPDATE (set it explicitly in the write methods — SQLite does not auto-update it)
- Never block the Qt GUI thread on network/DB — use worker threads + signals
```