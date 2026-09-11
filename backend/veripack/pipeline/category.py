"""
Product category classification (PRD Part 12).

MVP implementation is a keyword-over-OCR-text heuristic, not a trained
image/text classifier -- training a real classifier needs a labelled
dataset this sandbox has neither the data nor network access to assemble.
"""

SUPPORTED_CATEGORIES = ["PACKAGED_FOOD_FMCG", "COSMETICS", "ELECTRONICS"]

_COSMETICS_KEYWORDS = [
    "cream", "lotion", "shampoo", "conditioner", "spf", "sunscreen", "serum",
    "moisturi", "cosmetic", "soap", "talc", "deodorant", "perfume", "lipstick",
    "face wash", "body wash",
]
_FOOD_KEYWORDS = [
    "net wt", "net qty", "ingredients", "nutrition", "best before", "biscuit",
    "namkeen", "snack", "beverage", "edible", "fssai", "vegetarian", "spice",
    "atta", "oil", "ghee",
]
_ELECTRONICS_KEYWORDS = [
    "voltage", "watt", "ampere", "volt", "hz", "frequency", "bis", "warranty",
    "charger", "adapter", "battery", "rated input", "rated output", "model no",
    "serial no", "iso 9001", "electronic",
]


def classify_category(all_ocr_text: str) -> dict:
    """Returns {"category": ..., "confidence": ..., "method": "KEYWORD_HEURISTIC"}.
    Falls back to PACKAGED_FOOD_FMCG at low confidence if no keyword hits at all."""
    text_lower = all_ocr_text.lower()
    cosmetics_hits = sum(1 for kw in _COSMETICS_KEYWORDS if kw in text_lower)
    food_hits = sum(1 for kw in _FOOD_KEYWORDS if kw in text_lower)
    electronics_hits = sum(1 for kw in _ELECTRONICS_KEYWORDS if kw in text_lower)

    if cosmetics_hits == 0 and food_hits == 0 and electronics_hits == 0:
        return {"category": "PACKAGED_FOOD_FMCG", "confidence": 0.35, "method": "KEYWORD_HEURISTIC_DEFAULT"}

    scores = {
        "COSMETICS": cosmetics_hits,
        "PACKAGED_FOOD_FMCG": food_hits,
        "ELECTRONICS": electronics_hits,
    }
    best_category = max(scores, key=scores.get)
    confidence = min(0.95, 0.55 + 0.1 * scores[best_category])
    return {"category": best_category, "confidence": round(confidence, 2), "method": "KEYWORD_HEURISTIC"}