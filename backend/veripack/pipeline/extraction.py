"""
Field extraction (PRD Part 10).

Input: OCR lines (word regions grouped by tesseract's line_num, see ocr.py).
Output: a list of ExtractedField-shaped dicts, each traceable back to the
OCR text and bounding box it came from -- "every extracted value must be
traceable to OCR evidence" (PRD Part 10) is enforced structurally here: a
field is never emitted without a source line and bounding box attached.

This module uses regex + keyword layout heuristics only. No LLM call is
made here in this build (there is no network access to an LLM API in this
sandbox either). The PRD's LLM-assistance boundary (synonym matching /
generic-name interpretation / explanation wording, never the compliance
decision) is documented in docs/AI_PIPELINE.md as the integration point for
when a hosted LLM is available; `extraction.py` and `rules_engine.py` do not
require it to produce a real, working verdict.
"""

import re
from .normalization import normalize_quantity, normalize_mrp, normalize_date, looks_like_address_block

FIELD_TYPES = [
    "MANUFACTURER", "GENERIC_NAME", "NET_QUANTITY", "MRP",
    "MFG_DATE", "BEST_BEFORE", "CONSUMER_CARE", "COUNTRY_OF_ORIGIN",
]

_CONSUMER_CARE_RE = re.compile(
    r"(customer\s*care|consumer\s*care|grievance|for\s*complaints?)", re.IGNORECASE)
_CONSUMER_CARE_CONTACT_RE = re.compile(
    r"(\+?\d[\d\-\s]{7,}\d)|([\w.+-]+@[\w-]+\.[\w.-]+)")
_ORIGIN_RE = re.compile(
    r"(country\s*of\s*origin|made\s*in|origin)\s*[:\-]?\s*([A-Za-z ]{3,30})", re.IGNORECASE)
_BEST_BEFORE_KEYWORD_RE = re.compile(r"(best\s*before|use\s*by|expiry|exp\.?)", re.IGNORECASE)
_MFG_KEYWORD_RE = re.compile(r"(mfg\.?\s*date|manufactur(ed|ing)\s*date|pkd\.?\s*date|packed\s*on)", re.IGNORECASE)
_GENERIC_NAME_KEYWORD_RE = re.compile(r"(generic\s*name|common\s*name|contents?)\s*[:\-]?\s*(.+)", re.IGNORECASE)


def _make_field(field_type, raw_text, normalized_value, confidence, bbox, script="LATIN", source="OCR"):
    return {
        "field_type": field_type,
        "raw_text": raw_text,
        "normalized_value": normalized_value,
        "confidence": round(confidence, 3),
        "bounding_box": bbox,
        "source": source,
        "script": script,
    }


def extract_fields(lines: list) -> list:
    """`lines` is the output of TesseractOCRService.reconstruct_lines().
    Returns a flat list of extracted-field dicts. A single OCR line may
    contribute more than one field (rare) or none."""
    fields = []

    for line in lines:
        text = line["text"]
        bbox = line["bbox"]
        conf = line["confidence"]
        script = "DEVANAGARI" if any(w.script == "DEVANAGARI" for w in line["words"]) else "LATIN"

        mrp = normalize_mrp(text)
        if mrp:
            fields.append(_make_field("MRP", text, mrp, conf, bbox, script))
            continue  # an MRP line is unlikely to also be another field

        qty = normalize_quantity(text)
        if qty and re.search(r"(net\s*(qty|quantity|wt|weight)|contents?)", text, re.IGNORECASE) or (
                qty and not re.search(r"(mfg|best\s*before|use\s*by|expiry)", text, re.IGNORECASE)):
            fields.append(_make_field("NET_QUANTITY", text, qty, conf, bbox, script))
            continue

        if _BEST_BEFORE_KEYWORD_RE.search(text):
            date = normalize_date(text)
            fields.append(_make_field("BEST_BEFORE", text, date, conf if date else conf * 0.4, bbox, script))
            continue

        # Checked AFTER best-before: a line like "Best Before: 12 months
        # from Mfg Date" also matches the MFG_DATE keyword pattern, and
        # without this ordering it would be misclassified as MFG_DATE,
        # silently starving the BEST_BEFORE field of any candidate line.
        # (Caught by inspecting real pipeline output on seed data.)
        if _MFG_KEYWORD_RE.search(text):
            date = normalize_date(text)
            fields.append(_make_field("MFG_DATE", text, date, conf if date else conf * 0.4, bbox, script))
            continue

        if _CONSUMER_CARE_RE.search(text):
            contact = _CONSUMER_CARE_CONTACT_RE.search(text)
            fields.append(_make_field(
                "CONSUMER_CARE", text,
                {"has_contact_detail": bool(contact)},
                conf if contact else conf * 0.6, bbox, script))
            continue

        origin_match = _ORIGIN_RE.search(text)
        if origin_match:
            fields.append(_make_field(
                "COUNTRY_OF_ORIGIN", text, {"country": origin_match.group(2).strip()},
                conf, bbox, script))
            continue

        generic_match = _GENERIC_NAME_KEYWORD_RE.search(text)
        if generic_match:
            fields.append(_make_field(
                "GENERIC_NAME", text, {"name": generic_match.group(2).strip()}, conf, bbox, script))
            continue

        if looks_like_address_block(text):
            fields.append(_make_field(
                "MANUFACTURER", text,
                {"has_address_block": True, "qualified": bool(re.search(
                    r"(manufactured|packed|marketed|imported)\s+by", text, re.IGNORECASE))},
                conf, bbox, script))
            continue

    return fields


def best_field(fields: list, field_type: str):
    """Some labels produce more than one candidate line for the same field
    type (e.g. two lines both matching the address heuristic); pick the
    highest-confidence one rather than silently overwriting."""
    candidates = [f for f in fields if f["field_type"] == field_type]
    if not candidates:
        return None
    return max(candidates, key=lambda f: f["confidence"])
