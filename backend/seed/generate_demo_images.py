"""
Generates three synthetic label images for the seeded demo scenarios
(PRD Part 16 / Part 31).

WHY SYNTHETIC IMAGES: this sandbox has no network access to download real
product photos (and using real brands' packaging in a checked-in demo
dataset would also raise IP/trademark considerations outside this task's
scope). These are programmatically drawn label mockups containing real,
readable text that the actual OCR/extraction/rule-engine pipeline processes
for real -- they exist to make the pipeline runnable and demoable, not to
fake a result. When a real product photo is available (e.g. a judge's own
snack wrapper, PRD Part 32), the exact same code path handles it identically.

Scenario 1: DEMO_COMPLIANT -- every core declaration present and well formed.
Scenario 2: DEMO_MISSING_DECLARATION -- consumer-care block omitted.
Scenario 3: DEMO_DIFFICULT -- glare patch + perspective warp applied, to
            genuinely exercise the curvature/glare-aware confidence
            downgrades in font_size.py and quality.py rather than asserting
            they work without ever triggering them.
"""

import os
import platform
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

_FONT_CANDIDATES = {
    "regular": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\calibri.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
    ],
    "bold": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
        "C:\\Windows\\Fonts\\calibrib.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
    ],
}

_font_cache = {}


def _resolve_font_path(bold: bool):
    for path in _FONT_CANDIDATES["bold" if bold else "regular"]:
        if os.path.exists(path):
            return path
    return None


def _font(size, bold=False):
    cache_key = (size, bold)
    if cache_key in _font_cache:
        return _font_cache[cache_key]

    path = _resolve_font_path(bold)
    if path is not None:
        font = ImageFont.truetype(path, size)
    else:
        print(f"[generate_demo_images] No system font found for bold={bold} "
              f"on {platform.system()}; using default font instead.")
        font = ImageFont.load_default(size=size)

    _font_cache[cache_key] = font
    return font


def _draw_label_canvas(lines_with_sizes, canvas_size=(900, 1100), bg=(228, 224, 210), border_color=(80, 40, 20)):
    """bg is intentionally NOT near-white -- a full-frame near-white
    background would (correctly) trip the glare heuristic in quality.py,
    the same way an overexposed real photo would. Real packaging almost
    always has a coloured brand panel/border rather than a blank white
    page, so this mirrors that instead of accidentally testing a
    degenerate case."""
    img = Image.new("RGB", canvas_size, bg)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, canvas_size[0] - 1, canvas_size[1] - 1], outline=border_color, width=10)
    y = 40
    for text, size, bold, color in lines_with_sizes:
        draw.text((50, y), text, font=_font(size, bold), fill=color)
        y += int(size * 1.6)
    return img


def generate_compliant_label(out_path):
    lines = [
        ("XYZ FOODS", 46, True, (20, 20, 20)),
        ("Crunchy Wheat Biscuits", 30, False, (30, 30, 30)),
        ("", 10, False, (0, 0, 0)),
        ("Generic Name: Wheat Biscuit", 24, False, (0, 0, 0)),
        ("Net Qty. 200 g", 26, False, (0, 0, 0)),
        ("MRP Rs. 45.00 (Incl. of all taxes)", 26, False, (0, 0, 0)),
        ("Mfg Date: 03/2026", 24, False, (0, 0, 0)),
        ("Best Before: 12 months from Mfg Date", 22, False, (0, 0, 0)),
        ("Manufactured by: XYZ Foods Pvt Ltd,", 22, False, (0, 0, 0)),
        ("Plot 14, MIDC Industrial Area, Pune 411019", 22, False, (0, 0, 0)),
        ("Country of Origin: India", 22, False, (0, 0, 0)),
        ("Consumer Care: 1800-123-4567, care@xyzfoods.example", 20, False, (0, 0, 0)),
    ]
    img = _draw_label_canvas(lines)
    img.save(out_path, quality=95)


