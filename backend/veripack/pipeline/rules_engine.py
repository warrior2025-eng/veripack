"""
Rule engine (PRD Part 13 / docs/RULE_ENGINE.md).

Rules are DATA, not code. This module contains zero hardcoded knowledge of
"food products need X" -- every requirement, its applicability logic, its
validation logic, and its source citation are rows in rule_version /
rule_requirement (see db/schema.sql), selected at evaluation time by
(category, audit_date). Changing what the law requires means writing new
rows via the Admin API (veripack/api/rules.py), never editing this file.

This is what lets a historical compliance_check keep citing the
rule_version that was active when it ran, even after the Department issues
a new amendment and an admin activates a new RuleVersion -- reproducibility
requirement, PRD Part 47.
"""

from db.database import get_db, row_to_dict, rows_to_list, from_json
from .confidence import compute_confidence, visual_quality_factor_from_issues, CONFIDENCE_THRESHOLD
from .extraction import best_field
from . import font_size as font_size_module


def select_rule_version(category: str, audit_date: str):
    """Returns the ACTIVE rule_version row for `category` whose
    [effective_from, effective_to) window contains `audit_date`
    (ISO 'YYYY-MM-DD'). Returns None if no matching version exists --
    callers must treat that as UNSUPPORTED_CATEGORY, never fabricate a
    fallback rule set."""
    with get_db() as cur:
        cur.execute(
            """SELECT * FROM rule_version
               WHERE category = ? AND status = 'ACTIVE'
                 AND effective_from <= ?
                 AND (effective_to IS NULL OR effective_to > ?)
               ORDER BY effective_from DESC LIMIT 1""",
            (category, audit_date, audit_date),
        )
        return row_to_dict(cur.fetchone())


def get_requirements(rule_version_id: int):
    with get_db() as cur:
        cur.execute(
            "SELECT * FROM rule_requirement WHERE rule_version_id = ? AND enabled = 1 ORDER BY id",
            (rule_version_id,),
        )
        return rows_to_list(cur.fetchall())


def _is_applicable(requirement: dict, extracted_fields: list) -> tuple:
    """Returns (applicable: bool, applicability_uncertain: bool). Some
    requirements only apply under a condition the image itself may or may
    not let us determine -- see PRD Part 5's country-of-origin discussion.
    """
    logic = requirement["applicability_logic"]
    if logic == "ALL":
        return True, False

    if logic == "IMPORTED_ONLY":
        origin_field = best_field(extracted_fields, "COUNTRY_OF_ORIGIN")
        if origin_field is None:
            return False, True  # can't tell if this is an import -> uncertain, not "not applicable"
        country = (origin_field["normalized_value"] or {}).get("country", "").strip().lower()
        is_imported = bool(country) and country not in ("india", "made in india")
        return is_imported, False

    # PERISHABLE_ONLY / GARMENT_ONLY etc. are supported by the schema for
    # post-MVP category expansion (PRD Part 5/15) but MVP's two categories
    # (PACKAGED_FOOD_FMCG, COSMETICS) don't yet populate them with real
    # requirements -- default to applicable rather than silently skipping.
    return True, False


def _evaluate_presence(requirement: dict, extracted_fields: list, image_quality: dict):
    field = best_field(extracted_fields, requirement["field_type"])
    if field is None:
        if not image_quality["usable"] or image_quality["score"] < 0.4:
            return "INSUFFICIENT_EVIDENCE", 0.2, (
                f"{requirement['requirement_name']} was not detected, but image quality is low "
                f"({image_quality['score']}); this may be a detection failure rather than a true "
                f"absence. Recapture recommended.")
        return "POTENTIAL_NON_COMPLIANCE", 0.7, (
            f"{requirement['requirement_name']} was not detected on the label as photographed.")
    validation_confidence = 1.0
    reason = f"{requirement['requirement_name']} detected: \"{field['raw_text']}\"."
    confidence = compute_confidence(field["confidence"], image_quality["score"], validation_confidence)
    verdict = "COMPLIANT" if confidence >= CONFIDENCE_THRESHOLD else "REQUIRES_OFFICER_VERIFICATION"
    if verdict == "REQUIRES_OFFICER_VERIFICATION":
        reason += " Confidence is below the review threshold; officer verification requested."
    return verdict, confidence, reason


def _evaluate_qualified_presence(requirement: dict, extracted_fields: list, image_quality: dict):
    """Manufacturer/packer/importer: presence AND the 'manufactured by /
    packed by / marketed by' qualifier matters legally (PRD Part 5,
    Explanations I & II) -- detecting the qualifier is a text pattern, but
    which entity bears legal liability is NOT something this system decides."""
    field = best_field(extracted_fields, requirement["field_type"])
    if field is None:
        if not image_quality["usable"] or image_quality["score"] < 0.4:
            return "INSUFFICIENT_EVIDENCE", 0.2, (
                "Manufacturer/packer/importer block was not detected, and image quality is low; "
                "this may be a detection failure. Recapture recommended.")
        return "POTENTIAL_NON_COMPLIANCE", 0.7, "No manufacturer/packer/importer declaration was detected."

    qualified = (field["normalized_value"] or {}).get("qualified", False)
    validation_confidence = 1.0 if qualified else 0.6
    confidence = compute_confidence(field["confidence"], image_quality["score"], validation_confidence)
    if qualified:
        verdict = "COMPLIANT" if confidence >= CONFIDENCE_THRESHOLD else "REQUIRES_OFFICER_VERIFICATION"
        reason = f"Declaration detected with a 'manufactured by / packed by / marketed by' qualifier: \"{field['raw_text']}\"."
    else:
        verdict = "REQUIRES_OFFICER_VERIFICATION"
        reason = (f"An address-like block was detected (\"{field['raw_text']}\") but the required "
                  f"qualifier (manufactured by / packed by / marketed by) was not clearly recognized. "
                  f"Officer should confirm which entity bears declared responsibility.")
    return verdict, confidence, reason


