import os
import uuid
from datetime import date

from flask import Blueprint, request, jsonify, g, send_file
from werkzeug.utils import secure_filename

from db.database import get_db, row_to_dict, rows_to_list, from_json
from veripack.auth import require_auth, organization_scoped_filter
from veripack import audit
from veripack.pipeline.pipeline import run_pipeline
from veripack import reports as reports_module

bp = Blueprint("checks_api", __name__, url_prefix="/api/checks")

UPLOAD_DIR = os.environ.get("VERIPACK_UPLOAD_DIR", "storage/uploads")
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png"}
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


def _allowed_file(filename: str, mimetype: str) -> bool:
    ext_ok = "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    return ext_ok and mimetype in ALLOWED_MIME_TYPES


@bp.post("")
@require_auth
def create_check():
    """Accepts multipart/form-data: `image` file, optional `product_name`,
    optional `audit_date` (ISO date, defaults to today -- used to select the
    applicable rule_version, PRD Part 47 reproducibility)."""
    if "image" not in request.files:
        return jsonify({"error": "VALIDATION_ERROR", "message": "No image file provided."}), 400

    file = request.files["image"]
    if file.filename == "":
        return jsonify({"error": "VALIDATION_ERROR", "message": "Empty filename."}), 400

    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > MAX_FILE_SIZE_BYTES:
        return jsonify({"error": "VALIDATION_ERROR", "message": "File exceeds 10MB limit."}), 400

    if not _allowed_file(file.filename, file.mimetype):
        return jsonify({"error": "INVALID_IMAGE", "message": "Only JPEG/PNG images are accepted."}), 400

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    safe_name = secure_filename(file.filename)
    stored_name = f"{uuid.uuid4().hex}_{safe_name}"
    file_path = os.path.join(UPLOAD_DIR, stored_name)
    file.save(file_path)

    product_name = request.form.get("product_name")
    audit_date = request.form.get("audit_date") or date.today().isoformat()
    source = request.form.get("source", "UPLOAD")
    if source not in ("CAMERA", "UPLOAD", "ECOMMERCE_LISTING", "DEMO"):
        source = "UPLOAD"

    with get_db() as cur:
        cur.execute(
            "INSERT INTO product (name, organization_id) VALUES (?, ?)",
            (product_name, g.user["organization_id"]),
        )
        product_id = cur.lastrowid

        cur.execute(
            "INSERT INTO product_image (product_id, file_path, source, uploaded_by) VALUES (?,?,?,?)",
            (product_id, file_path, source, g.user["id"]),
        )
        product_image_id = cur.lastrowid

        cur.execute(
            """INSERT INTO compliance_check
               (product_id, product_image_id, submitted_by, organization_id, status, audit_date)
               VALUES (?,?,?,?,'QUEUED',?)""",
            (product_id, product_image_id, g.user["id"], g.user["organization_id"], audit_date),
        )
        check_id = cur.lastrowid

    audit.log(g.user["id"], "CHECK_SUBMITTED", "compliance_check", check_id,
              metadata={"file": stored_name, "source": source})

    return jsonify({"check_id": check_id, "status": "QUEUED"}), 201


@bp.post("/<int:check_id>/process")
@require_auth
def process_check(check_id):
    """Runs the pipeline synchronously and returns the outcome. A single
    demo-grade image processes in seconds on this hardware, which is why
    MVP calls this inline rather than requiring a poll loop -- the `job`
    table and this endpoint's shape are what a Celery task queue would sit
    behind for bulk/async processing (docs/ARCHITECTURE.md)."""
    with get_db() as cur:
        cur.execute("SELECT * FROM compliance_check WHERE id=?", (check_id,))
        check = row_to_dict(cur.fetchone())
    if check is None:
        return jsonify({"error": "NOT_FOUND"}), 404
    scope = organization_scoped_filter(g.user)
    if scope is not None and check["organization_id"] != scope:
        return jsonify({"error": "FORBIDDEN"}), 403

    try:
        result = run_pipeline(check_id)
    except Exception as exc:
        return jsonify({"error": "PROCESSING_FAILED", "message": str(exc)}), 500

    return jsonify(result)


def _check_row_summary(check: dict) -> dict:
    return {
        "id": check["id"], "status": check["status"], "category": check["category"],
        "created_at": check["created_at"], "completed_at": check["completed_at"],
        "image_quality_score": check["image_quality_score"],
        "rule_version_id": check["rule_version_id"],
    }