def generate_missing_declaration_label(out_path):
    """Same as compliant, minus the consumer-care line entirely."""
    lines = [
        ("RIVERA SNACKS", 46, True, (20, 20, 20)),
        ("Spicy Corn Puffs", 30, False, (30, 30, 30)),
        ("", 10, False, (0, 0, 0)),
        ("Generic Name: Corn Puff Snack", 24, False, (0, 0, 0)),
        ("Net Qty. 90 g", 26, False, (0, 0, 0)),
        ("MRP Rs. 20.00 (Incl. of all taxes)", 26, False, (0, 0, 0)),
        ("Mfg Date: 01/2026", 24, False, (0, 0, 0)),
        ("Best Before: 6 months from Mfg Date", 22, False, (0, 0, 0)),
        ("Manufactured by: Rivera Snacks Pvt Ltd,", 22, False, (0, 0, 0)),
        ("Sector 9, Faridabad 121006", 22, False, (0, 0, 0)),
        ("Country of Origin: India", 22, False, (0, 0, 0)),
        # Consumer care deliberately omitted -- Scenario 2 (PRD Part 16).
    ]
    img = _draw_label_canvas(lines)
    img.save(out_path, quality=95)


def generate_difficult_label(out_path):
    """Compliant-content label, then genuinely warped (barrel/cylindrical
    distortion, simulating a curved bottle/pouch surface) and given a
    strong localized glare patch, so quality.py's curvature/glare
    heuristics and font_size.py's downgrade logic have something real to
    detect -- the difficulty is actually present in the pixels, not
    asserted."""
    lines = [
        ("MOUNTAIN FRESH", 46, True, (20, 20, 20)),
        ("Herbal Face Cream, SPF 30", 28, False, (30, 30, 30)),
        ("", 10, False, (0, 0, 0)),
        ("Generic Name: Herbal Face Cream", 24, False, (0, 0, 0)),
        ("Net Qty. 50 g", 26, False, (0, 0, 0)),
        ("MRP Rs. 199.00 (Incl. of all taxes)", 26, False, (0, 0, 0)),
        ("Mfg Date: 11/2025", 24, False, (0, 0, 0)),
        ("Manufactured by: Mountain Fresh Cosmetics,", 22, False, (0, 0, 0)),
        ("Baddi, Himachal Pradesh 173205", 22, False, (0, 0, 0)),
        ("Country of Origin: India", 22, False, (0, 0, 0)),
        ("Consumer Care: 1800-999-2222", 20, False, (0, 0, 0)),
    ]
    img = _draw_label_canvas(lines, bg=(225, 230, 235))
    arr = np.array(img)
    arr_bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    h, w = arr_bgr.shape[:2]

    # Barrel/cylindrical distortion: bulges the panel outward like a curved
    # bottle surface, which produces a genuinely non-quadrilateral boundary
    # (unlike a flat perspective warp) for quality._curvature_estimate to detect.
    cx, cy = w / 2.0, h / 2.0
    k = 3.0e-7  # distortion strength -- tuned low enough that OCR can still
                # read most declarations (so presence/format checks still
                # succeed), while still producing a genuinely detectable,
                # non-quadrilateral boundary for the curvature heuristic.
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dx = xx - cx
    dy = yy - cy
    r2 = dx ** 2 + dy ** 2
    factor = 1 + k * r2
    map_x = cx + dx / factor
    map_y = cy + dy / factor
    warped = cv2.remap(arr_bgr, map_x.astype(np.float32), map_y.astype(np.float32),
                        interpolation=cv2.INTER_LINEAR, borderValue=(225, 230, 235))

    # Strong localized glare patch (simulates a flash reflection off glossy
    # packaging) -- high opacity, small enough to not blow out the whole frame.
    overlay = warped.copy()
    cv2.ellipse(overlay, (int(w * 0.68), int(h * 0.28)), (200, 140), 25, 0, 360, (255, 255, 255), -1)
    warped = cv2.addWeighted(overlay, 0.85, warped, 0.15, 0)

    cv2.imwrite(out_path, warped)


def generate_all(output_dir):
    os.makedirs(output_dir, exist_ok=True)
    paths = {
        "compliant": os.path.join(output_dir, "demo_compliant.jpg"),
        "missing_declaration": os.path.join(output_dir, "demo_missing_declaration.jpg"),
        "difficult": os.path.join(output_dir, "demo_difficult.jpg"),
    }
    generate_compliant_label(paths["compliant"])
    generate_missing_declaration_label(paths["missing_declaration"])
    generate_difficult_label(paths["difficult"])
    return paths


if __name__ == "__main__":
    result = generate_all("storage/uploads/demo")
    print(result)