def _evaluate_format(requirement: dict, extracted_fields: list, image_quality: dict):
    """MRP / Net Quantity: field must be present AND parse into a
    structured normalized_value (see normalization.py) with the expected
    keys, or the format itself is non-compliant/uncertain."""
    field = best_field(extracted_fields, requirement["field_type"])
    validation_spec = from_json(requirement["validation_logic"], {}) if isinstance(requirement["validation_logic"], str) else requirement["validation_logic"]
    required_keys = validation_spec.get("requires", [])

    if field is None:
        if not image_quality["usable"] or image_quality["score"] < 0.4:
            return "INSUFFICIENT_EVIDENCE", 0.2, (
                f"{requirement['requirement_name']} was not detected, and image quality is low; "
                f"this may be a detection failure. Recapture recommended.")
        return "POTENTIAL_NON_COMPLIANCE", 0.75, f"{requirement['requirement_name']} was not detected on the label."

    normalized = field["normalized_value"] or {}
    has_all_keys = all(k in normalized and normalized[k] not in (None, "") for k in required_keys)
    validation_confidence = 1.0 if has_all_keys else 0.4
    confidence = compute_confidence(field["confidence"], image_quality["score"], validation_confidence)

    if not has_all_keys:
        return "POTENTIAL_NON_COMPLIANCE", confidence, (
            f"{requirement['requirement_name']} text was detected (\"{field['raw_text']}\") but did not "
            f"parse into the expected format ({', '.join(required_keys)}).")

    verdict = "COMPLIANT" if confidence >= CONFIDENCE_THRESHOLD else "REQUIRES_OFFICER_VERIFICATION"
    reason = f"{requirement['requirement_name']} detected and correctly formatted: {normalized}."
    if requirement["field_type"] == "NET_QUANTITY":
        reason += (" Note: this confirms a net-quantity DECLARATION exists in the correct format. "
                   "VeriPack cannot verify the physical quantity inside the package from an image. "
                   "That requires metrological weighing under the Sixth Schedule.")
    return verdict, confidence, reason


def _evaluate_visual_geometric(requirement: dict, extracted_fields: list, image_quality: dict, panel_bbox):
    field = best_field(extracted_fields, requirement["field_type"]) or best_field(extracted_fields, "MRP")
    if field is None:
        return "INSUFFICIENT_EVIDENCE", 0.15, "No reference text region available to assess placement/size."
    result = font_size_module.evaluate_font_size_requirement(field, panel_bbox, image_quality["issues"])
    return result["verdict"], result["confidence"], result["reason"]


_EVALUATORS = {
    "presence": _evaluate_presence,
    "qualified_presence": _evaluate_qualified_presence,
    "format": _evaluate_format,
}


def evaluate_check(rule_version: dict, extracted_fields: list, image_quality: dict, panel_bbox=None) -> list:
    """Runs every enabled requirement in rule_version against the extracted
    fields for one compliance_check. Returns a list of result dicts ready
    to persist as requirement_result rows. Never mutates the database
    itself -- pure function, easy to unit test (see tests/test_rules_engine.py)."""
    requirements = get_requirements(rule_version["id"])
    results = []

    for requirement in requirements:
        applicable, uncertain = _is_applicable(requirement, extracted_fields)
        if uncertain:
            results.append({
                "rule_requirement_id": requirement["id"],
                "verdict": "INSUFFICIENT_EVIDENCE",
                "confidence": 0.2,
                "reason": (f"{requirement['requirement_name']} applies only to imported products; "
                          f"import status could not be determined from this image."),
                "rule_reference": requirement["source_citation"],
                "requirement_name": requirement["requirement_name"],
                "field_type": requirement["field_type"],
            })
            continue
        if not applicable:
            continue  # genuinely not applicable to this product -- no result row, not a violation

        validation_spec = from_json(requirement["validation_logic"], {})
        vtype = validation_spec.get("type", "presence")

        if vtype == "visual_geometric":
            verdict, confidence, reason = _evaluate_visual_geometric(
                requirement, extracted_fields, image_quality, panel_bbox)
        else:
            evaluator = _EVALUATORS.get(vtype, _evaluate_presence)
            verdict, confidence, reason = evaluator(requirement, extracted_fields, image_quality)

        results.append({
            "rule_requirement_id": requirement["id"],
            "verdict": verdict,
            "confidence": confidence,
            "reason": reason,
            "rule_reference": requirement["source_citation"],
            "requirement_name": requirement["requirement_name"],
            "field_type": requirement["field_type"],
        })

    return results
