"""
Deterministic field normalization (PRD Part 11).

Every function here is pure regex/arithmetic -- no model, no LLM. This is
intentional: unit, currency and date parsing has a finite, well-defined
grammar, and an LLM would add non-determinism (and hallucination risk) to a
task that a dozen lines of regex already solve reliably and reproducibly.
"""

import re
from datetime import datetime

UNIT_ALIASES = {
    "kg": "kg", "kgs": "kg", "kilogram": "kg", "kilograms": "kg",
    "g": "g", "gm": "g", "gms": "g", "grams": "g", "gram": "g",
    "mg": "mg", "milligram": "mg",
    "l": "l", "ltr": "l", "litre": "l", "litres": "l", "liter": "l",
    "ml": "ml", "millilitre": "ml", "milliliters": "ml",
    "pcs": "count", "pieces": "count", "nos": "count", "count": "count", "n": "count",
}

_QUANTITY_RE = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>kgs?|kilograms?|g|gm|gms|grams?|mg|milligram|"
    r"l|ltr|litres?|liters?|ml|millilitre|pcs|pieces|nos|count)\b",
    re.IGNORECASE,
)

_MRP_RE = re.compile(
    r"(?:mrp|m\.r\.p\.?|price)?\s*[:\-]?\s*(?:rs\.?|inr|₹)\s*(?P<value>\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)",
    re.IGNORECASE,
)

# DD/MM/YYYY, DD-MM-YYYY, MM/YYYY, Month YYYY
_DATE_PATTERNS = [
    (re.compile(r"\b(?P<d>\d{1,2})[/\-.](?P<m>\d{1,2})[/\-.](?P<y>\d{2,4})\b"), "DMY"),
    (re.compile(r"\b(?P<m>\d{1,2})[/\-.](?P<y>\d{4})\b"), "MY"),
    (re.compile(
        r"\b(?P<mon>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(?P<y>\d{4})\b",
        re.IGNORECASE), "MonY"),
]

_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
           "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def normalize_quantity(raw_text: str):
    """'Net Qty. 500 g' -> {'value': 500.0, 'unit': 'g'}"""
    match = _QUANTITY_RE.search(raw_text)
    if not match:
        return None
    unit_raw = match.group("unit").lower()
    unit = UNIT_ALIASES.get(unit_raw)
    if unit is None:
        return None
    return {"value": float(match.group("value")), "unit": unit}


def normalize_mrp(raw_text: str):
    """'MRP ₹99/-' or 'Rs. 99.00' -> {'value': 99.0, 'currency': 'INR'}"""
    match = _MRP_RE.search(raw_text)
    if not match:
        return None
    value_str = match.group("value").replace(",", "")
    try:
        value = float(value_str)
    except ValueError:
        return None
    return {"value": value, "currency": "INR"}


def normalize_date(raw_text: str):
    """Returns {'iso': 'YYYY-MM-DD' or 'YYYY-MM', 'precision': 'day'|'month', 'raw': raw_text}
    or None if no recognizable date pattern is found. Deliberately permissive
    on input format (labels are inconsistent) but strict on only returning a
    value when the pattern is unambiguous."""
    for pattern, kind in _DATE_PATTERNS:
        match = pattern.search(raw_text)
        if not match:
            continue
        try:
            if kind == "DMY":
                d, m, y = int(match.group("d")), int(match.group("m")), int(match.group("y"))
                if y < 100:
                    y += 2000
                if not (1 <= m <= 12 and 1 <= d <= 31):
                    continue
                datetime(y, m, min(d, 28) if m == 2 else d, 1)  # sanity check
                return {"iso": f"{y:04d}-{m:02d}-{d:02d}", "precision": "day", "raw": raw_text}
            if kind == "MY":
                m, y = int(match.group("m")), int(match.group("y"))
                if y < 100:
                    y += 2000
                if not (1 <= m <= 12):
                    continue
                return {"iso": f"{y:04d}-{m:02d}", "precision": "month", "raw": raw_text}
            if kind == "MonY":
                mon_str = match.group("mon").lower()[:3]
                m = _MONTHS.get(mon_str)
                y = int(match.group("y"))
                if m is None:
                    continue
                return {"iso": f"{y:04d}-{m:02d}", "precision": "month", "raw": raw_text}
        except (ValueError, KeyError):
            continue
    return None


def looks_like_address_block(raw_text: str) -> bool:
    """Heuristic (not a normalization, but used alongside it): a manufacturer
    declaration usually contains a PIN code and/or state-like tokens."""
    has_pin = bool(re.search(r"\b\d{6}\b", raw_text))
    has_keyword = bool(re.search(
        r"\b(manufactured|packed|marketed|mfg|imported)\s+by\b", raw_text, re.IGNORECASE))
    return has_pin or has_keyword
