"""
Confidence model (PRD Part 8 / Part 20 of the build brief).

confidence = field_confidence * image_quality_factor * validation_confidence * visual_quality_factor

This is a transparent, explainable multiplicative formula -- not a trained
model, and the PRD explicitly says not to pretend otherwise ("do not
pretend the confidence number is scientifically perfect"). Each factor is
independently inspectable in the evidence packet, so an officer (or a
judge) can see exactly why a number came out the way it did.

The threshold below CONFIDENCE_THRESHOLD forces REQUIRES_OFFICER_VERIFICATION
regardless of what the raw rule evaluation concluded -- see rules_engine.py.
"""

CONFIDENCE_THRESHOLD = 0.75  # PRD's proposed starting point; configurable via system_config table


def compute_confidence(field_confidence: float, image_quality_score: float,
                        validation_confidence: float, visual_quality_factor: float = 1.0) -> float:
    """All inputs are expected in [0, 1]. Returns a value in [0, 1]."""
    field_confidence = max(0.0, min(1.0, field_confidence))
    image_quality_score = max(0.0, min(1.0, image_quality_score))
    validation_confidence = max(0.0, min(1.0, validation_confidence))
    visual_quality_factor = max(0.0, min(1.0, visual_quality_factor))
    return round(field_confidence * image_quality_score * validation_confidence * visual_quality_factor, 3)


def visual_quality_factor_from_issues(image_quality_issues: list) -> float:
    """Used only for checks flagged as 'visual_geometric' (font-size,
    placement) in rule_requirement.validation_logic -- curvature/glare
    should not silently fail OCR-based presence checks, only geometry-based
    ones (PRD Part 18)."""
    factor = 1.0
    if "CURVED_SURFACE" in image_quality_issues:
        factor *= 0.35
    if "GLARE" in image_quality_issues:
        factor *= 0.5
    if "BLURRY" in image_quality_issues:
        factor *= 0.6
    return round(factor, 3)
