"""Test QR sample set covering every parse/lookup branch.

Used to validate the eKasa chain before it touches real data. Replace the
placeholder strings with real receipts from your own scans for live testing.
"""

# Each entry: (label, qr_raw, expected_behaviour)
SAMPLES = [
    ("Online QR (full receipt)", "O-XXXXXXXX-XXXXXXXX",
     "parse_qr → full items via API, data_complete = 1"),
    ("Offline OKP (already uploaded)",
     "dfa0da45-0000-0000-0000-000000000000:88820203726400244:260410022154:6452:70.66",
     "offline chain resolves, full items, data_complete = 1"),
    ("Offline not yet uploaded",
     "ffffffff-0000-0000-0000-000000000000:99999999999999999:260101000000:0001:1.00",
     "no items → one synthetic item, data_complete = 0, eligible for re-sync"),
    ("Receipt with zero line items", "O-ITEMLESS-RECEIPT",
     "handled without crashing; synthetic item = total"),
    ("Duplicate (qr already in profile)", "O-XXXXXXXX-XXXXXXXX",
     "duplicate guard warns and asks before saving"),
    ("Malformed / unparseable QR", "not-a-valid-qr",
     "warning + manual entry dialog with recoverable fields"),
]
