"""
Pipeline orchestrator (PRD Part 8 workflow, implemented for real).

This is the one place that calls every pipeline stage in order and persists
results. Route handlers (veripack/api/checks.py) call `run_pipeline()` and
nothing else -- they do not know about OCR, rule evaluation, or image
processing, keeping domain logic out of route handlers (build brief
Section 5).
"""

import os
import cv2
from datetime import datetime, date, timezone

from db.database import get_db, to_json
from . import ocr as ocr_module, extraction, category as category_module
from . import quality, rules_engine, evidence
from .confidence import CONFIDENCE_THRESHOLD
from .ocr import TesseractOCRService, OCR_ENGINE_VERSION

PIPELINE_VERSION = "veripack-pipeline-0.1.0"
EVIDENCE_DIR = os.environ.get("VERIPACK_EVIDENCE_DIR", "storage/evidence")

_ocr_service = TesseractOCRService(language_hint="eng")


def run_pipeline(check_id: int) -> dict:
    """Runs the entire CAPTURE -> ... -> EVIDENCE workflow for one
    compliance_check row that has already been inserted with status
    'QUEUED' and a product_image_id. Returns the final status."""
    from .. import audit as audit_helper  # local import: audit.log() calls record()

    with get_db() as cur:
        cur.execute("SELECT * FROM compliance_check WHERE id = ?", (check_id,))
        check = cur.fetchone()
        if check is None:
            raise ValueError(f"compliance_check {check_id} not found")
        check = dict(check)
        cur.execute("SELECT * FROM product_image WHERE id = ?", (check["product_image_id"],))
        image_row = dict(cur.fetchone())

    with get_db() as cur:
        cur.execute("UPDATE compliance_check SET status='PROCESSING' WHERE id=?", (check_id,))

    try:
        image_path = image_row["file_path"]
        image_bgr = ocr_module.load_image(image_path)

        # STAGE 1: Image quality gate
        quality_report = quality.assess_image_quality(image_bgr)

        if not quality_report["usable"]:
            with get_db() as cur:
                cur.execute(
                    """UPDATE compliance_check
                       SET status='INVALID_IMAGE', image_quality_score=?, image_quality_notes=?, completed_at=?
                       WHERE id=?""",
                    (quality_report["score"], to_json(quality_report["issues"]),
                     datetime.now(timezone.utc).isoformat(), check_id),
                )
            audit_helper.log(check["submitted_by"], "CHECK_INVALID_IMAGE", "compliance_check", check_id,
                              metadata=quality_report)
            return {"status": "INVALID_IMAGE", "quality": quality_report}

        # STAGE 2: Preprocessing + panel localization
        preprocessed = quality.preprocess_for_ocr(image_bgr)
        panel_bbox = evidence.detect_panel(preprocessed)

        # STAGE 3: OCR
        regions = _ocr_service.extract_regions(preprocessed)
        lines = _ocr_service.reconstruct_lines(regions)
        all_text = " ".join(l["text"] for l in lines)

        # STAGE 4 + 5: Field extraction + normalization (normalization happens
        # inside extraction.py at parse time, per field)
        fields = extraction.extract_fields(lines)

        # STAGE 6: Category classification
        cat_result = category_module.classify_category(all_text)
        category_code = cat_result["category"]

        if category_code not in category_module.SUPPORTED_CATEGORIES:
            with get_db() as cur:
                cur.execute(
                    "UPDATE compliance_check SET status='UNSUPPORTED_CATEGORY', category=?, completed_at=? WHERE id=?",
                    (category_code, datetime.now(timezone.utc).isoformat(), check_id),
                )
            return {"status": "UNSUPPORTED_CATEGORY", "category": category_code}

        # STAGE 7: Rule version selection
        audit_date = check["audit_date"] or date.today().isoformat()
        rule_version = rules_engine.select_rule_version(category_code, audit_date)
        if rule_version is None:
            with get_db() as cur:
                cur.execute(
                    "UPDATE compliance_check SET status='UNSUPPORTED_CATEGORY', category=?, completed_at=? WHERE id=?",
                    (category_code, datetime.now(timezone.utc).isoformat(), check_id),
                )
            audit_helper.log(check["submitted_by"], "NO_ACTIVE_RULE_VERSION", "compliance_check", check_id,
                              metadata={"category": category_code, "audit_date": audit_date})
            return {"status": "UNSUPPORTED_CATEGORY", "reason": "no_active_rule_version"}

        # Persist extracted fields now so requirement_result rows can
        # reference real field IDs.
        field_ids_by_type = {}
        with get_db() as cur:
            for f in fields:
                cur.execute(
                    """INSERT INTO extracted_field
                       (compliance_check_id, field_type, raw_text, normalized_value, confidence, bounding_box, source, script)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (check_id, f["field_type"], f["raw_text"], to_json(f["normalized_value"]),
                     f["confidence"], to_json(f["bounding_box"]), f["source"], f["script"]),
                )
                f["id"] = cur.lastrowid
                field_ids_by_type.setdefault(f["field_type"], []).append(f)

        # STAGE 8: Rule engine evaluation (per-requirement, four-state verdicts)
        results = rules_engine.evaluate_check(rule_version, fields, quality_report, panel_bbox)

        field_lookup_best = {ft: max(fl, key=lambda x: x["confidence"]) for ft, fl in field_ids_by_type.items()}

        with get_db() as cur:
            for r in results:
                related_field = field_lookup_best.get(r["field_type"])
                extracted_field_ids = [related_field["id"]] if related_field else []
                requires_review = r["confidence"] < CONFIDENCE_THRESHOLD or r["verdict"] in (
                    "REQUIRES_OFFICER_VERIFICATION",)
                cur.execute(
                    """INSERT INTO requirement_result
                       (compliance_check_id, rule_requirement_id, verdict, confidence, reason,
                        extracted_field_ids, rule_reference, requires_review)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (check_id, r["rule_requirement_id"], r["verdict"], r["confidence"], r["reason"],
                     to_json(extracted_field_ids), r["rule_reference"], int(requires_review)),
                )
                result_id = cur.lastrowid
                if requires_review:
                    cur.execute(
                        """INSERT INTO review_task (compliance_check_id, requirement_result_id, status)
                           VALUES (?, ?, 'PENDING')""",
                        (check_id, result_id),
                    )

        # STAGE 9: Evidence packet (annotated image)
        os.makedirs(EVIDENCE_DIR, exist_ok=True)
        annotated = evidence.draw_annotations(image_bgr, results, field_lookup_best)
        annotated_path = os.path.join(EVIDENCE_DIR, f"check_{check_id}_annotated.jpg")
        cv2.imwrite(annotated_path, annotated)

        with get_db() as cur:
            cur.execute(
                "INSERT INTO evidence_item (compliance_check_id, kind, file_path) VALUES (?, 'ORIGINAL_IMAGE', ?)",
                (check_id, image_path))
            cur.execute(
                "INSERT INTO evidence_item (compliance_check_id, kind, file_path) VALUES (?, 'ANNOTATED_IMAGE', ?)",
                (check_id, annotated_path))
            cur.execute(
                """UPDATE compliance_check
                   SET status='COMPLETED', category=?, rule_version_id=?, ocr_engine_version=?,
                       pipeline_version=?, image_quality_score=?, image_quality_notes=?, completed_at=?
                   WHERE id=?""",
                (category_code, rule_version["id"], OCR_ENGINE_VERSION, PIPELINE_VERSION,
                 quality_report["score"], to_json(quality_report["issues"]),
                 datetime.now(timezone.utc).isoformat(), check_id),
            )

        audit_helper.log(check["submitted_by"], "CHECK_COMPLETED", "compliance_check", check_id,
                          metadata={"category": category_code, "rule_version_id": rule_version["id"],
                                    "requirement_count": len(results)})

        return {"status": "COMPLETED", "category": category_code, "rule_version_id": rule_version["id"],
                "requirement_count": len(results)}

    except Exception as exc:
        with get_db() as cur:
            cur.execute(
                "UPDATE compliance_check SET status='PROCESSING_FAILED', completed_at=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), check_id),
            )
        audit_helper.log(None, "CHECK_PROCESSING_FAILED", "compliance_check", check_id,
                          metadata={"error": str(exc)})
        raise
