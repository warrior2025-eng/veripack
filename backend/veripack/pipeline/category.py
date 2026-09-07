"""
Product category classification (PRD Part 12).

MVP implementation is a keyword-over-OCR-text heuristic, not a trained
image/text classifier. The PRD explicitly says "use pretrained/lightweight
models wherever possible; do NOT require training a custom computer vision
model unless absolutely necessary" -- training a real category classifier
needs a labelled dataset of real product photos, which this sandbox has
neither the data nor the network access to assemble or download. A
keyword heuristic is the honest, practical MVP-appropriate substitute
documented here, with a clear upgrade path (docs/AI_PIPELINE.md) to a
trained classifier once real training data and network access exist.

MVP supports exactly two categories, per PRD Part 12 -- adding a third is a
data problem (keyword list / training set), not an architecture change.
"""

SUPPORTED_CATEGORIES = ["PACKAGED_FOOD_FMCG", "COSMETICS"]

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


def classify_category(all_ocr_text: str) -> dict:
    """Returns {"category": ..., "confidence": ..., "method": "KEYWORD_HEURISTIC"}.
    Falls back to PACKAGED_FOOD_FMCG (the more common SIH demo category) with
    low confidence if no keyword hits at all, rather than guessing an
    unsupported category."""
    text_lower = all_ocr_text.lower()
    cosmetics_hits = sum(1 for kw in _COSMETICS_KEYWORDS if kw in text_lower)
    food_hits = sum(1 for kw in _FOOD_KEYWORDS if kw in text_lower)

    if cosmetics_hits == 0 and food_hits == 0:
        return {"category": "PACKAGED_FOOD_FMCG", "confidence": 0.35, "method": "KEYWORD_HEURISTIC_DEFAULT"}

    if cosmetics_hits > food_hits:
        confidence = min(0.95, 0.55 + 0.1 * cosmetics_hits)
        return {"category": "COSMETICS", "confidence": round(confidence, 2), "method": "KEYWORD_HEURISTIC"}

    confidence = min(0.95, 0.55 + 0.1 * food_hits)
    return {"category": "PACKAGED_FOOD_FMCG", "confidence": round(confidence, 2), "method": "KEYWORD_HEURISTIC"}
