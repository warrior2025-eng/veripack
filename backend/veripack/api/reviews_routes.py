from flask import Blueprint, request, jsonify, g

from db.database import get_db, row_to_dict, rows_to_list
from veripack.auth import require_auth
from veripack import audit

bp = Blueprint("reviews_api", __name__, url_prefix="/api/reviews")


@bp.get("")
@require_auth
def list_reviews():
    status = request.args.get("status", "PENDING")
    with get_db() as cur:
        cur.execute(
            """SELECT rt.*, rr.verdict, rr.confidence, rr.reason, rr.rule_reference,
                      req.requirement_name, cc.product_id, cc.id as check_id
               FROM review_task rt
               JOIN requirement_result rr ON rr.id = rt.requirement_result_id
               JOIN rule_requirement req ON req.id = rr.rule_requirement_id
               JOIN compliance_check cc ON cc.id = rt.compliance_check_id
               WHERE rt.status = ?
               ORDER BY rt.created_at ASC""",
            (status,),
        )
        tasks = rows_to_list(cur.fetchall())
    return jsonify({"reviews": tasks})


@bp.post("/<int:task_id>/decision")
@require_auth
def submit_decision(task_id):
    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    reason = (body.get("reason") or "").strip()
    corrected_verdict = body.get("corrected_verdict")

    if decision not in ("CONFIRM", "CORRECT", "MARK_INSUFFICIENT", "OVERRIDE"):
        return jsonify({"error": "VALIDATION_ERROR", "message": "Invalid decision type."}), 400
    if not reason:
        return jsonify({"error": "VALIDATION_ERROR", "message": "A reason is required for every review decision."}), 400
    if decision in ("CORRECT", "OVERRIDE") and corrected_verdict not in (
            "COMPLIANT", "POTENTIAL_NON_COMPLIANCE", "REQUIRES_OFFICER_VERIFICATION", "INSUFFICIENT_EVIDENCE"):
        return jsonify({"error": "VALIDATION_ERROR", "message": "corrected_verdict required for CORRECT/OVERRIDE."}), 400

    with get_db() as cur:
        cur.execute("SELECT * FROM review_task WHERE id=?", (task_id,))
        task = row_to_dict(cur.fetchone())
        if task is None:
            return jsonify({"error": "NOT_FOUND"}), 404
        if task["status"] == "RESOLVED":
            return jsonify({"error": "ALREADY_RESOLVED"}), 409

        cur.execute("SELECT * FROM requirement_result WHERE id=?", (task["requirement_result_id"],))
        original_result = row_to_dict(cur.fetchone())

        cur.execute(
            """INSERT INTO review_decision (review_task_id, officer_id, decision, corrected_verdict, reason)
               VALUES (?,?,?,?,?)""",
            (task_id, g.user["id"], decision, corrected_verdict, reason),
        )

        # The AI-produced requirement_result row is NEVER silently overwritten
        # (PRD Part 21) -- we record the officer's decision as a linked event.
        # If the officer corrects/overrides the verdict, we insert a new
        # requirement_result row (officer-sourced) rather than mutating history.
        if decision in ("CORRECT", "OVERRIDE"):
            cur.execute(
                """INSERT INTO requirement_result
                   (compliance_check_id, rule_requirement_id, verdict, confidence, reason,
                    extracted_field_ids, rule_reference, requires_review)
                   VALUES (?,?,?,?,?,?,?,0)""",
                (original_result["compliance_check_id"], original_result["rule_requirement_id"],
                 corrected_verdict, 1.0, f"Officer {decision.lower()}: {reason}",
                 original_result["extracted_field_ids"], original_result["rule_reference"]),
            )
        elif decision == "MARK_INSUFFICIENT":
            cur.execute(
                """INSERT INTO requirement_result
                   (compliance_check_id, rule_requirement_id, verdict, confidence, reason,
                    extracted_field_ids, rule_reference, requires_review)
                   VALUES (?,?,?,?,?,?,?,0)""",
                (original_result["compliance_check_id"], original_result["rule_requirement_id"],
                 "INSUFFICIENT_EVIDENCE", 1.0, f"Officer marked insufficient: {reason}",
                 original_result["extracted_field_ids"], original_result["rule_reference"]),
            )

        cur.execute("UPDATE review_task SET status='RESOLVED' WHERE id=?", (task_id,))

    audit.log(g.user["id"], f"REVIEW_{decision}", "review_task", task_id,
              old_value={"ai_verdict": original_result["verdict"]},
              new_value={"decision": decision, "corrected_verdict": corrected_verdict},
              metadata={"reason": reason})

    return jsonify({"status": "RESOLVED"})