@bp.get("")
@require_auth
def list_checks():
    scope = organization_scoped_filter(g.user)
    query = """SELECT cc.*, p.name as product_name FROM compliance_check cc
               LEFT JOIN product p ON p.id = cc.product_id"""
    params = []
    if scope is not None:
        query += " WHERE cc.organization_id = ?"
        params.append(scope)
    query += " ORDER BY cc.created_at DESC LIMIT 200"
    with get_db() as cur:
        cur.execute(query, params)
        checks = rows_to_list(cur.fetchall())
    return jsonify({"checks": checks})


@bp.get("/<int:check_id>")
@require_auth
def get_check(check_id):
    with get_db() as cur:
        cur.execute(
            """SELECT cc.*, p.name as product_name FROM compliance_check cc
               LEFT JOIN product p ON p.id = cc.product_id WHERE cc.id=?""", (check_id,))
        check = row_to_dict(cur.fetchone())
    if check is None:
        return jsonify({"error": "NOT_FOUND"}), 404
    scope = organization_scoped_filter(g.user)
    if scope is not None and check["organization_id"] != scope:
        return jsonify({"error": "FORBIDDEN"}), 403
    return jsonify(check)


@bp.get("/<int:check_id>/results")
@require_auth
def get_results(check_id):
    with get_db() as cur:
        cur.execute("SELECT * FROM compliance_check WHERE id=?", (check_id,))
        check = row_to_dict(cur.fetchone())
        if check is None:
            return jsonify({"error": "NOT_FOUND"}), 404
        cur.execute(
            """SELECT rr.*, req.requirement_name, req.field_type, req.severity
               FROM requirement_result rr
               JOIN rule_requirement req ON req.id = rr.rule_requirement_id
               WHERE rr.compliance_check_id=? ORDER BY rr.id""", (check_id,))
        results = rows_to_list(cur.fetchall())
        cur.execute("SELECT * FROM extracted_field WHERE compliance_check_id=?", (check_id,))
        fields = rows_to_list(cur.fetchall())

    for r in results:
        r["extracted_field_ids"] = from_json(r["extracted_field_ids"], [])
    for f in fields:
        f["normalized_value"] = from_json(f["normalized_value"])
        f["bounding_box"] = from_json(f["bounding_box"])

    return jsonify({"check": check, "results": results, "fields": fields})


@bp.get("/<int:check_id>/evidence")
@require_auth
def get_evidence(check_id):
    with get_db() as cur:
        cur.execute("SELECT * FROM evidence_item WHERE compliance_check_id=?", (check_id,))
        items = rows_to_list(cur.fetchall())
    return jsonify({"evidence": items})


@bp.get("/<int:check_id>/evidence/<kind>")
@require_auth
def get_evidence_image(check_id, kind):
    with get_db() as cur:
        cur.execute(
            "SELECT * FROM evidence_item WHERE compliance_check_id=? AND kind=? ORDER BY id DESC LIMIT 1",
            (check_id, kind.upper()))
        item = row_to_dict(cur.fetchone())
    if item is None or not os.path.exists(item["file_path"]):
        return jsonify({"error": "NOT_FOUND"}), 404
    return send_file(item["file_path"], mimetype="image/jpeg")


@bp.post("/<int:check_id>/report")
@require_auth
def create_report(check_id):
    try:
        path = reports_module.generate_report(check_id, g.user["id"])
    except ValueError as exc:
        return jsonify({"error": "NOT_FOUND", "message": str(exc)}), 404
    audit.log(g.user["id"], "REPORT_GENERATED", "compliance_check", check_id)
    return jsonify({"report_path": path})


@bp.get("/<int:check_id>/report")
@require_auth
def download_report(check_id):
    with get_db() as cur:
        cur.execute("SELECT * FROM report WHERE compliance_check_id=? ORDER BY id DESC LIMIT 1", (check_id,))
        report = row_to_dict(cur.fetchone())
    if report is None:
        path = reports_module.generate_report(check_id, g.user["id"])
    else:
        path = report["file_path"]
    if not os.path.exists(path):
        return jsonify({"error": "NOT_FOUND"}), 404
    return send_file(path, mimetype="application/pdf", as_attachment=True,
                      download_name=f"veripack_report_{check_id}.pdf")
