"""
Image quality gate (PRD Part 9 / Part 17-18).

Runs BEFORE OCR. If the image is too poor to analyze reliably, the pipeline
must say so rather than silently running compliance logic on garbage input
(PRD Part 34: INVALID_IMAGE is a distinct, honest outcome, not a crash).

All thresholds are heuristic and documented as such -- there is no ground
truth "this image is 73% good" in the literature; these are practical,
tunable cutoffs, not a calibrated scientific measurement.
"""

import cv2
import numpy as np

BLUR_VARIANCE_THRESHOLD = 60.0       # Laplacian variance below this = likely blurry
MIN_WIDTH, MIN_HEIGHT = 400, 300     # below this, text is almost never legible
GLARE_SATURATION_THRESHOLD = 0.06    # fraction of near-white saturated pixels
CURVATURE_EDGE_THRESHOLD = 0.35      # heuristic: how non-linear the dominant contour is


def _blur_score(gray: np.ndarray) -> float:
    """Variance of the Laplacian -- a standard, well-understood focus-measure
    heuristic. Higher = sharper. Not a physical measurement of blur radius."""
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _glare_ratio(image_bgr: np.ndarray) -> float:
    """Proportion of pixels that are near-saturated white, which is the
    classic signature of a glare/reflection blowout on glossy packaging."""
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    saturated = np.sum(gray > 245)
    return float(saturated) / float(gray.size)


def _curvature_estimate(gray: np.ndarray) -> float:
    """Heuristic proxy for surface curvature: looks at how much the largest
    detected contour's boundary deviates from a straight-sided quadrilateral.
    This is NOT a true 3D curvature measurement -- it is a cheap, explainable
    signal used only to decide whether to trust font-size/placement geometry
    (PRD Part 9 / Part 18), never to reject presence/OCR checks outright.
    """
    edges = cv2.Canny(gray, 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return 0.0
    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < 0.05 * gray.shape[0] * gray.shape[1]:
        return 0.0
    perimeter = cv2.arcLength(largest, True)
    approx = cv2.approxPolyDP(largest, 0.02 * perimeter, True)
    # A flat rectangular panel approximates to ~4 vertices. More vertices
    # relative to a simplified hull suggests a curved/irregular boundary.
    hull = cv2.convexHull(largest)
    hull_perimeter = cv2.arcLength(hull, True) or 1.0
    irregularity = abs(perimeter - hull_perimeter) / hull_perimeter
    vertex_penalty = max(0.0, (len(approx) - 4)) / 10.0
    return float(min(1.0, irregularity + vertex_penalty))

def downscale_if_needed(image_bgr: np.ndarray, max_dimension: int = 1800) -> np.ndarray:
    """Real phone photos are 3000-4000px+ -- processing full resolution
    uses too much memory on a small free-tier server and can crash the
    request. Downscale before any other processing."""
    h, w = image_bgr.shape[:2]
    longest_side = max(h, w)
    if longest_side <= max_dimension:
        return image_bgr
    scale = max_dimension / longest_side
    new_size = (int(w * scale), int(h * scale))
    return cv2.resize(image_bgr, new_size, interpolation=cv2.INTER_AREA)
def assess_image_quality(image_bgr: np.ndarray) -> dict:
    """Returns a quality report used both to gate the pipeline and to feed
    the confidence model (docs/AI_PIPELINE.md)."""
    issues = []
    h, w = image_bgr.shape[:2]
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)

    if w < MIN_WIDTH or h < MIN_HEIGHT:
        issues.append("LOW_RESOLUTION")

    blur = _blur_score(gray)
    if blur < BLUR_VARIANCE_THRESHOLD:
        issues.append("BLURRY")

    glare = _glare_ratio(image_bgr)
    if glare > GLARE_SATURATION_THRESHOLD:
        issues.append("GLARE")

    curvature = _curvature_estimate(gray)
    if curvature > CURVATURE_EDGE_THRESHOLD:
        issues.append("CURVED_SURFACE")

    # Composite score: start at 1.0 and apply multiplicative penalties.
    # This is an engineered heuristic, not a statistically fitted model --
    # documented plainly in docs/AI_PIPELINE.md.
    score = 1.0
    if "LOW_RESOLUTION" in issues:
        score *= 0.4
    score *= float(np.clip(blur / (BLUR_VARIANCE_THRESHOLD * 2), 0.15, 1.0))
    score *= float(np.clip(1.0 - (glare / 0.5), 0.2, 1.0))
    score *= float(np.clip(1.0 - curvature, 0.3, 1.0))
    score = round(min(1.0, max(0.0, score)), 3)

    usable = score >= 0.25 and "LOW_RESOLUTION" not in issues

    return {
        "score": score,
        "issues": issues,
        "usable": usable,
        "raw": {"blur_variance": round(blur, 2), "glare_ratio": round(glare, 4),
                "curvature_estimate": round(curvature, 4), "width": w, "height": h},
    }


def preprocess_for_ocr(image_bgr: np.ndarray) -> np.ndarray:
    """Deterministic preprocessing pipeline (PRD Part 9): grayscale, contrast
    enhancement (CLAHE), denoise, sharpen. No AI model involved here --
    OCR accuracy on real-world label photos improves substantially with
    classical preprocessing before any neural OCR step runs."""
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    contrasted = clahe.apply(gray)
    denoised = cv2.fastNlMeansDenoising(contrasted, h=10)
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    sharpened = cv2.filter2D(denoised, -1, kernel)
    return sharpened
