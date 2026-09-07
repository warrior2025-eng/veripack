"""
Panel localization + evidence annotation (PRD Part 19-20).

Panel detection here is a practical heuristic (largest reasonably-central
rectangular contour), not a trained object detector -- training a package
detector needs a labelled dataset this sandbox cannot obtain (no network,
no existing dataset). It is a real, working, testable piece of OpenCV code,
just not a neural network. Swapping in a trained detector later only means
replacing `detect_panel()`'s body; every caller only depends on it
returning a bbox or None.
"""

import cv2
import numpy as np

VERDICT_COLORS = {
    "COMPLIANT": (60, 160, 60),                     # green (BGR)
    "POTENTIAL_NON_COMPLIANCE": (40, 40, 210),       # red
    "REQUIRES_OFFICER_VERIFICATION": (0, 165, 255),  # amber
    "INSUFFICIENT_EVIDENCE": (150, 150, 150),        # grey
}


def detect_panel(gray: np.ndarray):
    """Returns [x, y, w, h] for the largest plausible label panel region,
    or None. Used only to give font_size.py something to compute a
    *relative* height ratio against -- see that module's docstring for why
    this is never treated as a certified physical measurement."""
    h, w = gray.shape[:2]
    edges = cv2.Canny(gray, 40, 120)
    edges = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return [0, 0, w, h]  # fall back to the whole frame

    best = None
    best_area = 0
    frame_area = w * h
    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        area = cw * ch
        if area < 0.15 * frame_area or area > 0.98 * frame_area:
            continue
        if area > best_area:
            best_area = area
            best = [x, y, cw, ch]

    return best if best is not None else [0, 0, w, h]


def draw_annotations(image_bgr: np.ndarray, requirement_results: list, field_lookup: dict) -> np.ndarray:
    """Draws a colour-coded bounding box + short label for every requirement
    result that has an associated extracted field, matching PRD Part 20's
    annotated-evidence-viewer spec. `field_lookup` maps field_type -> field dict."""
    annotated = image_bgr.copy()
    for result in requirement_results:
        field = field_lookup.get(result["field_type"])
        if field is None or not field.get("bounding_box"):
            continue
        x, y, w, h = field["bounding_box"]
        color = VERDICT_COLORS.get(result["verdict"], (200, 200, 200))
        cv2.rectangle(annotated, (x, y), (x + w, y + h), color, 2)
        label = f"{result['requirement_name']}"
        (text_w, text_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        label_y = max(0, y - 6)
        cv2.rectangle(annotated, (x, label_y - text_h - 4), (x + text_w + 4, label_y + 2), color, -1)
        cv2.putText(annotated, label, (x + 2, label_y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return annotated
