"""Text utilities — diacritics/case-insensitive name normalization.

Used both in Python and registered as a SQLite function so the same
normalization applies in ``WHERE normalize_name(name) LIKE normalize_name(:term)``
and in alias-pattern matching.
"""

import re
import unicodedata
from typing import Optional

_WS_RE = re.compile(r"\s+")


def normalize_name(value: Optional[str]) -> str:
    """Lowercase, strip diacritics, collapse whitespace.

    Returns an empty string for ``None``. Used for diacritics- and
    case-insensitive matching of item names and alias patterns.
    """
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = _WS_RE.sub(" ", text).strip()
    return text
