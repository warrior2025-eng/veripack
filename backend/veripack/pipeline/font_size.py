"""
Font-size / placement heuristic (PRD Part 9 / Part 17 of the build brief).

THE HARD PART, handled honestly:

Pixel height in a photograph is NOT a physical measurement. The same 1mm
numeral can occupy 8px or 40px depending purely on camera distance -- there
is no calibration reference or known package dimension available in the
MVP capture flow, so this module NEVER outputs a millimetre figure and
NEVER contributes to a COMPLIANT verdict on its own for a numeral-height
rule. Its only two honest outputs are:

  - a RELATIVE size ratio (numeral height as a fraction of the detected
    panel height), used only as a coarse "obviously undersized" flag, and
  - REQUIRES_OFFICER_VERIFICATION, which is the correct verdict whenever
    the image cannot certify the measurement -- which, for an ordinary
    uncalibrated photo, is effectively always.

See docs/AI_PIPELINE.md for the calibration-marker mode that would be
required before this could ever contribute a COMPLIANT/POTENTIAL_NON_COMPLIANCE
verdict on font-size, which is explicitly out of MVP scope (PRD Part 12.4).
"""

RELATIVE_HEIGHT_UNDERSIZED_THRESHOLD = 0.015  # numeral height < 1.5% of panel height looks suspicious


def estimate_relative_font_size(field_bbox, panel_bbox):
    """Returns the field's text height as a fraction of the panel height.
    This is a *relative*, uncalibrated ratio -- not a millimetre estimate."""
    if not panel_bbox or panel_bbox[3] <= 0:
        return None
    field_height = field_bbox[3]
    panel_height = panel_bbox[3]
    return round(field_height / panel_height, 4)


def evaluate_font_size_requirement(field: dict, panel_bbox, image_quality_issues: list) -> dict:
    """Returns a dict with verdict/confidence/reason for a font-size-style
    requirement. This function's own docstring is intentionally repeated as
    the `reason` text in the low-confidence case, so the honesty travels
    all the way into the officer-facing UI and the PDF report."""
    if "CURVED_SURFACE" in image_quality_issues or "GLARE" in image_quality_issues:
        return {
            "verdict": "REQUIRES_OFFICER_VERIFICATION",
            "confidence": 0.3,
            "reason": ("Curved or reflective packaging detected; a reliable numeral-height "
                       "estimate cannot be made from this image. Physical measurement by the "
                       "officer is required."),
        }

    relative_height = estimate_relative_font_size(field["bounding_box"], panel_bbox)
    if relative_height is None:
        return {
            "verdict": "INSUFFICIENT_EVIDENCE",
            "confidence": 0.1,
            "reason": "Principal display panel could not be localized; numeral height cannot be assessed.",
        }

    if relative_height < RELATIVE_HEIGHT_UNDERSIZED_THRESHOLD:
        return {
            "verdict": "REQUIRES_OFFICER_VERIFICATION",
            "confidence": 0.55,
            "reason": (f"Numeral height appears small relative to the panel "
                       f"(ratio {relative_height}). This is an uncalibrated estimate, not a "
                       f"millimetre measurement -- officer should verify with a physical scale."),
        }

    return {
        "verdict": "REQUIRES_OFFICER_VERIFICATION",
        "confidence": 0.5,
        "reason": ("VeriPack cannot certify millimetre-accurate numeral height from an ordinary "
                   "photograph without a calibration reference. Relative proportions look "
                   "unremarkable, but physical verification under Rule 7 is required for a "
                   "conclusive determination."),
    }
